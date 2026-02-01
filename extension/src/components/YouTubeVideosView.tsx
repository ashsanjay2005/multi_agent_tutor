import { ExternalLink, Play, ArrowLeft, Loader2 } from 'lucide-react';
import { Button } from './ui/button';
import type { VideoResource } from '../lib/types';

interface YouTubeVideosViewProps {
    videos: VideoResource[];
    loading: boolean;
    hasMore: boolean;
    loadingMore: boolean;
    onLoadMore: () => void;
    onBack: () => void;
    topic?: string;
}

/**
 * Loading skeleton for video cards
 */
function VideoSkeleton() {
    return (
        <div className="flex gap-3 p-3 bg-slate-800/50 rounded-lg animate-pulse">
            {/* Thumbnail skeleton */}
            <div className="w-32 h-20 bg-slate-700 rounded-md flex-shrink-0" />
            {/* Content skeleton */}
            <div className="flex-1 space-y-2">
                <div className="h-4 bg-slate-700 rounded w-3/4" />
                <div className="h-3 bg-slate-700/60 rounded w-full" />
                <div className="h-3 bg-slate-700/60 rounded w-5/6" />
            </div>
        </div>
    );
}

/**
 * Single video card component
 */
function VideoCard({ video }: { video: VideoResource }) {
    const handleClick = () => {
        window.open(video.youtube_url, '_blank', 'noopener,noreferrer');
    };

    return (
        <button
            onClick={handleClick}
            className="w-full flex gap-3 p-3 bg-slate-800/50 hover:bg-slate-800/80 rounded-lg transition-all group text-left border border-transparent hover:border-red-500/30"
        >
            {/* Thumbnail with play overlay */}
            <div className="relative w-32 h-20 bg-slate-900 rounded-md flex-shrink-0 overflow-hidden">
                <img
                    src={video.thumbnail_url}
                    alt={video.title}
                    className="w-full h-full object-cover"
                    onError={(e) => {
                        // Fallback to placeholder on error
                        (e.target as HTMLImageElement).src = 'https://img.youtube.com/vi/default/mqdefault.jpg';
                    }}
                />
                {/* Play button overlay */}
                <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity">
                    <div className="h-10 w-10 rounded-full bg-red-600 flex items-center justify-center">
                        <Play className="h-5 w-5 text-white fill-white ml-0.5" />
                    </div>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
                {/* Title */}
                <h4 className="text-sm font-medium text-slate-200 line-clamp-2 group-hover:text-white transition-colors">
                    {video.title}
                </h4>
                {/* Relevance summary */}
                <p className="text-xs text-slate-400 mt-1.5 line-clamp-2 leading-relaxed">
                    {video.relevance_summary}
                </p>
                {/* External link hint */}
                <div className="flex items-center gap-1 mt-2 text-xs text-red-400/70 group-hover:text-red-400 transition-colors">
                    <ExternalLink className="h-3 w-3" />
                    <span>Watch on YouTube</span>
                </div>
            </div>
        </button>
    );
}

export function YouTubeVideosView({
    videos,
    loading,
    hasMore,
    loadingMore,
    onLoadMore,
    onBack,
    topic
}: YouTubeVideosViewProps) {
    // Extract the specific topic name
    const topicParts = topic?.split(' - ') || [];
    const displayTopic = topicParts[topicParts.length - 1] || 'this topic';

    return (
        <div className="space-y-4">
            {/* Header */}
            <div className="flex items-center gap-2">
                <button
                    onClick={onBack}
                    className="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
                >
                    <ArrowLeft className="h-4 w-4" />
                </button>
                <div>
                    <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                        <Play className="h-5 w-5 text-red-500" />
                        YouTube Resources
                    </h2>
                    <p className="text-xs text-slate-400 mt-0.5">
                        Tutorials for {displayTopic}
                    </p>
                </div>
            </div>

            {/* Video List */}
            <div className="space-y-3">
                {/* Loading skeletons */}
                {loading && videos.length === 0 && (
                    <>
                        <VideoSkeleton />
                        <VideoSkeleton />
                        <VideoSkeleton />
                    </>
                )}

                {/* Video cards */}
                {videos.map((video) => (
                    <VideoCard key={video.video_id} video={video} />
                ))}

                {/* Empty state */}
                {!loading && videos.length === 0 && (
                    <div className="text-center py-8 text-slate-400">
                        <Play className="h-12 w-12 mx-auto mb-3 opacity-50" />
                        <p>No videos found for this topic.</p>
                        <p className="text-sm mt-1">Try a different problem or check back later.</p>
                    </div>
                )}
            </div>

            {/* Load More Button */}
            {hasMore && videos.length > 0 && (
                <div className="pt-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={onLoadMore}
                        disabled={loadingMore}
                        className="w-full border-slate-700 hover:border-red-500/50 hover:bg-red-500/10"
                    >
                        {loadingMore ? (
                            <>
                                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                Loading...
                            </>
                        ) : (
                            <>
                                <Play className="h-4 w-4 mr-2" />
                                Show 3 More Videos
                            </>
                        )}
                    </Button>
                </div>
            )}

            {/* Back to Solution Button */}
            <div className="pt-2">
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={onBack}
                    className="w-full text-slate-400 hover:text-white"
                >
                    <ArrowLeft className="h-4 w-4 mr-2" />
                    Back to Solution
                </Button>
            </div>
        </div>
    );
}
