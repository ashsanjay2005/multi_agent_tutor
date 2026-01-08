/**
 * Chrome Storage utility for persisting session history
 */

import type { SolutionStep, PracticeQuestion, SubStep } from './types';

export interface HistorySession {
    id: string;
    timestamp: number;
    problem: string;
    topic: string;
    solutionSteps: SolutionStep[];
    finalAnswer: string;
    practiceQuiz?: PracticeQuestion[];
    practiceScore?: { correct: number; total: number };
    expandedSubSteps?: Record<string, SubStep[]>;  // Persisted sub-step expansions
}

const STORAGE_KEY = 'ai_tutor_history';
const MAX_SESSIONS = 50; // Limit to prevent storage bloat

/**
 * Generate a unique session ID
 */
function generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Save a new session to history
 */
export async function saveSession(session: Omit<HistorySession, 'id' | 'timestamp'>): Promise<HistorySession> {
    const newSession: HistorySession = {
        ...session,
        id: generateId(),
        timestamp: Date.now(),
    };

    const history = await getHistory();

    // Add new session at the beginning
    history.unshift(newSession);

    // Limit to MAX_SESSIONS
    if (history.length > MAX_SESSIONS) {
        history.pop();
    }

    await chrome.storage.local.set({ [STORAGE_KEY]: history });

    return newSession;
}

/**
 * Update an existing session (e.g., to add practice quiz score)
 */
export async function updateSession(
    sessionId: string,
    updates: Partial<Pick<HistorySession, 'practiceQuiz' | 'practiceScore' | 'expandedSubSteps'>>
): Promise<void> {
    const history = await getHistory();
    const index = history.findIndex(s => s.id === sessionId);

    if (index !== -1) {
        history[index] = { ...history[index], ...updates };
        await chrome.storage.local.set({ [STORAGE_KEY]: history });
    }
}

/**
 * Get all sessions from history (most recent first)
 */
export async function getHistory(): Promise<HistorySession[]> {
    try {
        const result = await chrome.storage.local.get(STORAGE_KEY);
        return result[STORAGE_KEY] || [];
    } catch (error) {
        console.error('Failed to load history:', error);
        return [];
    }
}

/**
 * Delete a specific session
 */
export async function deleteSession(sessionId: string): Promise<void> {
    const history = await getHistory();
    const filtered = history.filter(s => s.id !== sessionId);
    await chrome.storage.local.set({ [STORAGE_KEY]: filtered });
}

/**
 * Clear all history
 */
export async function clearHistory(): Promise<void> {
    await chrome.storage.local.remove(STORAGE_KEY);
}

/**
 * Get session count
 */
export async function getSessionCount(): Promise<number> {
    const history = await getHistory();
    return history.length;
}
