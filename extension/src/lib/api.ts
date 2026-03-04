/**
 * API Client for communicating with the Python backend
 */

import type {
    AnalyzeRequest,
    AnalyzeResponse,
    ResumeRequest,
    HealthResponse,
    PracticeRequest,
    PracticeResponse,
    ExpandStepRequest,
    ExpandStepResponse,
    ResourcesRequest,
    ResourcesResponse,
} from './types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class APIError extends Error {
    constructor(
        message: string,
        public status?: number,
        public data?: unknown
    ) {
        super(message);
        this.name = 'APIError';
    }
}

export class RateLimitError extends APIError {
    public retryAfter: number;
    public remaining: number;
    public limit: number;

    constructor(data: { message: string; retry_after: number; remaining: number; limit: number }) {
        super(data.message, 429, data);
        this.name = 'RateLimitError';
        this.retryAfter = data.retry_after;
        this.remaining = data.remaining;
        this.limit = data.limit;
    }
}

async function fetchAPI<T>(
    endpoint: string,
    options: RequestInit = {}
): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;

    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));

            // Handle rate limit specifically
            if (response.status === 429) {
                throw new RateLimitError({
                    message: errorData.message || 'Rate limit exceeded',
                    retry_after: errorData.retry_after || 60,
                    remaining: 0,
                    limit: errorData.limit || 5
                });
            }

            throw new APIError(
                errorData.detail || `HTTP ${response.status}: ${response.statusText}`,
                response.status,
                errorData
            );
        }

        return await response.json();
    } catch (error) {
        if (error instanceof APIError) {
            throw error;
        }
        throw new APIError(
            error instanceof Error ? error.message : 'Network request failed'
        );
    }
}

/**
 * Check backend health
 */
export async function checkHealth(): Promise<HealthResponse> {
    return fetchAPI<HealthResponse>('/health');
}

/**
 * Analyze a math problem (text or image)
 */
export async function analyzeProblem(
    request: AnalyzeRequest
): Promise<AnalyzeResponse> {
    return fetchAPI<AnalyzeResponse>('/v1/analyze', {
        method: 'POST',
        body: JSON.stringify(request),
    });
}

/**
 * Resume workflow after topic selection
 */
export async function resumeWorkflow(
    request: ResumeRequest
): Promise<AnalyzeResponse> {
    return fetchAPI<AnalyzeResponse>('/v1/resume', {
        method: 'POST',
        body: JSON.stringify(request),
    });
}

/**
 * Expand a step into sub-steps
 */
export async function expandStep(
    request: ExpandStepRequest
): Promise<ExpandStepResponse> {
    return fetchAPI<ExpandStepResponse>('/v1/expand_step', {
        method: 'POST',
        body: JSON.stringify(request),
    });
}

/**
 * Generate practice problems on-demand
 */
export async function generatePractice(
    request: PracticeRequest
): Promise<PracticeResponse> {
    return fetchAPI<PracticeResponse>('/v1/practice', {
        method: 'POST',
        body: JSON.stringify(request),
    });
}

/**
 * Get current rate limit quota status
 */
export interface QuotaResponse {
    remaining: number;
    limit: number;
    window_seconds: number;
    reset_in_seconds: number;
    tier: string;
}

export async function getQuota(userId: string = 'anonymous'): Promise<QuotaResponse> {
    return fetchAPI<QuotaResponse>(`/v1/quota?user_id=${encodeURIComponent(userId)}`);
}

/**
 * Get YouTube video resources for a problem
 */
export async function getYouTubeResources(
    request: ResourcesRequest
): Promise<ResourcesResponse> {
    return fetchAPI<ResourcesResponse>('/v1/resources', {
        method: 'POST',
        body: JSON.stringify(request),
    });
}

// ============================================================================
// Backboard Profiling APIs (Student Adaptive Learning)
// ============================================================================

interface LogBreakdownRequest {
    user_id: string;
    step_title: string;
    concept: string;
    context: string;
}

interface LogQuizResultRequest {
    user_id: string;
    concept: string;
    correct: boolean;
    question_summary: string;
}

/**
 * Log when a student clicks "breakdown" on a step (struggle signal)
 * This is fire-and-forget - failures are silently ignored
 */
export async function logBreakdown(request: LogBreakdownRequest): Promise<void> {
    try {
        await fetchAPI<{ status: string }>('/v1/log_breakdown', {
            method: 'POST',
            body: JSON.stringify(request),
        });
    } catch (e) {
        // Silent fail - profiling is non-critical
        console.debug('[Backboard] logBreakdown failed:', e);
    }
}

/**
 * Log quiz/practice results for mastery tracking
 * This is fire-and-forget - failures are silently ignored
 */
export async function logQuizResult(request: LogQuizResultRequest): Promise<void> {
    try {
        await fetchAPI<{ status: string }>('/v1/log_quiz_result', {
            method: 'POST',
            body: JSON.stringify(request),
        });
    } catch (e) {
        // Silent fail - profiling is non-critical
        console.debug('[Backboard] logQuizResult failed:', e);
    }
}

// ============================================================================
// SIMILAR PROBLEMS (Semantic Search)
// ============================================================================

