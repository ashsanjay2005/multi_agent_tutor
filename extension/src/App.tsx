import { useState, useRef, useEffect } from 'react';
// Tabs replaced with custom underlined tabs
import { Button } from './components/ui/button';
import { Textarea } from './components/ui/textarea';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from './components/ui/alert';
// Card components only used in specific views now
import { LoadingView } from './components/LoadingView';
import { DisambiguationView } from './components/DisambiguationView';
import { SolutionView } from './components/SolutionView';
import { PracticeView } from './components/PracticeView';
import { HistoryView } from './components/HistoryView';
import { YouTubeVideosView } from './components/YouTubeVideosView';
import { Upload, X, Sparkles, Pin, LogIn, LogOut, Cloud, HardDrive } from 'lucide-react';
import { initAuth, onAuthChange, signInInteractive, signOut as authSignOut, type AuthState } from './lib/auth';
import { analyzeProblem, resumeWorkflow, generatePractice, getYouTubeResources, APIError, RateLimitError, deleteProblem as deleteProblemMemory, deleteFolder as deleteFolderMemory } from './lib/api';
import { getUserId } from './lib/utils';
import { saveSession, getHistory, deleteSession, clearHistory, updateSession, getFolders, createFolder, deleteFolder as deleteFolderStorage, moveToFolder, batchMoveToFolder, batchMarkReviewed, batchDeleteSessions, type HistorySession, type Folder } from './lib/storage';
import type { AnalyzeResponse, InputType, PracticeQuestion, SolutionStep, SubStep, VideoResource } from './lib/types';

type AppState = 'idle' | 'loading' | 'disambiguation' | 'solution' | 'practice' | 'history' | 'videos' | 'error';

