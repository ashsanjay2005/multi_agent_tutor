import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs))
}

export function getUserId(): string {
    const stored = localStorage.getItem('ai_tutor_user_id');
    if (stored) return stored;

    const newId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    localStorage.setItem('ai_tutor_user_id', newId);
    return newId;
}
