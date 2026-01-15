import { useState } from 'react';
import { ChevronDown, ChevronRight, Trash2, BookOpen, FolderPlus, Folder, FolderOpen, X, Plus, Check, CheckSquare, Square } from 'lucide-react';
import type { HistorySession, Folder as FolderType, FolderColor } from '../lib/storage';

// Color mappings
const FOLDER_COLORS: Record<FolderColor, { bg: string; border: string; text: string; accent: string }> = {
    purple: { bg: 'bg-purple-600/20', border: 'border-purple-500', text: 'text-purple-400', accent: '#6D28D9' },
    red: { bg: 'bg-red-600/20', border: 'border-red-500', text: 'text-red-400', accent: '#DC2626' },
    green: { bg: 'bg-green-600/20', border: 'border-green-500', text: 'text-green-400', accent: '#16A34A' },
    blue: { bg: 'bg-blue-600/20', border: 'border-blue-500', text: 'text-blue-400', accent: '#2563EB' },
    amber: { bg: 'bg-amber-600/20', border: 'border-amber-500', text: 'text-amber-400', accent: '#D97706' },
};

interface HistoryViewProps {
    sessions: HistorySession[];
    folders: FolderType[];
    onDelete: (sessionId: string) => void;
    onClearAll: () => void;
    onSelectSession: (session: HistorySession) => void;
    onCreateFolder: (name: string, color: FolderColor) => void;
    onDeleteFolder: (folderId: string) => void;
    onMoveToFolder: (sessionId: string, folderId: string | null) => void;
    onBatchMove: (sessionIds: string[], folderId: string | null) => void;
    onBatchMarkReviewed: (sessionIds: string[], reviewed: boolean) => void;
    onBatchDelete: (sessionIds: string[]) => void;
}

function formatDate(timestamp: number): string {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();

    if (diff < 3600000) {
        const mins = Math.floor(diff / 60000);
        return mins <= 1 ? 'Just now' : `${mins} min ago`;
    }
    if (diff < 86400000) {
        const hours = Math.floor(diff / 3600000);
        return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    }
    if (diff < 604800000) {
        const days = Math.floor(diff / 86400000);
        return `${days} day${days > 1 ? 's' : ''} ago`;
    }
    return date.toLocaleDateString();
}

function truncate(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength).trim() + '...';
}

// Get primary topic from items in a folder
function getPrimaryTopic(items: HistorySession[]): string {
    if (items.length === 0) return '';
    const topicCounts = items.reduce((acc, item) => {
        const topic = item.topic.split(' - ').pop() || item.topic;
        acc[topic] = (acc[topic] || 0) + 1;
        return acc;
    }, {} as Record<string, number>);
    const sorted = Object.entries(topicCounts).sort((a, b) => b[1] - a[1]);
    return sorted[0]?.[0] ? `Mostly ${truncate(sorted[0][0], 12)}` : '';
}

