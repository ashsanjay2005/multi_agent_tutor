-- =============================================================================
-- Supabase Migration: AI STEM Tutor (Stepwise)
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- =============================================================================

-- 1. PROFILES: Core user settings
CREATE TABLE public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name TEXT,
  avatar_url TEXT,
  grade_level TEXT,
  preferences JSONB DEFAULT '{}'::JSONB,
  onboarding_completed BOOLEAN DEFAULT FALSE,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. CHAT_SESSIONS: Containers for each tutoring interaction
CREATE TABLE public.chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  title TEXT,
  topic TEXT,
  model TEXT,
  langgraph_thread_id TEXT,
  archived BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. CHAT_MESSAGES: Structured storage for tutor conversations
--    user_id is denormalized here for simpler RLS and direct queries
CREATE TABLE public.chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role TEXT CHECK (role IN ('user', 'assistant', 'system', 'tool')),
  content_text TEXT,        -- Plain text for preview/search
  content_json JSONB,       -- Final structured content (LaTeX steps, tool outputs)
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. SAVED_PROBLEMS: User's personal math problem library
CREATE TABLE public.saved_problems (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  problem_text TEXT NOT NULL,
  problem_hash TEXT,
  topic TEXT,
  solution_summary TEXT,
  solution_json JSONB,
  source TEXT,               -- 'typed', 'image', 'import', etc.
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. TOPICS: Normalized topic names (avoids "Integrals" vs "Integration" typos)
CREATE TABLE public.topics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  parent_topic_id UUID REFERENCES public.topics(id)
);

-- 6. USER_PROGRESS: Per-topic mastery tracking
CREATE TABLE public.user_progress (
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  topic_id UUID NOT NULL REFERENCES public.topics(id) ON DELETE CASCADE,
  mastery_score NUMERIC(5,2) DEFAULT 0,
  attempts INT DEFAULT 0,
  successes INT DEFAULT 0,
  last_practiced_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, topic_id)
);

-- 7. FEEDBACK: Per-message or per-session user rating
CREATE TABLE public.feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID REFERENCES public.chat_sessions(id) ON DELETE SET NULL,
  message_id UUID REFERENCES public.chat_messages(id) ON DELETE SET NULL,
  rating INT CHECK (rating BETWEEN 1 AND 5),
  comment TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. VIDEO_CACHE: Global caching (non-user-owned)
CREATE TABLE public.video_cache (
  problem_hash TEXT PRIMARY KEY,
  videos JSONB NOT NULL,
  grade_level TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);

-- =============================================================================
-- INDEXES
-- =============================================================================
CREATE INDEX idx_sessions_user_updated ON public.chat_sessions(user_id, updated_at DESC);
CREATE INDEX idx_sessions_user_archived ON public.chat_sessions(user_id, archived);
CREATE INDEX idx_messages_session_time ON public.chat_messages(session_id, created_at);
CREATE INDEX idx_messages_user_time ON public.chat_messages(user_id, created_at DESC);
CREATE INDEX idx_problems_user_hash ON public.saved_problems(user_id, problem_hash);
CREATE INDEX idx_problems_user_time ON public.saved_problems(user_id, created_at DESC);
CREATE INDEX idx_progress_user ON public.user_progress(user_id);
CREATE INDEX idx_video_cache_expires ON public.video_cache(expires_at);

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saved_problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback ENABLE ROW LEVEL SECURITY;
-- video_cache: no RLS (service role writes only, public reads)

-- =============================================================================
-- POLICIES: Users can only see/modify their own data
-- =============================================================================
CREATE POLICY "Profiles: Users see own" ON public.profiles
  FOR ALL USING (auth.uid() = id);

CREATE POLICY "Sessions: Users see own" ON public.chat_sessions
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Messages: Users see own" ON public.chat_messages
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Problems: Users see own" ON public.saved_problems
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Progress: Users see own" ON public.user_progress
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Feedback: Users see own" ON public.feedback
  FOR ALL USING (auth.uid() = user_id);

-- =============================================================================
-- AUTO-CREATE PROFILE ON SIGNUP (Supabase trigger)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, full_name, avatar_url)
  VALUES (
    NEW.id,
    NEW.raw_user_meta_data->>'full_name',
    NEW.raw_user_meta_data->>'avatar_url'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
