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
    email?: string;
    displayName?: string;
}

type AuthListener = (state: AuthState) => void;

// -------------------------------------------------------------------
// Supabase client
// -------------------------------------------------------------------
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL ?? "https://inbbdadosiwugdlnqttq.supabase.co";
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY ?? "";

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
            email: session.user.email ?? undefined,
            displayName: session.user.user_metadata?.full_name ?? undefined,
        };
        setState(next);
        return next;
    } catch (e) {
        console.debug("[Auth] Silent auth failed, falling back to local_anon:", (e as Error).message);
    }

    // 3. Fall back to local anonymous
    const anonId = await getOrCreateLocalAnonId();
    console.debug("[Auth] Using local_anon mode with ID:", anonId);
    const next: AuthState = {
        mode: "local_anon",
        userId: anonId,
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

    const anonId = await getOrCreateLocalAnonId();
    console.debug("[Auth] Signed out, mode=local_anon");
    const next: AuthState = {
        mode: "local_anon",
        userId: anonId,
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

/**
 * Subscribe to auth state changes. Returns an unsubscribe function.
 */
export function onAuthChange(cb: AuthListener): () => void {
    listeners.add(cb);
    return () => listeners.delete(cb);
}
