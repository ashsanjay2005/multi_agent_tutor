import { useState } from 'react';
import { ChevronDown, Trash2, BookOpen } from 'lucide-react';
import type { HistorySession } from '../lib/storage';

interface HistoryViewProps {
    sessions: HistorySession[];
    onDelete: (sessionId: string) => void;
    onClearAll: () => void;
    onSelectSession: (session: HistorySession) => void;
}

function formatDate(timestamp: number): string {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();

    // Less than 1 hour
    if (diff < 3600000) {
        const mins = Math.floor(diff / 60000);
        return mins <= 1 ? 'Just now' : `${mins} min ago`;
    }

    // Less than 24 hours
    if (diff < 86400000) {
        const hours = Math.floor(diff / 3600000);
        return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    }

    // Less than 7 days
    if (diff < 604800000) {
        const days = Math.floor(diff / 86400000);
        return `${days} day${days > 1 ? 's' : ''} ago`;
    }

    // Otherwise show date
    return date.toLocaleDateString();
}

function truncate(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength).trim() + '...';
}

export function HistoryView({ sessions, onDelete, onClearAll, onSelectSession }: HistoryViewProps) {
    const [selectedId, setSelectedId] = useState<string | null>(null);

    if (sessions.length === 0) {
        return (
            <div className="text-center py-12">
                <BookOpen className="h-12 w-12 text-slate-500 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-slate-300 mb-2">No History Yet</h3>
                <p className="text-sm text-slate-400">
                    Your solved problems will appear here.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h2 className="font-bold text-xl text-white">History</h2>
                <button
                    onClick={onClearAll}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-slate-600 text-slate-400 hover:text-red-400 hover:border-red-500/50 text-xs transition-colors"
                >
                    Clear All
                    <Trash2 className="h-3.5 w-3.5" />
                </button>
            </div>

            {/* Timeline Container */}
            <div className="timeline-container">
                {/* Vertical Timeline Line */}
                <div className="timeline-line"></div>

                <div className="space-y-3 overflow-y-auto pr-1" style={{ maxHeight: 'calc(100vh - 180px)' }}>
                    {sessions.map((session) => {
                        const isSelected = selectedId === session.id;
                        const topicShort = session.topic.split(' - ').pop() || session.topic;

                        return (
                            <div key={session.id}>
                                {/* Card */}
                                <div
                                    onClick={() => setSelectedId(isSelected ? null : session.id)}
                                    className={`cursor-pointer rounded-xl p-4 transition-all ${isSelected
                                        ? 'glow-border'
                                        : 'bg-slate-800/40 hover:bg-slate-800/60'
                                        }`}
                                >
                                    {/* Topic Badge */}
                                    <div className="flex items-center justify-between mb-2">
                                        <span className={`inline-block px-2 py-0.5 rounded-md text-xs font-medium ${isSelected
                                            ? 'topic-badge'
                                            : 'bg-slate-700/60 text-slate-400'
                                            }`}>
                                            {truncate(topicShort, 22)}
                                        </span>
                                        <ChevronDown className={`h-4 w-4 text-slate-500 transition-transform ${isSelected ? 'rotate-180' : ''}`} />
                                    </div>

                                    {/* Problem Preview */}
                                    <p className={`text-sm mb-1 ${isSelected ? 'text-white font-medium' : 'text-slate-300'}`}>
                                        {truncate(session.problem, 35)}
                                    </p>

                                    {/* Time */}
                                    <p className="text-xs text-slate-500">
                                        {formatDate(session.timestamp)}
                                    </p>

                                    {/* Expanded: View Solution Button */}
                                    {isSelected && (
                                        <div className="mt-4 flex gap-2">
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onSelectSession(session);
                                                }}
                                                className="gradient-button flex-1 py-2 text-sm"
                                            >
                                                View Solution
                                            </button>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onDelete(session.id);
                                                }}
                                                className="px-3 py-2 rounded-lg border border-slate-600 text-slate-400 hover:text-red-400 hover:border-red-500/50 transition-colors"
                                            >
                                                <Trash2 className="h-4 w-4" />
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div >
    );
}
