"""
Request identity helpers.

The backend uses a Supabase service-role key for database operations, so RLS
does not protect API routes by itself. Every user-scoped endpoint must derive
the user ID from a verified token instead of trusting request payloads.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, status

from config import settings
import supabase_client


ANON_TOKEN_PREFIX = "anon"


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    is_cloud: bool


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _anonymous_secret() -> bytes:
    secret = (
        settings.anonymous_token_secret
        or settings.supabase_service_key
        or settings.google_api_key
    )
    if not secret:
        if settings.environment == "production":
            raise RuntimeError("ANONYMOUS_TOKEN_SECRET must be configured in production")
        secret = "stepwise-development-anonymous-token-secret"
    return secret.encode("utf-8")


def create_anonymous_token() -> tuple[str, str, int]:
    """Create a signed backend-owned anonymous identity token."""
    now = int(time.time())
    exp = now + settings.anonymous_token_ttl_seconds
    user_id = str(uuid.uuid4())
    payload = {
        "typ": "anonymous",
        "sub": user_id,
        "iat": now,
        "exp": exp,
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        _anonymous_secret(),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    token = f"{ANON_TOKEN_PREFIX}.{payload_b64}.{_b64url_encode(signature)}"
    return user_id, token, exp


def _verify_anonymous_token(token: str) -> AuthContext:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != ANON_TOKEN_PREFIX:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid anonymous token")

    payload_b64 = parts[1]
    expected_sig = hmac.new(
        _anonymous_secret(),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_sig = _b64url_decode(parts[2])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid anonymous token")
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid anonymous token")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
        user_id = str(payload["sub"])
        exp = int(payload["exp"])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid anonymous token")

    if payload.get("typ") != "anonymous" or exp <= int(time.time()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Anonymous token expired")

    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid anonymous subject")

    return AuthContext(user_id=user_id, is_cloud=False)


async def _verify_supabase_token(token: str) -> AuthContext:
    """Verify a Supabase access token by asking Supabase Auth for the user."""
    try:
        client = supabase_client.get_supabase()
        result = client.auth.get_user(token)
        user = result.user
        user_id = str(user.id)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token")

    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user subject")

    return AuthContext(user_id=user_id, is_cloud=True)


async def require_auth_context(
    authorization: Optional[str] = Header(default=None),
) -> AuthContext:
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Authorization header")

    if token.startswith(f"{ANON_TOKEN_PREFIX}."):
        return _verify_anonymous_token(token)

    return await _verify_supabase_token(token)


def require_matching_user(auth: AuthContext, supplied_user_id: Optional[str]) -> str:
    """Reject attempts to act as a different user."""
    if supplied_user_id and supplied_user_id != auth.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_id does not match token")
    return auth.user_id


def require_cloud_user(auth: AuthContext) -> str:
    if not auth.is_cloud:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cloud sign-in required")
    return auth.user_id