interface SimilarProblemsRequest {
    user_id: string;
    topic: string;
    problem_text: string;
}

interface SimilarProblem {
    topic: string;
    similarity: number;
}

interface SimilarProblemsResponse {
    similar_problems: SimilarProblem[];
    suggested_folder_name: string | null;
}

/**
 * Find semantically similar problems from Backboard memory.
 * Used for smart grouping suggestions in history view.
 */
export async function getSimilarProblems(request: SimilarProblemsRequest): Promise<SimilarProblemsResponse> {
    try {
        const response = await fetchAPI<SimilarProblemsResponse>('/v1/similar_problems', {
            method: 'POST',
            body: JSON.stringify(request),
        });
        return response;
    } catch (e) {
        console.debug('[Backboard] getSimilarProblems failed:', e);
        return { similar_problems: [], suggested_folder_name: null };
    }
}

// ============================================================================
// SEMANTIC FOLDER MANAGEMENT
// ============================================================================

interface SuggestFolderRequest {
    user_id: string;
    session_id: string;
    topic: string;
    problem_text: string;
}

export interface FolderSuggestion {
    action: 'add_to_folder' | 'suggest_new_folder' | 'no_suggestion';
    folder_id: string | null;
    folder_name: string | null;
    similarity_score: number;
    similar_unfiled: { session_id: string }[];
    alternate_folder: { folder_id: string; folder_name: string; score: number } | null;
}

/**
 * Sync folder definition to Backboard memory.
 * Called when folder is created or renamed.
 */
export async function syncFolder(userId: string, folderId: string, folderName: string): Promise<void> {
    try {
        await fetchAPI<{ status: string }>('/v1/sync_folder', {
            method: 'POST',
            body: JSON.stringify({
                user_id: userId,
                folder_id: folderId,
                folder_name: folderName,
            }),
        });
        console.debug('[Backboard] Folder synced:', folderId, '->', folderName);
    } catch (e) {
        console.debug('[Backboard] syncFolder failed:', e);
    }
}

/**
 * Get semantic folder suggestion for a problem.
 * Uses 0.85 similarity threshold.
 */
export async function suggestFolder(request: SuggestFolderRequest): Promise<FolderSuggestion> {
    try {
        const response = await fetchAPI<FolderSuggestion>('/v1/suggest_folder', {
            method: 'POST',
            body: JSON.stringify(request),
        });
        return response;
    } catch (e) {
        console.debug('[Backboard] suggestFolder failed:', e);
        return {
            action: 'no_suggestion',
            folder_id: null,
            folder_name: null,
            similarity_score: 0,
            similar_unfiled: [],
            alternate_folder: null,
        };
    }
}

/**
 * Delete folder definition from Backboard memory.
 * Called when folder is deleted to prevent stale suggestions.
 */
export async function deleteFolder(userId: string, folderId: string): Promise<void> {
    try {
        await fetchAPI<{ status: string }>('/v1/delete_folder', {
            method: 'POST',
            body: JSON.stringify({
                user_id: userId,
                folder_id: folderId,
            }),
        });
        console.debug('[Backboard] Folder deleted from memory:', folderId);
    } catch (e) {
        console.debug('[Backboard] deleteFolder failed:', e);
    }
}

/**
 * Delete problem from Backboard memory.
 * Called when problem is deleted to exclude from similarity searches.
 */
export async function deleteProblem(userId: string, sessionId: string): Promise<void> {
    try {
        await fetchAPI<{ status: string }>('/v1/delete_problem', {
            method: 'POST',
            body: JSON.stringify({
                user_id: userId,
                session_id: sessionId,
            }),
        });
        console.debug('[Backboard] Problem deleted from memory:', sessionId);
    } catch (e) {
        console.debug('[Backboard] deleteProblem failed:', e);
    }
}

// ============================================================================
// GOOGLE DOCS CHEAT SHEET GENERATION
// ============================================================================

interface CheatSheetProblem {
    problem: string;
    topic: string;
    final_answer: string;
}

interface GenerateCheatSheetRequest {
    user_id: string;
    folder_name: string;
    problems: CheatSheetProblem[];
    google_access_token: string;
}

export interface GenerateCheatSheetResponse {
    doc_url: string;
    doc_title: string;
}

/**
 * Generate a cheat sheet from folder problems and write it to Google Docs.
 *
 * 1. Gets a Google Docs access token via chrome.identity
 * 2. Sends folder data + token to backend
 * 3. Backend generates content via LLM and writes to Google Docs
 * 4. Returns the created Google Doc URL
 */
export async function generateCheatSheet(
    userId: string,
    folderName: string,
    problems: CheatSheetProblem[],
    googleAccessToken: string,
): Promise<GenerateCheatSheetResponse> {
    const request: GenerateCheatSheetRequest = {
        user_id: userId,
        folder_name: folderName,
        problems,
        google_access_token: googleAccessToken,
    };

    return fetchAPI<GenerateCheatSheetResponse>('/v1/generate_cheatsheet', {
        method: 'POST',
        body: JSON.stringify(request),
    });
}

