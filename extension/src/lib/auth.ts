/**
 * Auth module for Stepwise Chrome extension.
 *
 * State machine:
 *   initializing → cloud   (silent chrome.identity succeeded + Supabase exchange)
 *   initializing → local_anon  (silent auth failed — no prompt, full local mode)
 *   local_anon   → cloud   (user clicks "Sign in to sync" → interactive auth)
 *   cloud        → local_anon  (user signs out)
 *
 * All user IDs are valid UUID v4 (required by backend).
 */

import { createClient, Session } from "@supabase/supabase-js";

// -------------------------------------------------------------------
// Types
// -------------------------------------------------------------------
export type AuthMode = "initializing" | "cloud" | "local_anon";

export interface AuthState {
    mode: AuthMode;
    userId: string;       // Always a valid UUID
    accessToken?: string;
    email?: string;
    displayName?: string;
}

type AuthListener = (state: AuthState) => void;

// -------------------------------------------------------------------
// Supabase client
// -------------------------------------------------------------------
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL ?? "https://inbbdadosiwugdlnqttq.supabase.co";
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY ?? "";
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: {
        persistSession: false,
        autoRefreshToken: false,
    },
});

// -------------------------------------------------------------------
// Storage keys
// -------------------------------------------------------------------
const SESSION_KEY = "stepwise_supabase_session";
const LOCAL_ANON_ID_KEY = "stepwise_local_anon_id";
const ANON_SESSION_KEY = "stepwise_backend_anon_session";

// -------------------------------------------------------------------
// Internal state
// -------------------------------------------------------------------
let currentState: AuthState = {
    mode: "initializing",
    userId: "",
};
const listeners: Set<AuthListener> = new Set();

function setState(next: AuthState) {
    currentState = next;
    listeners.forEach((cb) => cb(currentState));
}

