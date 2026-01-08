/**
 * API Client for communicating with the Python backend
 */

import type {
    AnalyzeRequest,
    AnalyzeResponse,
    ResumeRequest,
    ExplainStepRequest,
    ExplainStepResponse,
    HealthResponse,
    PracticeRequest,
    PracticeResponse,
} from './types';

const API_BASE_URL = 'http://localhost:8000';

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
 * Get explanation for a specific step
 */
export async function explainStep(
    request: ExplainStepRequest
): Promise<ExplainStepResponse> {
    return fetchAPI<ExplainStepResponse>('/v1/explain_step', {
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
