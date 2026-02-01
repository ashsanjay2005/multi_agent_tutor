/**
 * Chrome Storage utility for persisting session history
 */

import type { SolutionStep, PracticeQuestion, SubStep, VideoResource } from './types';

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
    folderId?: string | null;  // null or undefined = unfiled
    reviewed?: boolean;  // For progress tracking
    youtubeVideos?: VideoResource[];  // Cached YouTube videos for this problem
}

export type FolderColor = 'purple' | 'red' | 'green' | 'blue' | 'amber';

export interface Folder {
    id: string;
    name: string;
    createdAt: number;
    color: FolderColor;
}

const STORAGE_KEY = 'ai_tutor_history';
const FOLDERS_KEY = 'ai_tutor_folders';
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
    updates: Partial<Pick<HistorySession, 'practiceQuiz' | 'practiceScore' | 'expandedSubSteps' | 'youtubeVideos'>>
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

// ============ FOLDER FUNCTIONS ============

/**
 * Generate a unique folder ID
 */
function generateFolderId(): string {
    return `folder-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Get all folders
 */
export async function getFolders(): Promise<Folder[]> {
    try {
        const result = await chrome.storage.local.get(FOLDERS_KEY);
        return result[FOLDERS_KEY] || [];
    } catch (error) {
        console.error('Failed to load folders:', error);
        return [];
    }
}

/**
 * Create a new folder
 */
export async function createFolder(name: string, color: FolderColor = 'purple'): Promise<Folder> {
    const newFolder: Folder = {
        id: generateFolderId(),
        name: name.trim(),
        createdAt: Date.now(),
        color,
    };

    const folders = await getFolders();
    folders.push(newFolder);
    await chrome.storage.local.set({ [FOLDERS_KEY]: folders });

    return newFolder;
}

/**
 * Delete a folder (items are unfiled, NOT deleted)
 */
export async function deleteFolder(folderId: string): Promise<void> {
    // First, unfile all items in this folder
    const history = await getHistory();
    const updatedHistory = history.map(session =>
        session.folderId === folderId
            ? { ...session, folderId: null }
            : session
    );
    await chrome.storage.local.set({ [STORAGE_KEY]: updatedHistory });

    // Then remove the folder
    const folders = await getFolders();
    const filtered = folders.filter(f => f.id !== folderId);
    await chrome.storage.local.set({ [FOLDERS_KEY]: filtered });
}

/**
 * Rename a folder
 */
export async function renameFolder(folderId: string, newName: string): Promise<void> {
    const folders = await getFolders();
    const index = folders.findIndex(f => f.id === folderId);
    if (index !== -1) {
        folders[index].name = newName.trim();
        await chrome.storage.local.set({ [FOLDERS_KEY]: folders });
    }
}

/**
 * Move a session to a folder (or unfile by passing null)
 */
export async function moveToFolder(sessionId: string, folderId: string | null): Promise<void> {
    const history = await getHistory();
    const index = history.findIndex(s => s.id === sessionId);
    if (index !== -1) {
        history[index].folderId = folderId;
        await chrome.storage.local.set({ [STORAGE_KEY]: history });
    }
}

/**
 * Clear all folders (items are unfiled, NOT deleted)
 */
export async function clearFolders(): Promise<void> {
    // Unfile all items
    const history = await getHistory();
    const updatedHistory = history.map(session => ({ ...session, folderId: null }));
    await chrome.storage.local.set({ [STORAGE_KEY]: updatedHistory });

    // Remove all folders
    await chrome.storage.local.remove(FOLDERS_KEY);
}

// ============ BATCH OPERATIONS ============

/**
 * Move multiple sessions to a folder (or unfile by passing null)
 */
export async function batchMoveToFolder(sessionIds: string[], folderId: string | null): Promise<void> {
    const history = await getHistory();
    const idsSet = new Set(sessionIds);
    const updatedHistory = history.map(session =>
        idsSet.has(session.id) ? { ...session, folderId } : session
    );
    await chrome.storage.local.set({ [STORAGE_KEY]: updatedHistory });
}

/**
 * Mark multiple sessions as reviewed/unreviewed
 */
export async function batchMarkReviewed(sessionIds: string[], reviewed: boolean): Promise<void> {
    const history = await getHistory();
    const idsSet = new Set(sessionIds);
    const updatedHistory = history.map(session =>
        idsSet.has(session.id) ? { ...session, reviewed } : session
    );
    await chrome.storage.local.set({ [STORAGE_KEY]: updatedHistory });
}

/**
 * Delete multiple sessions at once
 */
export async function batchDeleteSessions(sessionIds: string[]): Promise<void> {
    const history = await getHistory();
    const idsSet = new Set(sessionIds);
    const filtered = history.filter(s => !idsSet.has(s.id));
    await chrome.storage.local.set({ [STORAGE_KEY]: filtered });
}

/**
 * Update a folder's color
 */
export async function updateFolderColor(folderId: string, color: FolderColor): Promise<void> {
    const folders = await getFolders();
    const index = folders.findIndex(f => f.id === folderId);
    if (index !== -1) {
        folders[index].color = color;
        await chrome.storage.local.set({ [FOLDERS_KEY]: folders });
    }
}