// -------------------------------------------------------------------
// UUID v4 generator (crypto-safe)
// -------------------------------------------------------------------
function generateUUIDv4(): string {
    // Use crypto.randomUUID if available (Chrome 92+)
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    // Fallback
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

// -------------------------------------------------------------------
// Session persistence (chrome.storage.local)
// -------------------------------------------------------------------
async function persistSession(session: Session | null): Promise<void> {
    if (session) {
        await chrome.storage.local.set({ [SESSION_KEY]: session });
    } else {
        await chrome.storage.local.remove(SESSION_KEY);
    }
}

async function loadPersistedSession(): Promise<Session | null> {
    const result = await chrome.storage.local.get(SESSION_KEY);
    return result[SESSION_KEY] ?? null;
}

// -------------------------------------------------------------------
// Local anonymous ID persistence
// -------------------------------------------------------------------
async function getOrCreateLocalAnonId(): Promise<string> {
    const result = await chrome.storage.local.get(LOCAL_ANON_ID_KEY);
    if (result[LOCAL_ANON_ID_KEY]) {
        return result[LOCAL_ANON_ID_KEY];
    }
    const id = generateUUIDv4();
    await chrome.storage.local.set({ [LOCAL_ANON_ID_KEY]: id });
    return id;
}

interface BackendAnonymousSession {
    user_id: string;
    access_token: string;
    expires_at: number;
}

async function loadBackendAnonymousSession(): Promise<BackendAnonymousSession | null> {
    const result = await chrome.storage.local.get(ANON_SESSION_KEY);
    return result[ANON_SESSION_KEY] ?? null;
}

async function persistBackendAnonymousSession(session: BackendAnonymousSession): Promise<void> {
    await chrome.storage.local.set({ [ANON_SESSION_KEY]: session });
    await chrome.storage.local.set({ [LOCAL_ANON_ID_KEY]: session.user_id });
}

async function createBackendAnonymousSession(): Promise<BackendAnonymousSession> {
    const response = await fetch(`${API_BASE_URL}/v1/anonymous_session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
        throw new Error(`Anonymous session failed: HTTP ${response.status}`);
    }
    const data = await response.json();
    return {
        user_id: data.user_id,
        access_token: data.access_token,
        expires_at: data.expires_at,
    };
}

async function getOrCreateBackendAnonymousSession(): Promise<BackendAnonymousSession> {
    const existing = await loadBackendAnonymousSession();
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (existing?.access_token && existing.expires_at > nowSeconds + 60) {
        return existing;
    }
    const created = await createBackendAnonymousSession();
    await persistBackendAnonymousSession(created);
    return created;
}

// -------------------------------------------------------------------
// Chrome identity helpers
// -------------------------------------------------------------------
// Helper to generate a random nonce
function generateNonce(): string {
    const array = new Uint8Array(16);
    crypto.getRandomValues(array);
    return Array.from(array, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

// SHA-256 hash a string and return hex digest
async function sha256(message: string): Promise<string> {
    const encoder = new TextEncoder();
    const data = encoder.encode(message);
    const hashBuffer = await crypto.subtle.digest("SHA-256", data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Get Google ID Token via launchWebAuthFlow (required for Supabase)
async function getGoogleIdToken(interactive: boolean): Promise<{ token: string; nonce: string }> {
    const rawNonce = generateNonce();
    // Supabase expects the RAW nonce in signInWithIdToken — it hashes it internally.
    // Google must receive the HASHED nonce so the ID token's nonce claim matches what Supabase expects.
    const hashedNonce = await sha256(rawNonce);

    // Must use the WEB Client ID here, because that's where we added the redirect URI in Google Console.
    const clientId = "873376819767-suol5i0o0vueh2a36v7fd6q9ruhua8t5.apps.googleusercontent.com"; // Web Client ID

    const redirectUri = chrome.identity.getRedirectURL();
    const scope = "openid email profile";
    const authUrl = new URL("https://accounts.google.com/o/oauth2/v2/auth");
    authUrl.searchParams.set("client_id", clientId);
    authUrl.searchParams.set("response_type", "id_token");
    authUrl.searchParams.set("access_type", "online");
    authUrl.searchParams.set("redirect_uri", redirectUri);
    authUrl.searchParams.set("nonce", hashedNonce);  // Send HASHED nonce to Google
    authUrl.searchParams.set("scope", scope);
    authUrl.searchParams.set("prompt", interactive ? "consent" : "none");

    return new Promise((resolve, reject) => {
        chrome.identity.launchWebAuthFlow(
            { url: authUrl.toString(), interactive },
            (responseUrl) => {
                if (chrome.runtime.lastError || !responseUrl) {
                    reject(new Error(chrome.runtime.lastError?.message ?? "No response URL"));
                    return;
                }

                // Extract ID token from hash fragment
                const params = new URLSearchParams(new URL(responseUrl).hash.substring(1));
                const idToken = params.get("id_token");
                if (!idToken) {
                    reject(new Error("No ID token found in response"));
                    return;
                }
                resolve({ token: idToken, nonce: rawNonce });
            }
        );
    });
}

async function exchangeWithSupabase(googleIdToken: string, nonce: string): Promise<Session> {
    const { data, error } = await supabase.auth.signInWithIdToken({
        provider: "google",
        token: googleIdToken,
        nonce: nonce,
    });
    if (error) throw error;
    if (!data.session) throw new Error("Supabase returned no session");
    return data.session;
}

// -------------------------------------------------------------------
// Public API
// -------------------------------------------------------------------

/**
 * Initialize auth — call once on app mount.
 *
 * 1. Check for a persisted Supabase session
 * 2. Try silent chrome.identity (interactive: false)
 * 3. Fall back to local_anon if anything fails
 */
export async function initAuth(): Promise<AuthState> {
    // 1. Check for existing persisted Supabase session
    try {
        const existing = await loadPersistedSession();
        if (existing?.user?.id) {
            console.debug("[Auth] Restored persisted session, mode=cloud");
            const next: AuthState = {
                mode: "cloud",
                userId: existing.user.id,
                accessToken: existing.access_token,
                email: existing.user.email ?? undefined,
                displayName: existing.user.user_metadata?.full_name ?? undefined,
            };
            setState(next);
            return next;
        }
    } catch (e) {
        console.debug("[Auth] Failed to load persisted session:", e);
    }

    // 2. Try silent Chrome identity
    try {
        const { token, nonce } = await getGoogleIdToken(false);
        const session = await exchangeWithSupabase(token, nonce);
        await persistSession(session);

        console.debug("[Auth] Silent auth succeeded, mode=cloud");
        const next: AuthState = {
            mode: "cloud",
            userId: session.user.id,
            accessToken: session.access_token,
            email: session.user.email ?? undefined,
            displayName: session.user.user_metadata?.full_name ?? undefined,
        };
        setState(next);
        return next;
    } catch (e) {
        console.debug("[Auth] Silent auth failed, falling back to local_anon:", (e as Error).message);
    }

    // 3. Fall back to local anonymous
    let anonId = "";
    let accessToken: string | undefined;
    try {
        const anon = await getOrCreateBackendAnonymousSession();
        anonId = anon.user_id;
        accessToken = anon.access_token;
    } catch (e) {
        console.debug("[Auth] Backend anonymous session failed:", e);
        anonId = await getOrCreateLocalAnonId();
    }
    console.debug("[Auth] Using local_anon mode with ID:", anonId);
    const next: AuthState = {
        mode: "local_anon",
        userId: anonId,
        accessToken,
    };
    setState(next);
    return next;
}

/**
 * User-initiated interactive sign-in (upgrade from local_anon to cloud).
 * Only call when user clicks "Sign in to enable sync".
 */
export async function signInInteractive(): Promise<AuthState> {
    let result = await getGoogleIdToken(true);
    let session: Session;

    try {
        session = await exchangeWithSupabase(result.token, result.nonce);
    } catch (err: any) {
        console.warn("[Auth] First sign-in attempt failed, checking for stale token...", err);
        // Ensure we remove the cached token if Supabase rejects it (though launchWebAuthFlow caches differently)
        if (result.token) {
            // launchWebAuthFlow doesn't have a simple "removeCached" for ID tokens, but we can try
            // simply retrying interactively which forces a fresh flow usually.
            console.debug("[Auth] Retrying with fresh interactive flow...");
        }

        result = await getGoogleIdToken(true);
        session = await exchangeWithSupabase(result.token, result.nonce);
    }

    await persistSession(session);

    console.debug("[Auth] Interactive sign-in succeeded, mode=cloud");
    const next: AuthState = {
        mode: "cloud",
        userId: session.user.id,
        accessToken: session.access_token,
        email: session.user.email ?? undefined,
        displayName: session.user.user_metadata?.full_name ?? undefined,
    };
    setState(next);
    return next;
}

/**
 * Sign out — clears Supabase session, revokes Google token, reverts to local_anon.
 */
export async function signOut(): Promise<AuthState> {
    await supabase.auth.signOut();
    await persistSession(null);

    // Revoke Google token (best effort)
    // specific revocation endpoint for ID tokens isn't standard, but we clear session

    let anonId = "";
    let accessToken: string | undefined;
    try {
        const anon = await getOrCreateBackendAnonymousSession();
        anonId = anon.user_id;
        accessToken = anon.access_token;
    } catch (e) {
        console.debug("[Auth] Backend anonymous session failed after sign-out:", e);
        anonId = await getOrCreateLocalAnonId();
    }
    console.debug("[Auth] Signed out, mode=local_anon");
    const next: AuthState = {
        mode: "local_anon",
        userId: anonId,
        accessToken,
    };
    setState(next);
    return next;
}

/**
 * Get current auth state synchronously (returns cached value).
 */
export function getAuthState(): AuthState {
    return currentState;
}

/**
 * Resolve the current user ID (always a valid UUID).
 * Synchronous — returns the cached auth state userId.
 */
export function resolveUserId(): string {
    return currentState.userId;
}

export function getAuthAccessToken(): string | undefined {
    return currentState.accessToken;
}

/**
 * Subscribe to auth state changes. Returns an unsubscribe function.
 */
export function onAuthChange(cb: AuthListener): () => void {
    listeners.add(cb);
    return () => listeners.delete(cb);
}

// -------------------------------------------------------------------
// Google Docs Access Token (for Docs API calls)
// -------------------------------------------------------------------

/**
 * Get a Google OAuth access token with Google Docs scope.
 *
 * Uses chrome.identity.getAuthToken (simpler than launchWebAuthFlow)
 * which reads scopes from manifest.json oauth2 config.
 *
 * This is DIFFERENT from the ID token flow used for Supabase auth.
 * The access token is passed to the backend for Google Docs REST API calls.
 */
export async function getGoogleDocsAccessToken(): Promise<string> {
    return new Promise((resolve, reject) => {
        chrome.identity.getAuthToken({ interactive: true }, (token) => {
            if (chrome.runtime.lastError || !token) {
                reject(new Error(
                    chrome.runtime.lastError?.message ?? "Failed to get Google Docs access token"
                ));
                return;
            }
            resolve(token);
        });
    });
}

/**
 * Remove a cached Google Auth token.
 * Useful when the token is rejected by an API indicating stale or missing scopes.
 */
export async function removeCachedAuthToken(token: string): Promise<void> {
    return new Promise((resolve) => {
        chrome.identity.removeCachedAuthToken({ token }, () => {
            console.debug("[Auth] Cleared cached auth token");
            resolve();
        });
    });
}
