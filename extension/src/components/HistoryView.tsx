import { useState } from 'react';
import { Card, CardContent } from './ui/card';
import { Button } from './ui/button';
import { ChevronDown, ChevronUp, Trash2, Clock, BookOpen, Trophy } from 'lucide-react';
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
    const [expandedId, setExpandedId] = useState<string | null>(null);

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
        <div className="space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between pb-2 border-b border-slate-700">
                <div>
                    <h2 className="font-semibold text-base text-blue-400">History</h2>
                    <p className="text-xs text-slate-400">{sessions.length} solved problem{sessions.length !== 1 ? 's' : ''}</p>
                </div>
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={onClearAll}
                    className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
                >
                    <Trash2 className="h-4 w-4 mr-1" />
                    Clear All
                </Button>
            </div>

            {/* Session List */}
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                {sessions.map((session) => {
                    const isExpanded = expandedId === session.id;
                    const topicShort = session.topic.split(' - ').pop() || session.topic;

                    return (
                        <Card
                            key={session.id}
                            className={`transition-all cursor-pointer ${isExpanded ? 'border-blue-500/50' : 'border-slate-700 hover:border-slate-600'
                                }`}
                        >
                            <CardContent className="p-3">
                                {/* Header row */}
                                <div
                                    className="flex items-start gap-3"
                                    onClick={() => setExpandedId(isExpanded ? null : session.id)}
                                >
                                    {/* Topic badge */}
                                    <div className="flex-shrink-0 px-2 py-1 bg-blue-500/20 rounded text-xs font-medium text-blue-400">
                                        {truncate(topicShort, 20)}
                                    </div>

                                    {/* Problem preview */}
                                    <div className="flex-1 min-w-0">
                                        <p className="text-sm text-slate-300 truncate">
                                            {truncate(session.problem, 50)}
                                        </p>
                                        <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                                            <span className="flex items-center gap-1">
                                                <Clock className="h-3 w-3" />
                                                {formatDate(session.timestamp)}
                                            </span>
                                            {session.practiceScore && (
                                                <span className="flex items-center gap-1 text-emerald-400">
                                                    <Trophy className="h-3 w-3" />
                                                    {session.practiceScore.correct}/{session.practiceScore.total}
                                                </span>
                                            )}
                                        </div>
                                    </div>

                                    {/* Expand icon */}
                                    <div className="flex-shrink-0 text-slate-400">
                                        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                                    </div>
                                </div>

                                {/* Expanded content */}
                                {isExpanded && (
                                    <div className="mt-3 pt-3 border-t border-slate-700 space-y-3">
                                        {/* Problem */}
                                        <div>
                                            <p className="text-xs text-slate-500 mb-1">Problem</p>
                                            <p className="text-sm text-slate-300">{session.problem}</p>
                                        </div>

                                        {/* Answer */}
                                        {session.finalAnswer && (
                                            <div>
                                                <p className="text-xs text-slate-500 mb-1">Answer</p>
                                                <p className="text-sm text-emerald-400 font-medium">{session.finalAnswer}</p>
                                            </div>
                                        )}

                                        {/* Steps count */}
                                        <div className="text-xs text-slate-500">
                                            {session.solutionSteps.length} solution step{session.solutionSteps.length !== 1 ? 's' : ''}
                                            {session.practiceQuiz && ` • ${session.practiceQuiz.length} practice questions`}
                                        </div>

                                        {/* Actions */}
                                        <div className="flex gap-2">
                                            <Button
                                                size="sm"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onSelectSession(session);
                                                }}
                                                className="flex-1"
                                            >
                                                View Solution
                                            </Button>
                                            {session.practiceQuiz && (
                                                <div className="flex items-center gap-1 text-xs text-emerald-400 px-2">
                                                    <Trophy className="h-3 w-3" />
                                                    <span>{session.practiceQuiz.length} Q's</span>
                                                </div>
                                            )}
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onDelete(session.id);
                                                }}
                                                className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
                                            >
                                                <Trash2 className="h-4 w-4" />
                                            </Button>
                                        </div>
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    );
                })}
            </div>
        </div>
    );
}
