"""
Supabase Client for the AI STEM Tutor.

Singleton wrapper for the Supabase Python client. Uses the SERVICE ROLE KEY,
which bypasses RLS — every query MUST include .eq('user_id', ...) manually.

Provides typed helpers for profiles, sessions, messages, and saved problems.
"""

import logging
import uuid as _uuid_mod
from typing import Optional

from supabase import create_client, Client
from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_client: Optional[Client] = None


def get_supabase() -> Client:
    """Get or create the Supabase client singleton."""
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env"
            )
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
        logger.info("Supabase client initialized (service role)")
    return _client


def _is_valid_uuid(value: str) -> bool:
    """Return True if *value* is a valid UUID (v4 or any version)."""
    try:
        _uuid_mod.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

async def get_profile(user_id: str) -> Optional[dict]:
    """Fetch a user's profile. Returns None if not found."""
    if not _is_valid_uuid(user_id):
        return None
    client = get_supabase()
    result = (
        client.table("profiles")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data


async def upsert_profile(user_id: str, **fields) -> dict:
    """Create or update a user profile. Always scoped to user_id."""
    if not _is_valid_uuid(user_id):
        return {"id": user_id, **fields}
    client = get_supabase()
    data = {"id": user_id, **fields}
    result = (
        client.table("profiles")
        .upsert(data, on_conflict="id")
        .execute()
    )
    return result.data[0] if result.data else data


async def set_backboard_assistant_id(user_id: str, assistant_id: str) -> None:
    """
    Save a Backboard assistant ID to the user's profile.
    Called after the compensating-transaction pattern:
      1. Create assistant in Backboard
      2. Write ID here
      If step 2 fails, caller must delete the assistant (rollback).
    """
    if not _is_valid_uuid(user_id):
        logger.debug(f"Skipping set_backboard_assistant_id for non-UUID user: {user_id}")
        return
    
    # Ensure user_id is a string (pydantic models might pass UUID objects)
    user_id_str = str(user_id)
    
    client = get_supabase()
    client.table("profiles").update(
        {"backboard_assistant_id": assistant_id}
    ).eq("id", user_id_str).execute()


async def get_backboard_assistant_id(user_id: str) -> Optional[str]:
    """Get the per-user Backboard assistant ID from their profile."""
    profile = await get_profile(user_id)
    if profile:
        return profile.get("backboard_assistant_id")
    return None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

async def create_session(
    user_id: str,
    title: str = "",
    topic: str = "",
    model: str = "",
    langgraph_thread_id: str = "",
) -> dict:
    """Create a new chat session. Returns the inserted row."""
    if not _is_valid_uuid(user_id):
        logger.debug(f"Skipping create_session for non-UUID user: {user_id}")
        return {"id": None}
    client = get_supabase()
    result = (
        client.table("chat_sessions")
        .insert({
            "user_id": user_id,
            "title": title,
            "topic": topic,
            "model": model,
            "langgraph_thread_id": langgraph_thread_id,
        })
        .execute()
    )
    return result.data[0]


async def get_user_sessions(
    user_id: str, limit: int = 20, offset: int = 0, include_archived: bool = False
) -> list[dict]:
    """Get paginated sessions for the sidebar history."""
    if not _is_valid_uuid(user_id):
        return []
    client = get_supabase()
    query = (
        client.table("chat_sessions")
        .select("*")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if not include_archived:
        query = query.eq("archived", False)
    result = query.execute()
    return result.data or []


async def update_session(session_id: str, user_id: str, **fields) -> dict:
    """Update a session. Scoped to user_id for safety."""
    client = get_supabase()
    result = (
        client.table("chat_sessions")
        .update(fields)
        .eq("id", session_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else {}


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------

async def save_message(
    session_id: str,
    user_id: str,
    role: str,
    content_text: str = "",
    content_json: Optional[dict] = None,
) -> dict:
    """Insert a chat message. Both session_id and user_id are required."""
    if not _is_valid_uuid(user_id) or not session_id:
        return {}
    client = get_supabase()
    row = {
        "session_id": session_id,
        "user_id": user_id,
        "role": role,
        "content_text": content_text,
    }
    if content_json is not None:
        row["content_json"] = content_json
    result = client.table("chat_messages").insert(row).execute()
    return result.data[0]


async def get_session_messages(
    session_id: str, user_id: str
) -> list[dict]:
    """Get all messages for a session, ordered chronologically."""
    if not _is_valid_uuid(user_id):
        return []
    client = get_supabase()
    result = (
        client.table("chat_messages")
        .select("*")
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# Saved problems helpers
# ---------------------------------------------------------------------------

async def save_problem(
    user_id: str,
    problem_text: str,
    topic: str = "",
    solution_summary: str = "",
    solution_json: Optional[dict] = None,
    problem_hash: str = "",
    source: str = "typed",
) -> dict:
    """Save a problem to the user's library."""
    if not _is_valid_uuid(user_id):
        return {}
    client = get_supabase()
    row = {
        "user_id": user_id,
        "problem_text": problem_text,
        "topic": topic,
        "solution_summary": solution_summary,
        "problem_hash": problem_hash,
        "source": source,
    }
    if solution_json is not None:
        row["solution_json"] = solution_json
    result = client.table("saved_problems").insert(row).execute()
    return result.data[0]


async def get_saved_problems(
    user_id: str, limit: int = 20, offset: int = 0
) -> list[dict]:
    """Get paginated saved problems for a user."""
    if not _is_valid_uuid(user_id):
        return []
    client = get_supabase()
    result = (
        client.table("saved_problems")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# Feedback helpers
# ---------------------------------------------------------------------------

async def save_feedback(
    user_id: str,
    rating: int,
    session_id: Optional[str] = None,
    message_id: Optional[str] = None,
    comment: str = "",
) -> dict:
    """Save user feedback on a session or specific message."""
    if not _is_valid_uuid(user_id):
        return {}
    client = get_supabase()
    row = {
        "user_id": user_id,
        "rating": rating,
        "comment": comment,
    }
    if session_id:
        row["session_id"] = session_id
    if message_id:
        row["message_id"] = message_id
    result = client.table("feedback").insert(row).execute()
    return result.data[0]


# ---------------------------------------------------------------------------
# Video cache helpers (global, not user-scoped)
# ---------------------------------------------------------------------------

async def get_cached_videos(problem_hash: str) -> Optional[dict]:
    """Get cached YouTube results for a problem hash."""
    client = get_supabase()
    result = (
        client.table("video_cache")
        .select("*")
        .eq("problem_hash", problem_hash)
        .maybe_single()
        .execute()
    )
    return result.data


async def cache_videos(
    problem_hash: str, videos: list[dict], grade_level: str = ""
) -> None:
    """Cache YouTube results for a problem hash."""
    client = get_supabase()
    client.table("video_cache").upsert({
        "problem_hash": problem_hash,
        "videos": videos,
        "grade_level": grade_level,
    }, on_conflict="problem_hash").execute()


# ---------------------------------------------------------------------------
# Supabase Storage helpers (image offload)
# ---------------------------------------------------------------------------

STORAGE_BUCKET = "problem-images"


async def ensure_storage_bucket() -> None:
    """Create the problem-images bucket if it doesn't exist (idempotent)."""
    client = get_supabase()
    try:
        client.storage.get_bucket(STORAGE_BUCKET)
        logger.debug(f"Storage bucket '{STORAGE_BUCKET}' already exists")
    except Exception:
        try:
            client.storage.create_bucket(
                STORAGE_BUCKET,
                options={
                    "public": True,
                    "file_size_limit": 10 * 1024 * 1024,  # 10MB
                    "allowed_mime_types": ["image/png", "image/jpeg", "image/webp"],
                },
            )
            logger.info(f"Created storage bucket '{STORAGE_BUCKET}'")
        except Exception as e:
            # Bucket may already exist from a parallel init
            if "already exists" in str(e).lower():
                logger.debug(f"Bucket '{STORAGE_BUCKET}' already exists (race)")
            else:
                raise


async def upload_image(base64_data: str, thread_id: str) -> str:
    """Upload a base64-encoded image to Supabase Storage.

    Returns the public URL of the uploaded image.
    """
    import base64 as b64

    client = get_supabase()
    image_bytes = b64.b64decode(base64_data)

    # Determine content type from magic bytes
    content_type = "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        content_type = "image/jpeg"

    ext = "png" if content_type == "image/png" else "jpg"
    path = f"{thread_id}.{ext}"

    client.storage.from_(STORAGE_BUCKET).upload(
        path,
        image_bytes,
        file_options={"content-type": content_type, "upsert": "true"},
    )

    public_url = client.storage.from_(STORAGE_BUCKET).get_public_url(path)
    logger.info(f"Uploaded image to storage: {path} ({len(image_bytes)} bytes)")
    return public_url


async def download_image_bytes(url: str) -> bytes:
    """Download image bytes from a Supabase Storage public URL."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()
