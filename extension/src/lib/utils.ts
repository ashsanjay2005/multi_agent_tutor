import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { resolveUserId } from "./auth"

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs))
}

/**
 * Get the current user ID (always a valid UUID).
 * Delegates to auth module's cached state — synchronous.
 */
export function getUserId(): string {
    return resolveUserId();
}