function App() {
  const [activeTab, setActiveTab] = useState<'paste' | 'screenshot' | 'history'>('paste');
  const [state, setState] = useState<AppState>('idle');
  const [textInput, setTextInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AnalyzeResponse | null>(null);
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [originalProblem, setOriginalProblem] = useState<string>('');
  const [practiceQuestions, setPracticeQuestions] = useState<PracticeQuestion[]>([]);
  const [practiceLoading, setPracticeLoading] = useState(false);
  const [historySessions, setHistorySessions] = useState<HistorySession[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [currentSubSteps, setCurrentSubSteps] = useState<Record<string, SubStep[]>>({});
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  // YouTube videos state
  const [youtubeVideos, setYoutubeVideos] = useState<VideoResource[]>([]);
  const [videosLoading, setVideosLoading] = useState(false);
  const [videosLoadingMore, setVideosLoadingMore] = useState(false);
  const [videosOffset, setVideosOffset] = useState(0);
  const [videosHasMore, setVideosHasMore] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Auth state
  const [authState, setAuthState] = useState<AuthState>({ mode: 'initializing', userId: '' });
  const [showAccountMenu, setShowAccountMenu] = useState(false);

  // Initialize auth + load history on mount
  useEffect(() => {
    initAuth().then(setAuthState);
    const unsub = onAuthChange(setAuthState);
    getHistory().then(setHistorySessions);
    getFolders().then(setFolders);
    return unsub;
  }, []);

  // Close account menu when clicking outside
  useEffect(() => {
    if (!showAccountMenu) return;
    const handler = () => setShowAccountMenu(false);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [showAccountMenu]);

  const handleAnalyze = async (type: InputType, content: string) => {
    if (!content.trim()) {
      setError('Please enter a math problem or capture a screenshot');
      return;
    }
    if (!authState.accessToken) {
      setError('Authentication is still initializing. Please try again in a moment.');
      return;
    }

    setState('loading');
    setError(null);

    try {
      const userId = getUserId();
      setOriginalProblem(content); // Store for practice generation
      const result = await analyzeProblem({
        type,
        content,
        user_id: userId,
      });

      setResponse(result);

      // Determine next state based on response
      if (result.status === 'requires_disambiguation') {
        setState('disambiguation');
      } else if (result.status === 'completed') {
        setState('solution');

        // Save to history - use extracted_problem for images (not base64)
        if (result.solution_steps && result.topic) {
          const problemText = result.extracted_problem || content;
          const saved = await saveSession({
            problem: problemText,
            topic: result.topic,
            solutionSteps: result.solution_steps as SolutionStep[],
            finalAnswer: result.final_answer || '',
          });
          setCurrentSessionId(saved.id);
          setOriginalProblem(problemText);
          setHistorySessions(await getHistory());
        }
      } else if (result.status === 'requires_clarification') {
        setState('error');
        // Show specific message for images with no STEM problem detected
        const isImageProblem = result.extracted_problem === 'No STEM problem found in the image.';
        setError(
          isImageProblem
            ? 'No STEM problem was found in this image. Please upload a photo of a math, science, or engineering problem.'
            : 'Could not understand the problem. Please provide more details.'
        );
      } else {
        setState('error');
        setError('An unexpected error occurred.');
      }
    } catch (err) {
      setState('error');
      if (err instanceof RateLimitError) {
        setError(`Rate limit exceeded. Try again in ${err.retryAfter} seconds. (${err.remaining}/${err.limit} remaining)`);
      } else if (err instanceof APIError) {
        setError(err.message);
      } else {
        setError('Failed to connect to the backend. Make sure the server is running.');
      }
      console.error('Analysis error:', err);
    }
  };

  const handleTextSubmit = () => {
    handleAnalyze('text', textInput);
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      setError('Please select an image file (PNG, JPG, etc.)');
      return;
    }

    // Validate file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      setError('Image too large. Please use an image under 10MB.');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const base64 = e.target?.result as string;
      // Remove data URL prefix for API (keep full for preview)
      setImagePreview(base64);
      setUploadedImage(base64.split(',')[1]); // Just the base64 part
      setError(null);
    };
    reader.onerror = () => {
      setError('Failed to read image file.');
    };
    reader.readAsDataURL(file);
  };

  // Handle drag and drop
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const file = e.dataTransfer.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      setError('Please select an image file (PNG, JPG, etc.)');
      return;
    }

    // Validate file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      setError('Image too large. Please use an image under 10MB.');
      return;
    }

    const reader = new FileReader();
    reader.onload = (evt) => {
      const base64 = evt.target?.result as string;
      setImagePreview(base64);
      setUploadedImage(base64.split(',')[1]);
      setError(null);
    };
    reader.onerror = () => {
      setError('Failed to read image file.');
    };
    reader.readAsDataURL(file);
  };

  const handleImageSubmit = async () => {
    if (!uploadedImage) {
      setError('Please upload an image first.');
      return;
    }
    await handleAnalyze('image', uploadedImage);
  };

  const clearImage = () => {
    setUploadedImage(null);
    setImagePreview(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleTopicSelection = async (selectedTopic: string) => {
    if (!response?.thread_id) return;

    setState('loading');
    setError(null);

    try {
      const result = await resumeWorkflow({
        thread_id: response.thread_id,
        selected_topic: selectedTopic,
      });

      setResponse(result);
      setState('solution');

      if (result.solution_steps && result.topic) {
        const problemText = result.extracted_problem || originalProblem || selectedTopic;
        const saved = await saveSession({
          problem: problemText,
          topic: result.topic,
          solutionSteps: result.solution_steps as SolutionStep[],
          finalAnswer: result.final_answer || '',
        });
        setCurrentSessionId(saved.id);
        setOriginalProblem(problemText);
        setHistorySessions(await getHistory());
      }
    } catch (err) {
      setState('error');
      if (err instanceof APIError) {
        setError(err.message);
      } else {
        setError('Failed to resume workflow.');
      }
      console.error('Resume error:', err);
    }
  };

  const handleReset = () => {
    setState('idle');
    setActiveTab('paste');
    setTextInput('');
    setError(null);
    setResponse(null);
    clearImage();
  };

  const handlePracticeClick = async () => {
    if (!response?.topic || !originalProblem) return;

    setPracticeLoading(true);
    try {
      const result = await generatePractice({
        topic: response.topic,
        original_problem: originalProblem,
        num_questions: 3
      });
      setPracticeQuestions(result.questions);

      // Save quiz immediately to session
      if (currentSessionId) {
        await updateSession(currentSessionId, {
          practiceQuiz: result.questions,
        });
        setHistorySessions(await getHistory());
      }

      setState('practice');
    } catch (err) {
      console.error('Practice generation error:', err);
      setError('Failed to generate practice problems. Please try again.');
    } finally {
      setPracticeLoading(false);
    }
  };

  const handleMoreQuestions = async () => {
    if (!response?.topic || !originalProblem) return;

    setPracticeLoading(true);
    try {
      const result = await generatePractice({
        topic: response.topic,
        original_problem: originalProblem,
        num_questions: 3
      });

      // Append new questions to existing
      const allQuestions = [...practiceQuestions, ...result.questions];
      setPracticeQuestions(allQuestions);

      // Save updated quiz to session
      if (currentSessionId) {
        await updateSession(currentSessionId, {
          practiceQuiz: allQuestions,
        });
        setHistorySessions(await getHistory());
      }
    } catch (err) {
      console.error('More questions error:', err);
    } finally {
      setPracticeLoading(false);
    }
  };

  const handleBackFromPractice = async (score?: { correct: number; total: number }) => {
    // Update session with cumulative practice score if provided
    if (currentSessionId && score) {
      // Get existing score and add to it
      const sessions = await getHistory();
      const currentSession = sessions.find(s => s.id === currentSessionId);
      const existingScore = currentSession?.practiceScore || { correct: 0, total: 0 };

      const newScore = {
        correct: existingScore.correct + score.correct,
        total: existingScore.total + score.total,
      };

      await updateSession(currentSessionId, {
        practiceQuiz: practiceQuestions,
        practiceScore: newScore,
      });
      setHistorySessions(await getHistory());
    }
    setState('solution');
    // Don't clear practiceQuestions - keep them for Review Quiz button
  };

  const handleDeleteSession = async (sessionId: string) => {
    await deleteSession(sessionId);
    setHistorySessions(await getHistory());
    // Sync deletion to Backboard memory (fire-and-forget)
    deleteProblemMemory(getUserId(), sessionId);
  };

  // YouTube Videos Handlers
  const handleVideosClick = async () => {
    if (!response?.topic || !originalProblem || !currentSessionId) return;

    // If we already have videos, just navigate to view
    if (youtubeVideos.length > 0) {
      setState('videos');
      return;
    }

    // Fetch new videos
    setVideosLoading(true);
    setState('videos');

    try {
      const result = await getYouTubeResources({
        problem_id: currentSessionId,
        problem_text: originalProblem,
        topic: response.topic,
        offset: 0,
      });

      setYoutubeVideos(result.videos);
      setVideosHasMore(result.has_more);
      setVideosOffset(result.videos.length);

      // Cache to session
      await updateSession(currentSessionId, {
        youtubeVideos: result.videos,
      });
      setHistorySessions(await getHistory());
    } catch (err) {
      console.error('Failed to fetch videos:', err);
    } finally {
      setVideosLoading(false);
    }
  };

  const handleLoadMoreVideos = async () => {
    if (!response?.topic || !originalProblem || !currentSessionId) return;

    setVideosLoadingMore(true);

    try {
      const result = await getYouTubeResources({
        problem_id: currentSessionId,
        problem_text: originalProblem,
        topic: response.topic,
        offset: videosOffset,
      });

      const allVideos = [...youtubeVideos, ...result.videos];
      setYoutubeVideos(allVideos);
      setVideosHasMore(result.has_more);
      setVideosOffset(videosOffset + result.videos.length);

      // Update cache
      await updateSession(currentSessionId, {
        youtubeVideos: allVideos,
      });
      setHistorySessions(await getHistory());
    } catch (err) {
      console.error('Failed to load more videos:', err);
    } finally {
      setVideosLoadingMore(false);
    }
  };

  const handleClearHistory = async () => {
    await clearHistory();
    setHistorySessions([]);
  };

  const handleSelectSession = (session: HistorySession) => {
    // Load session into view
    setResponse({
      thread_id: '',
      status: 'completed',
      requires_user_action: false,
      topic: session.topic,
      solution_steps: session.solutionSteps,
      final_answer: session.finalAnswer,
    });
    setOriginalProblem(session.problem);
    setCurrentSessionId(session.id);
    // Load expanded sub-steps from history
    setCurrentSubSteps(session.expandedSubSteps || {});
    // Set practice questions if exists, otherwise clear them
    if (session.practiceQuiz && session.practiceQuiz.length > 0) {
      setPracticeQuestions(session.practiceQuiz);
    } else {
      setPracticeQuestions([]);
    }
    // Load cached YouTube videos if exists
    if (session.youtubeVideos && session.youtubeVideos.length > 0) {
      setYoutubeVideos(session.youtubeVideos);
      setVideosHasMore(session.youtubeVideos.length >= 3);
    } else {
      setYoutubeVideos([]);
      setVideosHasMore(false);
    }
    setVideosOffset(0);
    setState('solution');
  };

  // Render current view based on state
  const renderContent = () => {
    if (state === 'loading') {
      return <LoadingView />;
    }

    if (state === 'disambiguation' && response?.candidate_topics) {
      return (
        <DisambiguationView
          topics={response.candidate_topics}
          onSelect={handleTopicSelection}
        />
      );
    }

    if (state === 'practice' && practiceQuestions.length > 0) {
      return (
        <PracticeView
          topic={response?.topic || ''}
          questions={practiceQuestions}
          onBack={handleBackFromPractice}
          onMoreQuestions={handleMoreQuestions}
          loading={practiceLoading}
        />
      );
    }

    if (state === 'solution' && (response?.final_response_html || response?.solution_steps)) {
      const handleSubStepsChange = async (subSteps: Record<string, SubStep[]>) => {
        setCurrentSubSteps(subSteps);
        if (currentSessionId) {
          await updateSession(currentSessionId, { expandedSubSteps: subSteps });
          setHistorySessions(await getHistory());
        }
      };

      return (
        <SolutionView
          html={response.final_response_html}
          topic={response.topic}
          solutionSteps={response.solution_steps}
          finalAnswer={response.final_answer}
          originalProblem={originalProblem}
          onPracticeClick={handlePracticeClick}
          practiceLoading={practiceLoading}
          initialSubSteps={currentSubSteps}
          onSubStepsChange={handleSubStepsChange}
          hasStoredQuiz={practiceQuestions.length > 0}
          onReviewQuiz={() => setState('practice')}
          onVideosClick={handleVideosClick}
          videosLoading={videosLoading}
          hasStoredVideos={youtubeVideos.length > 0}
        />
      );
    }

    if (state === 'videos') {
      return (
        <YouTubeVideosView
          videos={youtubeVideos}
          loading={videosLoading}
          hasMore={videosHasMore}
          loadingMore={videosLoadingMore}
          onLoadMore={handleLoadMoreVideos}
          onBack={() => setState('solution')}
          topic={response?.topic || undefined}
        />
      );
    }

    if (state === 'error') {
      return (
        <div className="space-y-4">
          <Alert variant="destructive">
            <AlertIcon className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error || 'An unexpected error occurred'}</AlertDescription>
          </Alert>
          <Button onClick={handleReset} variant="outline" className="w-full">
            Try Again
          </Button>
        </div>
      );
    }

    if (state === 'history') {
      return (
        <HistoryView
          sessions={historySessions}
          folders={folders}
          onDelete={handleDeleteSession}
          onClearAll={handleClearHistory}
          onSelectSession={handleSelectSession}
          onCreateFolder={async (name, color) => {
            const newFolder = await createFolder(name, color);
            setFolders(prev => [...prev, newFolder]);
          }}
          onCreateAndPopulateFolder={async (name, color, sessionIds) => {
            // Create the folder first
            const newFolder = await createFolder(name, color);
            setFolders(prev => [...prev, newFolder]);

            // Then move all sessions into the new folder
            await batchMoveToFolder(sessionIds, newFolder.id);
            const updated = await getHistory();
            setHistorySessions(updated);
          }}
          onDeleteFolder={async (folderId) => {
            await deleteFolderStorage(folderId);
            setFolders(prev => prev.filter(f => f.id !== folderId));
            const updated = await getHistory();
            setHistorySessions(updated);
            // Sync deletion to Backboard memory (fire-and-forget)
            deleteFolderMemory(getUserId(), folderId);
          }}
          onMoveToFolder={async (sessionId, folderId) => {
            await moveToFolder(sessionId, folderId);
            const updated = await getHistory();
            setHistorySessions(updated);
          }}
          onBatchMove={async (sessionIds, folderId) => {
            await batchMoveToFolder(sessionIds, folderId);
            const updated = await getHistory();
            setHistorySessions(updated);
          }}
          onBatchMarkReviewed={async (sessionIds, reviewed) => {
            await batchMarkReviewed(sessionIds, reviewed);
            const updated = await getHistory();
            setHistorySessions(updated);
          }}
          onBatchDelete={async (sessionIds) => {
            await batchDeleteSessions(sessionIds);
            const updated = await getHistory();
            setHistorySessions(updated);
          }}
        />
      );
    }

    return (
      <div className="space-y-4">
        {/* Ask Stepwise Heading */}
        <h2 className="text-2xl font-bold text-white">Ask Stepwise</h2>

        {/* Underlined Tabs */}
        <div className="underline-tabs">
          <button
            className={`underline-tab ${activeTab === 'paste' ? 'active' : ''}`}
            onClick={() => setActiveTab('paste')}
          >
            Text Input
          </button>
          <button
            className={`underline-tab ${activeTab === 'screenshot' ? 'active' : ''}`}
            onClick={() => setActiveTab('screenshot')}
          >
            Upload Image
          </button>
          <button
            className={`underline-tab ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => { setActiveTab('history'); setState('history'); }}
          >
            History
          </button>
        </div>

        {activeTab === 'paste' && (
          <div className="space-y-4">
            {/* Your Question Label */}
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 rounded-full bg-indigo-500"></div>
              <span className="text-sm text-slate-300">Your Question</span>
            </div>

            {/* Glowing Textarea */}
            <div className="glow-border p-1">
              <Textarea
                placeholder="Paste your math problem, equation, or question here...

Example: Solve for x: 2x + 5 = 13"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                rows={8}
                className="resize-none bg-transparent border-0 focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>

            {/* Gradient Button */}
            <button
              onClick={handleTextSubmit}
              disabled={!textInput.trim()}
              className="gradient-button w-full flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Analyze & Explain
              <Sparkles className="h-4 w-4" />
            </button>
          </div>
        )}

        {activeTab === 'screenshot' && (
          <div className="space-y-4">
            {/* Hidden file input */}
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept="image/*"
              className="hidden"
            />

            {/* Upload zone with glowing border */}
            {imagePreview ? (
              <div className="glow-border p-4">
                <div className="relative group">
                  <img
                    src={imagePreview}
                    alt="Uploaded problem"
                    className="w-full rounded-lg max-h-56 object-contain bg-slate-900/50"
                  />
                  {/* Elegant small X button */}
                  <button
                    onClick={clearImage}
                    className="absolute top-2 right-2 h-6 w-6 rounded-full bg-slate-800/90 hover:bg-red-500 text-slate-400 hover:text-white flex items-center justify-center transition-colors opacity-0 group-hover:opacity-100"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ) : (
              <div
                className="glow-border flex flex-col items-center justify-center py-12 px-8 cursor-pointer hover:border-indigo-500 transition-all"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={handleDragOver}
                onDragEnter={handleDragOver}
                onDrop={handleFileDrop}
              >
                <Upload className="h-14 w-14 text-indigo-400 mb-4" />
                <p className="text-sm text-slate-300 text-center mb-1">
                  Click to upload or drag and drop
                </p>
                <p className="text-xs text-slate-500">
                  PNG, JPG up to 10MB
                </p>
              </div>
            )}

            {/* Gradient Button */}
            <button
              onClick={handleImageSubmit}
              disabled={!uploadedImage}
              className="gradient-button w-full flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Analyze & Explain
              <Sparkles className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="w-full h-full bg-background text-foreground overflow-y-auto">
      {/* Stepwise Floating Header */}
      <div className="p-3">
        <div className="stepwise-header">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
              <span className="text-white font-bold text-sm">π</span>
            </div>
            <h1 className="text-base font-semibold text-white">Stepwise</h1>
          </div>
          {/* Auth status + account menu */}
          <div className="flex items-center gap-2">
            {/* Auth status pill */}
            {authState.mode !== 'initializing' && (
              <div className="relative">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowAccountMenu((v) => !v);
                  }}
                  className="flex items-center gap-1.5 text-xs px-2 py-1 rounded-full transition-colors
                    hover:bg-white/10
                    text-slate-400 hover:text-white"
                  title={authState.mode === 'cloud' ? `Signed in as ${authState.email}` : 'Local mode'}
                >
                  {authState.mode === 'cloud' ? (
                    <>
                      <Cloud className="h-3 w-3 text-emerald-400" />
                      <span className="max-w-[80px] truncate hidden sm:inline">{authState.email ?? 'Cloud'}</span>
                    </>
                  ) : (
                    <>
                      <HardDrive className="h-3 w-3 text-amber-400" />
                      <span className="hidden sm:inline">Local</span>
                    </>
                  )}
                </button>

                {/* Account dropdown */}
                {showAccountMenu && (
                  <div className="absolute right-0 top-full mt-1 w-56 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 py-1 text-sm">
                    {authState.mode === 'cloud' ? (
                      <>
                        <div className="px-3 py-2 border-b border-slate-700">
                          <p className="text-white font-medium truncate">{authState.displayName ?? 'Signed in'}</p>
                          <p className="text-slate-400 text-xs truncate">{authState.email}</p>
                        </div>
                        <button
                          onClick={async () => {
                            setShowAccountMenu(false);
                            await authSignOut();
                          }}
                          className="w-full flex items-center gap-2 px-3 py-2 text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
                        >
                          <LogOut className="h-3.5 w-3.5" />
                          Sign out
                        </button>
                      </>
                    ) : (
                      <>
                        <div className="px-3 py-2 border-b border-slate-700">
                          <p className="text-slate-300 text-xs">Local mode — this device only</p>
                        </div>
                        <button
                          onClick={async () => {
                            setShowAccountMenu(false);
                            try {
                              await signInInteractive();
                            } catch (err) {
                              const msg = err instanceof Error ? err.message : String(err);
                              console.error('Sign-in failed:', msg);
                              setError(`Sign-in failed: ${msg}`);
                              setState('error');
                            }
                          }}
                          className="w-full flex items-center gap-2 px-3 py-2 text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
                        >
                          <LogIn className="h-3.5 w-3.5" />
                          Sign in to enable sync
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {state === 'idle' && (
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  (async () => {
                    try {
                      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
                      if (tab?.windowId) {
                        chrome.runtime.sendMessage(
                          { action: 'openSidePanel', windowId: tab.windowId },
                          (response) => {
                            if (response?.success) {
                              window.close();
                            }
                          }
                        );
                      }
                    } catch (err) {
                      console.error('Failed to open side panel:', err);
                    }
                  })();
                }}
                className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors px-2 py-1 rounded-md hover:bg-white/5"
                title="Pin to side panel"
              >
                <Pin className="h-3.5 w-3.5" />
                Pin
              </button>
            )}
            {/* Back button - visible when not idle */}
            {state !== 'idle' && (
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  handleReset();
                }}
                className="text-slate-400 hover:text-white"
              >
                Back
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="p-4">
        {renderContent()}
      </div>

      {/* Reset Confirmation Modal */}
      {showResetConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-800 rounded-xl p-6 max-w-sm w-full border border-slate-700 shadow-xl">
            <h3 className="text-lg font-semibold text-white mb-2">Reset History?</h3>
            <p className="text-sm text-slate-400 mb-6">
              Are you sure you want to reset your entire history?
            </p>
            <div className="flex gap-3 justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowResetConfirm(false)}
                className="text-slate-400 hover:text-white"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  clearHistory();
                  setHistorySessions([]);
                  setShowResetConfirm(false);
                }}
                className="bg-red-600 hover:bg-red-700"
              >
                Reset All
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;