// History Card Component
function HistoryCard({
    session,
    isSelected,
    isChecked,
    selectMode,
    onSelect,
    onCheck,
    onViewSolution,
    onDelete,
    onMoveToFolder,
    folders,
    accentColor,
    isDragging,
    onDragStart,
    onDragEnd,
}: {
    session: HistorySession;
    isSelected: boolean;
    isChecked: boolean;
    selectMode: boolean;
    onSelect: () => void;
    onCheck: () => void;
    onViewSolution: () => void;
    onDelete: () => void;
    onMoveToFolder: (folderId: string | null) => void;
    folders: FolderType[];
    accentColor?: string;
    isDragging?: boolean;
    onDragStart?: () => void;
    onDragEnd?: () => void;
}) {
    const [showFolderMenu, setShowFolderMenu] = useState(false);
    const topicShort = session.topic.split(' - ').pop() || session.topic;

    return (
        <div className="relative">
            <div
                draggable={!selectMode}
                onDragStart={(e) => {
                    e.dataTransfer.setData('sessionId', session.id);
                    e.dataTransfer.effectAllowed = 'move';
                    onDragStart?.();
                }}
                onDragEnd={() => onDragEnd?.()}
                onClick={() => selectMode ? onCheck() : onSelect()}
                className={`cursor-pointer rounded-xl p-4 transition-all duration-200 ${isSelected
                    ? 'glow-border'
                    : 'bg-slate-800/40 hover:bg-slate-800/60'
                    } ${isDragging ? 'opacity-60 rotate-2 scale-105' : ''}`}
                style={accentColor ? { borderLeft: `2px solid ${accentColor}` } : undefined}
            >
                {/* Topic Badge + Actions */}
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                        {selectMode && (
                            <button onClick={(e) => { e.stopPropagation(); onCheck(); }} className="text-purple-400">
                                {isChecked ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                            </button>
                        )}
                        <span className={`inline-block px-2 py-0.5 rounded-md text-xs font-medium ${isSelected
                            ? 'topic-badge'
                            : 'bg-slate-700/60 text-slate-400'
                            }`}>
                            {truncate(topicShort, 22)}
                        </span>
                        {session.reviewed && (
                            <Check className="h-3.5 w-3.5 text-green-400" />
                        )}
                    </div>
                    <div className="flex items-center gap-1">
                        {!selectMode && (
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    setShowFolderMenu(!showFolderMenu);
                                }}
                                className="p-1 rounded hover:bg-slate-700/50 text-purple-400 hover:text-purple-300 transition-colors"
                                title="Add to folder"
                            >
                                <FolderPlus className="h-4 w-4" />
                            </button>
                        )}
                        <ChevronDown className={`h-4 w-4 text-slate-500 transition-transform ${isSelected ? 'rotate-180' : ''}`} />
                    </div>
                </div>

                {/* Problem Preview */}
                <p className={`text-sm mb-1 ${isSelected ? 'text-white font-medium' : 'text-slate-300'}`}>
                    {truncate(session.problem, 35)}
                </p>

                {/* Time */}
                <p className="text-xs text-slate-500">
                    {formatDate(session.timestamp)}
                </p>

                {/* Expanded Actions */}
                {isSelected && !selectMode && (
                    <div className="mt-4 flex gap-2">
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onViewSolution();
                            }}
                            className="gradient-button flex-1 py-2 text-sm"
                        >
                            View Solution
                        </button>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onDelete();
                            }}
                            className="px-3 py-2 rounded-lg border border-slate-600 text-slate-400 hover:text-red-400 hover:border-red-500/50 transition-colors"
                        >
                            <Trash2 className="h-4 w-4" />
                        </button>
                    </div>
                )}
            </div>

            {/* Folder Selection Dropdown */}
            {showFolderMenu && (
                <div className="absolute right-0 top-8 z-20 bg-slate-800 border border-slate-700 rounded-lg shadow-xl py-1 min-w-[160px]">
                    <div className="px-3 py-2 text-xs text-slate-400 font-medium border-b border-slate-700">
                        Move to folder
                    </div>
                    {session.folderId && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onMoveToFolder(null);
                                setShowFolderMenu(false);
                            }}
                            className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700/50 flex items-center gap-2"
                        >
                            <X className="h-3.5 w-3.5" />
                            Remove from folder
                        </button>
                    )}
                    {folders.length === 0 ? (
                        <div className="px-3 py-2 text-sm text-slate-500 italic">
                            No folders yet
                        </div>
                    ) : (
                        folders.map(folder => (
                            <button
                                key={folder.id}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onMoveToFolder(folder.id);
                                    setShowFolderMenu(false);
                                }}
                                className={`w-full text-left px-3 py-2 text-sm hover:bg-slate-700/50 flex items-center gap-2 ${session.folderId === folder.id ? FOLDER_COLORS[folder.color].text : 'text-slate-300'
                                    }`}
                            >
                                <Folder className="h-3.5 w-3.5" style={{ color: FOLDER_COLORS[folder.color].accent }} />
                                {truncate(folder.name, 18)}
                            </button>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}

// Folder Accordion Component
function FolderAccordion({
    folder,
    items,
    selectMode,
    selectedIds,
    onToggleSelect,
    onDeleteFolder,
    onSelectSession,
    onDeleteSession,
    onMoveToFolder,
    folders,
    onDropItem,
    draggingItemId: _draggingItemId,
}: {
    folder: FolderType;
    items: HistorySession[];
    selectMode: boolean;
    selectedIds: Set<string>;
    onToggleSelect: (id: string) => void;
    onDeleteFolder: () => void;
    onSelectSession: (session: HistorySession) => void;
    onDeleteSession: (sessionId: string) => void;
    onMoveToFolder: (sessionId: string, folderId: string | null) => void;
    folders: FolderType[];
    onDropItem: (sessionId: string, folderId: string) => void;
    draggingItemId: string | null;
}) {
    const [isExpanded, setIsExpanded] = useState(false);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [isDragOver, setIsDragOver] = useState(false);

    const colorStyle = FOLDER_COLORS[folder.color] || FOLDER_COLORS.purple;
    const primaryTopic = getPrimaryTopic(items);
    const reviewedCount = items.filter(i => i.reviewed).length;
    const progress = items.length > 0 ? (reviewedCount / items.length) * 100 : 0;

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (!isDragOver) setIsDragOver(true);
    };

    const handleDragLeave = () => {
        setIsDragOver(false);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        const sessionId = e.dataTransfer.getData('sessionId');
        if (sessionId) {
            onDropItem(sessionId, folder.id);
        }
        setIsDragOver(false);
    };

    return (
        <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={`rounded-xl overflow-hidden border transition-all duration-200 ${isDragOver
                ? `${colorStyle.border} shadow-lg shadow-purple-500/30 scale-[1.02]`
                : `${colorStyle.border} bg-slate-800/30`
                }`}
        >
            {/* Folder Header */}
            <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-full flex items-center justify-between p-3 hover:bg-slate-800/50 transition-colors"
            >
                <div className="flex items-center gap-2">
                    {isExpanded ? (
                        <FolderOpen className="h-4 w-4" style={{ color: colorStyle.accent }} />
                    ) : (
                        <Folder className="h-4 w-4" style={{ color: colorStyle.accent }} />
                    )}
                    <span className="font-medium text-slate-200">{folder.name}</span>
                    <span className="text-xs text-slate-500">({items.length})</span>
                    {primaryTopic && (
                        <span className={`text-xs px-2 py-0.5 rounded ${colorStyle.bg} ${colorStyle.text}`}>
                            {primaryTopic}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-500">{Math.round(progress)}% Reviewed</span>
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            if (confirm(`Delete folder "${folder.name}"? Items will be moved to General History.`)) {
                                onDeleteFolder();
                            }
                        }}
                        className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-red-400 transition-colors"
                    >
                        <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    {isExpanded ? (
                        <ChevronDown className="h-4 w-4 text-slate-500" />
                    ) : (
                        <ChevronRight className="h-4 w-4 text-slate-500" />
                    )}
                </div>
            </button>

            {/* Progress Bar */}
            <div className="h-0.5 bg-slate-700">
                <div
                    className="h-full transition-all duration-300"
                    style={{ width: `${progress}%`, backgroundColor: colorStyle.accent }}
                />
            </div>

            {/* Folder Contents */}
            {isExpanded && (
                <div className="p-2 pt-2 space-y-2">
                    {items.map(session => (
                        <HistoryCard
                            key={session.id}
                            session={session}
                            isSelected={selectedId === session.id}
                            isChecked={selectedIds.has(session.id)}
                            selectMode={selectMode}
                            onSelect={() => setSelectedId(selectedId === session.id ? null : session.id)}
                            onCheck={() => onToggleSelect(session.id)}
                            onViewSolution={() => onSelectSession(session)}
                            onDelete={() => onDeleteSession(session.id)}
                            onMoveToFolder={(folderId) => onMoveToFolder(session.id, folderId)}
                            folders={folders}
                            accentColor={colorStyle.accent}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}

// Color Picker Component
function ColorPicker({ selected, onChange }: { selected: FolderColor; onChange: (c: FolderColor) => void }) {
    const colors: FolderColor[] = ['purple', 'red', 'green', 'blue', 'amber'];
    return (
        <div className="flex gap-2">
            {colors.map(c => (
                <button
                    key={c}
                    onClick={() => onChange(c)}
                    className={`w-6 h-6 rounded-full border-2 transition-all ${selected === c ? 'scale-110 border-white' : 'border-transparent'
                        }`}
                    style={{ backgroundColor: FOLDER_COLORS[c].accent }}
                />
            ))}
        </div>
    );
}

export function HistoryView({
    sessions,
    folders,
    onDelete,
    onClearAll,
    onSelectSession,
    onCreateFolder,
    onDeleteFolder,
    onMoveToFolder,
    onBatchMove,
    onBatchMarkReviewed,
    onBatchDelete,
}: HistoryViewProps) {
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [showNewFolder, setShowNewFolder] = useState(false);
    const [newFolderName, setNewFolderName] = useState('');
    const [newFolderColor, setNewFolderColor] = useState<FolderColor>('purple');
    const [selectMode, setSelectMode] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [showBatchFolderMenu, setShowBatchFolderMenu] = useState(false);
    const [showClearConfirm, setShowClearConfirm] = useState(false);

    // Split sessions into folders and unfiled
    const folderGroups = folders.map(folder => ({
        folder,
        items: sessions.filter(s => s.folderId === folder.id)
    })).filter(g => g.items.length > 0);

    const unfiledItems = sessions.filter(s => !s.folderId);

    const handleCreateFolder = () => {
        if (newFolderName.trim()) {
            onCreateFolder(newFolderName.trim(), newFolderColor);
            setNewFolderName('');
            setNewFolderColor('purple');
            setShowNewFolder(false);
        }
    };

    const toggleSelect = (id: string) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const clearSelection = () => {
        setSelectedIds(new Set());
        setSelectMode(false);
    };

    const [draggingItemId, setDraggingItemId] = useState<string | null>(null);

    const handleDropToFolder = (sessionId: string, folderId: string) => {
        onMoveToFolder(sessionId, folderId);
        setDraggingItemId(null);
    };

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
        <div className="space-y-4 pb-20">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h2 className="font-bold text-xl text-white">History</h2>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => {
                            if (selectMode) clearSelection();
                            else setSelectMode(true);
                        }}
                        className={`px-3 py-1.5 rounded-full border text-xs transition-colors ${selectMode
                            ? 'border-purple-500 text-purple-400 bg-purple-500/10'
                            : 'border-slate-600 text-slate-400 hover:text-white'
                            }`}
                    >
                        {selectMode ? 'Cancel' : 'Select'}
                    </button>
                    <button
                        onClick={() => setShowNewFolder(true)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-slate-600 text-slate-400 hover:text-purple-400 hover:border-purple-500/50 text-xs transition-colors"
                    >
                        New Folder
                        <Plus className="h-3.5 w-3.5" />
                    </button>
                    <button
                        onClick={() => setShowClearConfirm(true)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-slate-600 text-slate-400 hover:text-red-400 hover:border-red-500/50 text-xs transition-colors"
                    >
                        Clear All
                        <Trash2 className="h-3.5 w-3.5" />
                    </button>
                </div>
            </div>

            {/* New Folder Input */}
            {showNewFolder && (
                <div className="space-y-3 p-4 bg-slate-800/50 rounded-xl border border-slate-700">
                    <input
                        type="text"
                        value={newFolderName}
                        onChange={(e) => setNewFolderName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()}
                        placeholder="Folder name..."
                        className="w-full px-3 py-2 bg-slate-900/50 border border-slate-600 rounded-lg text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-purple-500"
                        autoFocus
                    />
                    <div className="flex items-center justify-between">
                        <ColorPicker selected={newFolderColor} onChange={setNewFolderColor} />
                        <div className="flex gap-2">
                            <button
                                onClick={() => {
                                    setShowNewFolder(false);
                                    setNewFolderName('');
                                }}
                                className="px-3 py-1.5 border border-slate-600 rounded-lg text-slate-400 hover:text-white transition-colors text-sm"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleCreateFolder}
                                className="px-4 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm text-white transition-colors"
                            >
                                Create
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Folder Groups */}
            {folderGroups.length > 0 && (
                <div className="space-y-2">
                    {folderGroups.map(({ folder, items }) => (
                        <FolderAccordion
                            key={folder.id}
                            folder={folder}
                            items={items}
                            selectMode={selectMode}
                            selectedIds={selectedIds}
                            onToggleSelect={toggleSelect}
                            onDeleteFolder={() => onDeleteFolder(folder.id)}
                            onSelectSession={onSelectSession}
                            onDeleteSession={onDelete}
                            onMoveToFolder={onMoveToFolder}
                            folders={folders}
                            onDropItem={handleDropToFolder}
                            draggingItemId={draggingItemId}
                        />
                    ))}
                </div>
            )}

            {/* Unfiled Items */}
            {unfiledItems.length > 0 && (
                <div className="space-y-3">
                    {folderGroups.length > 0 && (
                        <div className="text-xs text-slate-500 font-medium px-1">
                            General History
                        </div>
                    )}
                    <div className="space-y-3 overflow-y-auto pr-1" style={{ maxHeight: 'calc(100vh - 320px)' }}>
                        {unfiledItems.map((session) => (
                            <HistoryCard
                                key={session.id}
                                session={session}
                                isSelected={selectedId === session.id}
                                isChecked={selectedIds.has(session.id)}
                                selectMode={selectMode}
                                onSelect={() => setSelectedId(selectedId === session.id ? null : session.id)}
                                onCheck={() => toggleSelect(session.id)}
                                onViewSolution={() => onSelectSession(session)}
                                onDelete={() => onDelete(session.id)}
                                onMoveToFolder={(folderId) => onMoveToFolder(session.id, folderId)}
                                folders={folders}
                                isDragging={draggingItemId === session.id}
                                onDragStart={() => setDraggingItemId(session.id)}
                                onDragEnd={() => setDraggingItemId(null)}
                            />
                        ))}
                    </div>
                </div>
            )}

            {/* Bulk Action Bar */}
            {selectMode && selectedIds.size > 0 && (
                <div className="fixed bottom-4 left-4 right-4 bg-slate-800 border border-purple-500/50 rounded-xl p-4 shadow-xl z-30">
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-300">
                            <span className="font-medium text-white">{selectedIds.size}</span> item{selectedIds.size > 1 ? 's' : ''} selected
                        </span>
                        <div className="flex items-center gap-2">
                            <div className="relative">
                                <button
                                    onClick={() => setShowBatchFolderMenu(!showBatchFolderMenu)}
                                    className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-white transition-colors"
                                >
                                    Move to Folder
                                </button>
                                {showBatchFolderMenu && (
                                    <div className="absolute bottom-full mb-2 right-0 bg-slate-800 border border-slate-700 rounded-lg shadow-xl py-1 min-w-[160px]">
                                        <button
                                            onClick={() => {
                                                onBatchMove(Array.from(selectedIds), null);
                                                setShowBatchFolderMenu(false);
                                                clearSelection();
                                            }}
                                            className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700/50"
                                        >
                                            Remove from folders
                                        </button>
                                        {folders.map(f => (
                                            <button
                                                key={f.id}
                                                onClick={() => {
                                                    onBatchMove(Array.from(selectedIds), f.id);
                                                    setShowBatchFolderMenu(false);
                                                    clearSelection();
                                                }}
                                                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700/50 flex items-center gap-2"
                                            >
                                                <Folder className="h-3.5 w-3.5" style={{ color: FOLDER_COLORS[f.color].accent }} />
                                                {f.name}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                            <button
                                onClick={() => {
                                    onBatchMarkReviewed(Array.from(selectedIds), true);
                                    clearSelection();
                                }}
                                className="px-3 py-1.5 bg-green-600 hover:bg-green-700 rounded-lg text-sm text-white transition-colors"
                            >
                                Mark Reviewed
                            </button>
                            <button
                                onClick={() => {
                                    if (confirm(`Delete ${selectedIds.size} item(s)?`)) {
                                        onBatchDelete(Array.from(selectedIds));
                                        clearSelection();
                                    }
                                }}
                                className="px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded-lg text-sm text-white transition-colors"
                            >
                                Delete
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Clear All Confirmation Modal */}
            {showClearConfirm && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
                    <div className="bg-slate-800 rounded-xl p-6 max-w-sm w-full border border-slate-700 shadow-xl">
                        <h3 className="text-lg font-semibold text-white mb-2">Clear All History?</h3>
                        <p className="text-sm text-slate-400 mb-6">
                            Are you sure you want to delete your entire history? This action cannot be undone.
                        </p>
                        <div className="flex gap-3 justify-end">
                            <button
                                onClick={() => setShowClearConfirm(false)}
                                className="px-4 py-2 text-slate-400 hover:text-white transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => {
                                    onClearAll();
                                    setShowClearConfirm(false);
                                }}
                                className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-white transition-colors"
                            >
                                Clear All
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
