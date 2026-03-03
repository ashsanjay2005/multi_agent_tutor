"""
FastAPI Application for AI Math Tutor Backend
"""

import logging
import asyncio
import uuid
from typing import Literal, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import base64

from config import settings
from graph import get_graph
from state import GraphState
from rate_limiter import (
    init_rate_limiter, 
    close_rate_limiter, 
    get_rate_limiter,
    RateLimitConfig
)
from cache import init_video_cache, get_video_cache
from youtube_resources_graph import get_youtube_graph, YouTubeResourcesState
from backboard_client import get_backboard_service, is_backboard_available
import supabase_client

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class AnalyzeRequest(BaseModel):
    type: Literal["text", "image"] = Field(...)
    content: str = Field(..., min_length=1)
    user_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: Optional[str] = Field(None)
    
    @validator("content")
    def validate_content(cls, v, values):
        if values.get("type") == "image":
            try:
                base64.b64decode(v, validate=True)
            except Exception:
                raise ValueError("Invalid base64 encoding")
        return v

class ResumeRequest(BaseModel):
    thread_id: str = Field(...)
    selected_topic: str = Field(..., min_length=1)

class ExplainStepRequest(BaseModel):
    """Request payload for /v1/explain_step"""
    step_text: str = Field(...)
    context: str = Field(...)
    topic: str = Field(...)

class AnalyzeResponse(BaseModel):
    thread_id: str
    status: Literal["completed", "requires_disambiguation", "requires_clarification", "error"]
    requires_user_action: bool
    final_response_html: Optional[str] = None
    candidate_topics: Optional[list[str]] = None
    topic: Optional[str] = None
    confidence_score: Optional[float] = None
    solution_steps: Optional[list[dict]] = None  # Step-by-step solution
    final_answer: Optional[str] = None  # Final answer from solver
    extracted_problem: Optional[str] = None  # Problem text (extracted from image or original text)

class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    environment: str

# Sub-step expansion models
class PreviousStepSummary(BaseModel):
    """Summary of a previous step for context."""
    label: str
    title: str
    summary: str  # 1-line summary

class ExpandStepRequest(BaseModel):
    """Request to break down a step into sub-steps."""
    step_id: str = Field(..., description="Unique ID of the step")
    step_path: str = Field(..., description="Path in tree, e.g., '1', '1.2', '1.2.1'")
    step_title: str = Field(...)
    step_explanation: str = Field(...)
    step_math: Optional[str] = None
    problem_statement: str = Field(..., description="Original problem text")
    topic: str = Field(...)
    current_depth: int = Field(..., ge=0, le=3)
    previous_steps: Optional[list[PreviousStepSummary]] = None

class SubStep(BaseModel):
    """A sub-step generated from expanding a parent step."""
    id: str
    label: str  # e.g., "1.1", "1.2.1"
    order: int  # 1, 2, 3... within siblings
    title: str
    explanation: str
    math_expression: Optional[str] = None
    can_expand: bool = True

class ExpandStepResponse(BaseModel):
    """Response containing sub-steps or stop indication."""
    sub_steps: list[SubStep] = []
    can_expand: bool = True
    stop_reason: Optional[Literal["atomic", "max_depth", "loop_risk", "insufficient_context"]] = None
    message: Optional[str] = None


# YouTube Resources models
class ResourcesRequest(BaseModel):
    """Request for YouTube video resources."""
    problem_id: str = Field(..., description="Session ID from frontend")
    problem_text: str = Field(..., description="The math problem text")
    topic: str = Field(..., description="Detected topic")
    offset: int = Field(default=0, ge=0, description="Pagination offset (0, 3, 6, ...)")


class VideoResource(BaseModel):
    """A single YouTube video resource."""
    video_id: str
    title: str
    thumbnail_url: str
    youtube_url: str
    relevance_summary: str  # AI-generated "Why this video?"


class ResourcesResponse(BaseModel):
    """Response with YouTube video resources."""
    videos: list[VideoResource]
    has_more: bool
    total_fetched: int


# Student Profiling models (Backboard diagnostic logging)
class LogBreakdownRequest(BaseModel):
    """Request to log when a student clicks 'breakdown' on a step."""
    user_id: str = Field(..., description="User ID for thread lookup")
    step_title: str = Field(..., description="Title of the step being broken down")
    concept: str = Field(..., description="Normalized concept tag (e.g., 'negative_signs', 'matrix_multiplication')")
    context: str = Field(..., description="Problem statement or step explanation")


class LogQuizResultRequest(BaseModel):
    """Request to log a quiz/practice result."""
    user_id: str = Field(..., description="User ID for thread lookup")
    concept: str = Field(..., description="Concept being tested (e.g., 'cross_product')")
    correct: bool = Field(..., description="Whether the answer was correct")
    question_summary: str = Field(..., description="Brief summary of the question")


class SyncFolderRequest(BaseModel):
    """Request to sync folder definition to Backboard memory."""
    user_id: str = Field(..., description="User ID for thread lookup")
    folder_id: str = Field(..., description="Unique folder identifier")
    folder_name: str = Field(..., description="Current folder name")


class SuggestFolderRequest(BaseModel):
    """Request to get semantic folder suggestion for a problem."""
    user_id: str = Field(..., description="User ID for thread lookup")
    session_id: str = Field(..., description="Current session/problem ID")
    topic: str = Field(..., description="Problem topic")
    problem_text: str = Field(..., description="Problem text for semantic matching")


class FolderSuggestionResponse(BaseModel):
    """Semantic folder suggestion result."""
    action: str = Field(..., description="'add_to_folder' | 'suggest_new_folder' | 'no_suggestion'")
    folder_id: Optional[str] = Field(None, description="Suggested folder ID")
    folder_name: Optional[str] = Field(None, description="Suggested folder name")
    similarity_score: float = Field(0.0, description="Match confidence 0-1")
    similar_unfiled: list[dict] = Field(default_factory=list, description="Similar unfiled problems")
    alternate_folder: Optional[dict] = Field(None, description="Did you mean? alternative")


class DeleteFolderRequest(BaseModel):
    """Request to delete folder from Backboard memory."""
    user_id: str = Field(..., description="User ID for thread lookup")
    folder_id: str = Field(..., description="Folder ID to delete")


class DeleteProblemRequest(BaseModel):
    """Request to delete problem from Backboard memory."""
    user_id: str = Field(..., description="User ID for thread lookup")
    session_id: str = Field(..., description="Session/problem ID to delete")


class SimilarProblemsRequest(BaseModel):
    """Request to find semantically similar problems."""
    user_id: str = Field(..., description="User ID for thread lookup")
    topic: str = Field(..., description="Current problem topic")
    problem_text: str = Field(..., description="Current problem text")


class SimilarProblem(BaseModel):
    """A similar problem found in memory."""
    topic: str
    similarity: float


class SimilarProblemsResponse(BaseModel):
    """Response with similar problems for grouping suggestions."""
    similar_problems: list[SimilarProblem]
    suggested_folder_name: str | None = None

# ============================================================================
# LIFECYCLE & APP
# ============================================================================

app_graph = None          # Lightweight graph (no checkpointer) — default
app_graph_ckpt = None     # Checkpointed graph — for disambiguation/resume only
video_cache = None
_db_pool = None  # Connection pool — closed on shutdown

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_graph, app_graph_ckpt, _db_pool
    logger.info("Starting up AI Math Tutor Backend...")
    
    # Initialize rate limiter
    try:
        rate_config = RateLimitConfig(
            free_limit=settings.rate_limit_free,
            pro_limit=settings.rate_limit_pro,
            window_seconds=settings.rate_limit_window
        )
        await init_rate_limiter(settings.redis_url)
        logger.info(f"Rate limiter initialized (free={settings.rate_limit_free}/min, pro={settings.rate_limit_pro}/min)")
    except Exception as e:
        logger.warning(f"Rate limiter unavailable (Redis connection failed): {e}")
    
    # Initialize graph + connection pool in the BACKGROUND
    # This is critical so Uvicorn can start listening on the port immediately,
    # otherwise Cloud Run health checks will kill the container while we retry.
    async def init_graph_bg():
        global _db_pool, app_graph_ckpt, app_graph
        try:
            pool, ckpt, graph = await get_graph()
            _db_pool = pool
            app_graph_ckpt = ckpt
            app_graph = graph
            logger.info("LangGraph workflow initialized successfully in background")
        except Exception as e:
            logger.error(f"Background graph init failed (will retry on first request): {e}")

    asyncio.create_task(init_graph_bg())
    
    # Initialize video cache
    global video_cache
    try:
        video_cache = await init_video_cache(settings.database_url)
        logger.info("Video cache initialized")
    except Exception as e:
        logger.warning(f"Video cache unavailable: {e}")
    
    # Initialize Backboard.io for persistent memory
    if is_backboard_available():
        try:
            await get_backboard_service()
            logger.info("Backboard.io initialized with LoCoMo memory enabled")
        except Exception as e:
            logger.warning(f"Backboard.io unavailable: {e}")
    else:
        logger.info("Backboard.io not configured (no BACKBOARD_API_KEY)")
    
    # Ensure Supabase Storage bucket exists for image offload
    try:
        await supabase_client.ensure_storage_bucket()
        logger.info("Supabase Storage bucket ready")
    except Exception as e:
        logger.warning(f"Supabase Storage bucket setup failed (non-critical): {e}")
    
    yield
    
    # Cleanup
    logger.info("Shutting down...")
    if _db_pool:
        await _db_pool.close()
        logger.info("Database pool closed")
    await close_rate_limiter()

app = FastAPI(
    title="AI Math Tutor API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="healthy", environment=settings.environment)

@app.get("/v1/quota")
async def get_quota(user_id: str = "anonymous"):
    """Get current rate limit quota status for a user."""
    try:
        limiter = await get_rate_limiter()
        user_tier = "free"  # In production, look up from DB
        quota = await limiter.get_quota_status(user_id, tier=user_tier)
        return quota
    except RuntimeError:
        # Rate limiter not available
        return {
            "remaining": -1,  # -1 means unlimited
            "limit": -1,
            "window_seconds": 60,
            "reset_in_seconds": 0,
            "tier": "unlimited",
            "message": "Rate limiting not enabled"
        }

@app.post("/v1/analyze", response_model=AnalyzeResponse)
async def analyze_problem(request: AnalyzeRequest):
    global app_graph, app_graph_ckpt, _db_pool
    
    # Lazy init: if graph failed during startup, retry now
    if app_graph is None:
        try:
            logger.info("Graph not initialized — attempting lazy initialization...")
            _db_pool, app_graph_ckpt, app_graph = await get_graph()
            logger.info("Lazy graph initialization succeeded!")
        except Exception as e:
            logger.error(f"Lazy graph initialization failed: {e}")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Database unavailable: {e}")
    
    # Check rate limit
    try:
        limiter = await get_rate_limiter()
        # Default to free tier - in production, you'd look up user tier from DB
        user_tier = "free"  
        allowed, remaining, reset_in = await limiter.check_rate_limit(
            request.user_id, 
            tier=user_tier
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Try again in {reset_in} seconds.",
                    "retry_after": reset_in,
                    "remaining": 0,
                    "limit": settings.rate_limit_free if user_tier == "free" else settings.rate_limit_pro
                },
                headers={"Retry-After": str(reset_in)}
            )
    except RuntimeError:
        # Rate limiter not available, continue without limiting
        logger.debug("Rate limiter not available, skipping rate limit check")
    
    thread_id = request.thread_id or str(uuid.uuid4())
    logger.info(f"[Analyze] Request Type: {request.type}, Thread: {thread_id}")
    
    try:
        # Get or create Backboard thread for persistent memory
        backboard_thread_id = None
        if is_backboard_available():
            try:
                backboard = await get_backboard_service()
                backboard_thread_id = await backboard.get_or_create_thread(request.user_id)
            except Exception as e:
                logger.warning(f"Backboard thread creation failed: {e}")
        
        # Offload images to Supabase Storage (reduces checkpoint blob size ~80%)
        content_for_state = request.content
        if request.type == "image":
            try:
                image_url = await supabase_client.upload_image(
                    request.content, thread_id
                )
                content_for_state = image_url
                logger.info(f"[Analyze] Image offloaded to storage: {image_url[:80]}...")
            except Exception as e:
                logger.warning(f"[Analyze] Image upload failed, using base64 fallback: {e}")
        
        initial_state: GraphState = {
            "input_type": request.type,
            "input_content": content_for_state,
            "user_id": request.user_id,
            "thread_id": thread_id,
            "backboard_thread_id": backboard_thread_id,
            "topic": None,
            "confidence_score": 0.0,
            "detected_ambiguity": False,
            "candidate_topics": [],
            "teaching_plan": None,
            "worked_example": None,
            "practice_problem": None,
            "video_url": None,
            "solution_steps": None,
            "final_response_html": None,
            "requires_user_action": False
        }
        
        # Use lightweight (non-checkpointed) graph by default — zero checkpoint overhead
        result = await app_graph.ainvoke(initial_state)
        
        response_status = "completed"
        if result["requires_user_action"]:
            response_status = "requires_disambiguation" if result.get("candidate_topics") else "requires_clarification"
        
        # Persist session + messages to Supabase (fire-and-forget, non-blocking)
        try:
            session = await supabase_client.create_session(
                user_id=request.user_id,
                title=result.get("input_content", "")[:100],
                topic=result.get("topic", ""),
                model=settings.text_model,
                langgraph_thread_id=thread_id,
            )
            session_id = session["id"]
            
            # Save user message
            await supabase_client.save_message(
                session_id=session_id,
                user_id=request.user_id,
                role="user",
                content_text=request.content[:500] if request.type == "text" else "[image]",
            )
            
            # Save assistant response
            await supabase_client.save_message(
                session_id=session_id,
                user_id=request.user_id,
                role="assistant",
                content_text=result.get("worked_example", "")[:500],
                content_json={
                    "solution_steps": result.get("solution_steps"),
                    "final_answer": result.get("worked_example"),
                    "topic": result.get("topic"),
                    "confidence": result.get("confidence_score"),
                },
            )
            # Save to saved_problems table
            await supabase_client.save_problem(
                user_id=request.user_id,
                problem_text=(
                    request.content[:500]
                    if request.type == "text"
                    else result.get("topic", "image problem")
                ),
                topic=result.get("topic", ""),
                solution_summary=result.get("worked_example", "")[:500],
                solution_json={
                    "solution_steps": result.get("solution_steps"),
                    "final_answer": result.get("worked_example"),
                },
                source=request.type,
            )
            logger.info(f"[Analyze] Persisted session {session_id} + problem to Supabase")
        except Exception as e:
            logger.warning(f"[Analyze] Supabase persistence failed (non-critical): {e}")
        
        return AnalyzeResponse(
            thread_id=thread_id,
            status=response_status,
            requires_user_action=result["requires_user_action"],
            final_response_html=result.get("final_response_html"),
            candidate_topics=result.get("candidate_topics"),
            topic=result.get("topic"),
            confidence_score=result.get("confidence_score"),
            solution_steps=result.get("solution_steps"),
            final_answer=result.get("worked_example"),
            extracted_problem=result.get("input_content")  # Contains extracted text for images
        )
    except Exception as e:
        logger.error(f"[Analyze] Error: {e}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))

@app.post("/v1/resume", response_model=AnalyzeResponse)
async def resume_workflow(request: ResumeRequest):
    global app_graph_ckpt
    if app_graph_ckpt is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Graph not initialized")
    
    try:
        config = {"configurable": {"thread_id": request.thread_id}}
        state = await app_graph_ckpt.aget_state(config)
        
        if not state:
             raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")

        # Resume by updating topic and proceeding
        updated_state = {
            "topic": request.selected_topic,
            "confidence_score": 1.0,
            "detected_ambiguity": False,
            "requires_user_action": False
        }
        
        # In v0.2, we update state and create a new run
        await app_graph_ckpt.aupdate_state(config, updated_state)
        # Invoke with None input to resume execution from current state
        final_state = await app_graph_ckpt.ainvoke(None, config)
        
        return AnalyzeResponse(
            thread_id=request.thread_id,
            status="completed",
            requires_user_action=False,
            final_response_html=final_state["final_response_html"],
            topic=final_state["topic"],
            confidence_score=final_state["confidence_score"]
        )
    except Exception as e:
        logger.error(f"[Resume] Error: {e}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))

@app.post("/v1/expand_step", response_model=ExpandStepResponse)
async def expand_step(request: ExpandStepRequest):
    """
    Break down a solution step into 2-4 sub-steps.
    Uses parent step as context, doesn't restate the full problem.
    """
    logger.info(f"[ExpandStep] Path: {request.step_path}, Depth: {request.current_depth}")
    
    # Check max depth
    if request.current_depth >= 3:
        return ExpandStepResponse(
            sub_steps=[],
            can_expand=False,
            stop_reason="max_depth",
            message="Maximum explanation depth reached. Consider watching a video or reading detailed notes."
        )
    
    # Build context from previous steps
    prev_context = ""
    if request.previous_steps:
        prev_context = "\n".join([
            f"- {s.label}: {s.title} ({s.summary})" 
            for s in request.previous_steps[:5]  # Limit to last 5
        ])
    
    # Build optional sections (f-strings can't have backslashes)
    math_line = f"- Math: {request.step_math}" if request.step_math else ""
    prev_section = f"PREVIOUS CONTEXT:\n{prev_context}" if prev_context else ""
    
    # Build the prompt
    prompt = f"""You are a math tutor explaining a solution step in more detail.

PROBLEM: {request.problem_statement}
TOPIC: {request.topic}

STEP TO BREAK DOWN:
- Title: {request.step_title}
- Explanation: {request.step_explanation}
{math_line}

{prev_section}

Break this step into 2-4 smaller sub-steps that explain HOW this step works.

RULES:
1. Do NOT restate the overall problem
2. Do NOT introduce new high-level concepts
3. Each sub-step should be NARROWER than the parent
4. Each explanation: 1-4 sentences max
5. Include math_expression only if there's a specific formula/equation
6. Set can_expand: false if a sub-step is atomic (cannot be broken down further)

Return ONLY valid JSON matching this format (no markdown, no extra text):
{{
  "sub_steps": [
    {{
      "order": 1,
      "title": "Sub-step title",
      "explanation": "Brief explanation",
      "math_expression": "optional LaTeX",
      "can_expand": true
    }}
  ],
  "is_atomic": false
}}

Set is_atomic: true if this step cannot be meaningfully decomposed."""

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        import json
        import re
        import uuid
        
        llm = ChatGoogleGenerativeAI(
            model=settings.text_model,
            google_api_key=settings.google_api_key,
            temperature=0.3
        )
        
        result = await llm.ainvoke(prompt)
        response_text = result.content
        
        # Parse JSON from response
        start_idx = response_text.find('{')
        if start_idx == -1:
            raise ValueError("No JSON in response")
        
        # Find matching brace
        brace_count = 0
        end_idx = start_idx
        for i, char in enumerate(response_text[start_idx:], start_idx):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i
                    break
        
        json_str = response_text[start_idx:end_idx + 1]
        
        # Fix common JSON escape issues with LaTeX backslashes
        # The LLM often returns unescaped backslashes in LaTeX
        import re
        def fix_backslashes(s):
            result = []
            i = 0
            while i < len(s):
                if s[i] == '\\' and i + 1 < len(s):
                    next_char = s[i + 1]
                    # Valid JSON escape sequences
                    if next_char in '"\\bfnrtu/':
                        result.append(s[i:i+2])
                        i += 2
                    else:
                        # Escape the backslash for JSON
                        result.append('\\\\')
                        i += 1
                else:
                    result.append(s[i])
                    i += 1
            return ''.join(result)
        
        json_str = fix_backslashes(json_str)
        data = json.loads(json_str)
        
        # Check if atomic
        if data.get("is_atomic", False):
            return ExpandStepResponse(
                sub_steps=[],
                can_expand=False,
                stop_reason="atomic",
                message="This step is already at its most fundamental level."
            )
        
        # Build sub-steps with IDs and labels
        sub_steps = []
        for item in data.get("sub_steps", []):
            order = item.get("order", len(sub_steps) + 1)
            sub_step = SubStep(
                id=str(uuid.uuid4()),
                label=f"{request.step_path}.{order}",
                order=order,
                title=item.get("title", ""),
                explanation=item.get("explanation", ""),
                math_expression=item.get("math_expression"),
                can_expand=item.get("can_expand", True) and (request.current_depth + 1 < 3)
            )
            sub_steps.append(sub_step)
        
        # Simple loop detection: check for very similar titles to parent
        parent_title_lower = request.step_title.lower()
        filtered_steps = []
        for s in sub_steps:
            if s.title.lower() == parent_title_lower:
                logger.warning(f"[ExpandStep] Loop detected: sub-step title matches parent")
                continue
            filtered_steps.append(s)
        
        if len(filtered_steps) == 0:
            return ExpandStepResponse(
                sub_steps=[],
                can_expand=False,
                stop_reason="loop_risk",
                message="Cannot break down further without repeating."
            )
        
        return ExpandStepResponse(
            sub_steps=filtered_steps,
            can_expand=True
        )
        
    except Exception as e:
        logger.error(f"[ExpandStep] Error: {e}", exc_info=True)
        return ExpandStepResponse(
            sub_steps=[],
            can_expand=False,
            stop_reason="insufficient_context",
            message=f"Could not generate sub-steps: {str(e)[:100]}"
        )


# ============================================================================
# PRACTICE PROBLEMS ENDPOINT
# ============================================================================

class PracticeRequest(BaseModel):
    """Request for generating practice problems"""
    topic: str = Field(..., description="The topic to generate practice problems for")
    original_problem: str = Field(..., description="The original problem for context")
    num_questions: int = Field(default=3, ge=1, le=5)
    user_id: str = Field(default="anonymous", description="User ID for profile-aware generation")


class PracticeQuestion(BaseModel):
    """A single practice question"""
    question: str
    options: list[str]  # 4 multiple choice options
    correct_index: int  # 0-3 index of correct answer
    explanation: str


class PracticeResponse(BaseModel):
    """Response with practice problems"""
    topic: str
    questions: list[PracticeQuestion]


@app.post("/v1/practice", response_model=PracticeResponse)
async def generate_practice(request: PracticeRequest):
    """Generate practice problems on-demand, adapted to student's profile."""
    logger.info(f"[Practice] Generating {request.num_questions} questions for: {request.topic}")
    
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    import json
    import re
    
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
        temperature=0.7  # Slight variation for diverse questions
    )
    
    # Get student profile for adaptive question generation
    profile_context = ""
    if is_backboard_available():
        try:
            from backboard_client import get_backboard_service
            backboard = await get_backboard_service()
            thread_id = await backboard.get_or_create_thread(request.user_id or "anonymous")
            profile = await backboard.get_student_profile(thread_id, request.topic)
            
            if profile.has_history:
                if profile.weak_concepts:
                    profile_context += f"\nFOCUS ON WEAKNESS: Include extra questions testing: {', '.join(profile.weak_concepts[:3])}"
                    profile_context += "\nMake these questions simpler and more foundational to build confidence."
                if profile.strong_concepts:
                    profile_context += f"\nSKIP BASICS ON: {', '.join(profile.strong_concepts[:3])} (student has mastered these)"
                    profile_context += "\nMake questions on these topics more challenging."
            logger.info(f"[Practice] Using profile: {len(profile.weak_concepts)} weaknesses, {len(profile.strong_concepts)} strengths")
        except Exception as e:
            logger.warning(f"[Practice] Could not get profile: {e}")
    
    try:
        prompt = f"""Generate {request.num_questions} multiple choice practice questions on the topic: {request.topic}

Original problem for context: {request.original_problem}
{profile_context}

Create questions that test the same concept but with different numbers/scenarios.
Each question should have 4 options (A, B, C, D) with only one correct answer.

Respond in this EXACT JSON format:
{{
  "questions": [
    {{
      "question": "The question text with math in LaTeX like $x^2$",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_index": 0,
      "explanation": "Brief explanation of why this is correct"
    }}
  ]
}}

Make the questions progressively harder. Use LaTeX for math expressions."""

        result = await llm.ainvoke([HumanMessage(content=prompt)])
        response_text = result.content
        
        # Parse JSON from response
        json_match = re.search(r'\{[\s\S]*"questions"[\s\S]*\}', response_text)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError("Could not parse questions JSON")
        
        questions = [
            PracticeQuestion(
                question=q["question"],
                options=q["options"],
                correct_index=q["correct_index"],
                explanation=q["explanation"]
            )
            for q in data["questions"]
        ]
        
        logger.info(f"[Practice] Generated {len(questions)} questions")
        
        return PracticeResponse(
            topic=request.topic,
            questions=questions
        )
        
    except Exception as e:
        logger.error(f"[Practice] Error: {e}", exc_info=True)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Failed to generate practice problems: {str(e)}"
        )


# ============================================================================
# YOUTUBE RESOURCES ENDPOINT
# ============================================================================

@app.post("/v1/resources", response_model=ResourcesResponse)
async def get_youtube_resources(request: ResourcesRequest):
    """
    Get YouTube video resources for a math problem.
    Uses caching to avoid re-fetching for the same problem+offset.
    """
    logger.info(f"[Resources] problem_id={request.problem_id}, offset={request.offset}")
    
    # 1. Check cache first
    cache = get_video_cache()
    if cache:
        cached_videos = await cache.get(request.problem_id, request.offset)
        if cached_videos:
            logger.info(f"[Resources] Cache HIT, returning {len(cached_videos)} videos")
            return ResourcesResponse(
                videos=[VideoResource(**v) for v in cached_videos],
                has_more=len(cached_videos) >= 3,
                total_fetched=request.offset + len(cached_videos)
            )
    
    # 2. Get student profile for Gap-Fill video queries
    student_weakness = None
    if is_backboard_available() and hasattr(request, 'user_id') and request.user_id:
        try:
            from backboard_client import get_backboard_service
            backboard = await get_backboard_service()
            thread_id = await backboard.get_or_create_thread(request.user_id)
            profile = await backboard.get_student_profile(thread_id, request.topic)
            
            if profile.weak_concepts:
                # Use the most relevant weakness for Gap-Fill queries
                student_weakness = profile.weak_concepts[0]
                logger.info(f"[Resources] Gap-Fill targeting weakness: {student_weakness}")
        except Exception as e:
            logger.warning(f"[Resources] Could not get profile for Gap-Fill: {e}")
    
    # 3. Run the YouTube resources graph
    try:
        graph = get_youtube_graph()
        
        initial_state: YouTubeResourcesState = {
            "problem_text": request.problem_text,
            "topic": request.topic,
            "offset": request.offset,
            "student_weakness": student_weakness,  # Gap-Fill query targeting
            "key_concepts": [],
            "search_queries": [],
            "raw_videos": [],
            "annotated_videos": []
        }
        
        result = await graph.ainvoke(initial_state)
        annotated_videos = result.get("annotated_videos", [])
        
        # 4. Cache the results
        if cache and annotated_videos:
            await cache.set(request.problem_id, request.offset, annotated_videos)
        
        # 4. Return response
        videos = [
            VideoResource(
                video_id=v["video_id"],
                title=v["title"],
                thumbnail_url=v["thumbnail_url"],
                youtube_url=v["youtube_url"],
                relevance_summary=v["relevance_summary"]
            )
            for v in annotated_videos
        ]
        
        logger.info(f"[Resources] Returning {len(videos)} videos")
        
        return ResourcesResponse(
            videos=videos,
            has_more=len(videos) >= 3,
            total_fetched=request.offset + len(videos)
        )
        
    except Exception as e:
        logger.error(f"[Resources] Error: {e}", exc_info=True)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Failed to fetch video resources: {str(e)}"
        )


# ============================================================================
# STUDENT PROFILING ENDPOINTS (Backboard Diagnostic Logging)
# ============================================================================

@app.post("/v1/log_breakdown", status_code=status.HTTP_200_OK)
async def log_breakdown(request: LogBreakdownRequest):
    """
    Log when a student clicks 'breakdown' on a step.
    This shadow-saves the interaction to Backboard for profiling.
    """
    logger.info(f"[LogBreakdown] user={request.user_id}, concept={request.concept}")
    
    if not is_backboard_available():
        return {"status": "skipped", "message": "Backboard not configured"}
    
    try:
        backboard = await get_backboard_service()
        thread_id = await backboard.get_or_create_thread(request.user_id)
        
        await backboard.log_struggle(
            thread_id=thread_id,
            step_title=request.step_title,
            concept=request.concept,
            context=request.context
        )
        
        return {"status": "logged", "concept": request.concept}
        
    except Exception as e:
        logger.error(f"[LogBreakdown] Error: {e}", exc_info=True)
        # Non-critical - don't fail the request
        return {"status": "error", "message": str(e)[:100]}


@app.post("/v1/log_quiz_result", status_code=status.HTTP_200_OK)
async def log_quiz_result(request: LogQuizResultRequest):
    """
    Log quiz/practice results for student profiling.
    Tracks mastery and struggle patterns.
    """
    logger.info(f"[LogQuizResult] user={request.user_id}, concept={request.concept}, correct={request.correct}")
    
    if not is_backboard_available():
        return {"status": "skipped", "message": "Backboard not configured"}
    
    try:
        backboard = await get_backboard_service()
        thread_id = await backboard.get_or_create_thread(request.user_id)
        
        await backboard.log_quiz_result(
            thread_id=thread_id,
            concept=request.concept,
            correct=request.correct,
            question_summary=request.question_summary
        )
        
        return {"status": "logged", "concept": request.concept, "correct": request.correct}
        
    except Exception as e:
        logger.error(f"[LogQuizResult] Error: {e}", exc_info=True)
        # Non-critical - don't fail the request
        return {"status": "error", "message": str(e)[:100]}


@app.post("/v1/similar_problems", response_model=SimilarProblemsResponse)
async def find_similar_problems_endpoint(request: SimilarProblemsRequest):
    """
    Find semantically similar problems from Backboard memory.
    Used for smart grouping suggestions in history view.
    """
    logger.info(f"[SimilarProblems] user={request.user_id}, topic={request.topic}")
    
    if not is_backboard_available():
        return SimilarProblemsResponse(similar_problems=[], suggested_folder_name=None)
    
    try:
        backboard = await get_backboard_service()
        thread_id = await backboard.get_or_create_thread(request.user_id)
        
        similar = await backboard.find_similar_problems(
            thread_id=thread_id,
            query_topic=request.topic,
            query_problem=request.problem_text
        )
        
        # Convert to response model
        similar_problems = [
            SimilarProblem(topic=p["topic"], similarity=p["similarity"])
            for p in similar
        ]
        
        # Generate suggested folder name if we found similar problems
        suggested_name = None
        if similar_problems:
            # Use most common topic category
            base_topic = request.topic.split(" - ")[1] if " - " in request.topic else request.topic
            suggested_name = f"{base_topic} Practice"
        
        return SimilarProblemsResponse(
            similar_problems=similar_problems,
            suggested_folder_name=suggested_name
        )
        
    except Exception as e:
        logger.error(f"[SimilarProblems] Error: {e}", exc_info=True)
        return SimilarProblemsResponse(similar_problems=[], suggested_folder_name=None)


# ============================================================================
# SEMANTIC FOLDER MANAGEMENT
# ============================================================================

@app.post("/v1/sync_folder", status_code=status.HTTP_200_OK)
async def sync_folder(request: SyncFolderRequest):
    """
    Sync folder definition to Backboard memory.
    Called when folder is created or renamed to keep Folder Map updated.
    """
    logger.info(f"[SyncFolder] user={request.user_id}, folder={request.folder_id} -> {request.folder_name}")
    
    if not is_backboard_available():
        return {"status": "skipped", "message": "Backboard not configured"}
    
    try:
        backboard = await get_backboard_service()
        thread_id = await backboard.get_or_create_thread(request.user_id)
        
        await backboard.save_folder_definition(
            thread_id=thread_id,
            folder_id=request.folder_id,
            folder_name=request.folder_name
        )
        
        return {"status": "synced", "folder_id": request.folder_id}
        
    except Exception as e:
        logger.error(f"[SyncFolder] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)[:100]}


@app.post("/v1/suggest_folder", response_model=FolderSuggestionResponse)
async def suggest_folder(request: SuggestFolderRequest):
    """
    Get semantic folder suggestion for a problem.
    Uses Backboard memory search with 0.85 similarity threshold.
    """
    logger.info(f"[SuggestFolder] user={request.user_id}, topic={request.topic}")
    
    if not is_backboard_available():
        return FolderSuggestionResponse(action="no_suggestion")
    
    try:
        backboard = await get_backboard_service()
        thread_id = await backboard.get_or_create_thread(request.user_id)
        
        suggestion = await backboard.find_folder_for_problem(
            thread_id=thread_id,
            problem_text=request.problem_text,
            topic=request.topic
        )
        
        return FolderSuggestionResponse(
            action=suggestion.action,
            folder_id=suggestion.folder_id,
            folder_name=suggestion.folder_name,
            similarity_score=suggestion.similarity_score,
            similar_unfiled=suggestion.similar_unfiled,
            alternate_folder=suggestion.alternate_folder
        )
        
    except Exception as e:
        logger.error(f"[SuggestFolder] Error: {e}", exc_info=True)
        return FolderSuggestionResponse(action="no_suggestion")


@app.post("/v1/delete_folder", status_code=status.HTTP_200_OK)
async def delete_folder_memory(request: DeleteFolderRequest):
    """
    Delete folder definition from Backboard memory.
    Called when folder is deleted to prevent stale suggestions.
    """
    logger.info(f"[DeleteFolder] user={request.user_id}, folder={request.folder_id}")
    
    if not is_backboard_available():
        return {"status": "skipped", "message": "Backboard not configured"}
    
    try:
        backboard = await get_backboard_service()
        thread_id = await backboard.get_or_create_thread(request.user_id)
        
        await backboard.delete_folder_definition(
            thread_id=thread_id,
            folder_id=request.folder_id
        )
        
        return {"status": "deleted", "folder_id": request.folder_id}
        
    except Exception as e:
        logger.error(f"[DeleteFolder] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)[:100]}


@app.post("/v1/delete_problem", status_code=status.HTTP_200_OK)
async def delete_problem_memory(request: DeleteProblemRequest):
    """
    Delete problem from Backboard memory.
    Called when problem is deleted to exclude from similarity searches.
    """
    logger.info(f"[DeleteProblem] user={request.user_id}, session={request.session_id}")
    
    if not is_backboard_available():
        return {"status": "skipped", "message": "Backboard not configured"}
    
    try:
        backboard = await get_backboard_service()
        thread_id = await backboard.get_or_create_thread(request.user_id)
        
        await backboard.delete_problem_memory(
            thread_id=thread_id,
            session_id=request.session_id
        )
        
        return {"status": "deleted", "session_id": request.session_id}
        
    except Exception as e:
        logger.error(f"[DeleteProblem] Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)[:100]}

# ============================================================================
# SUPABASE SESSION HISTORY ENDPOINTS
# ============================================================================

class SessionListItem(BaseModel):
    """Lightweight session preview for the sidebar."""
    id: str
    title: Optional[str] = None
    topic: Optional[str] = None
    updated_at: Optional[str] = None


class SessionMessagesResponse(BaseModel):
    """Full message list for a session."""
    session_id: str
    messages: list[dict]


class FeedbackRequest(BaseModel):
    """User feedback on a session or message."""
    user_id: str = Field(...)
    rating: int = Field(..., ge=1, le=5)
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    comment: str = ""


@app.get("/v1/sessions", response_model=list[SessionListItem])
async def list_sessions(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    include_archived: bool = False,
):
    """Get paginated session list for a user."""
    sessions = await supabase_client.get_user_sessions(
        user_id=user_id,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    return [SessionListItem(**s) for s in sessions]


@app.get("/v1/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(session_id: str, user_id: str):
    """Get all messages for a session."""
    messages = await supabase_client.get_session_messages(
        session_id=session_id,
        user_id=user_id,
    )
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@app.post("/v1/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(request: FeedbackRequest):
    """Submit user feedback on a session or message."""
    result = await supabase_client.save_feedback(
        user_id=request.user_id,
        rating=request.rating,
        session_id=request.session_id,
        message_id=request.message_id,
        comment=request.comment,
    )
    return {"status": "saved", "feedback_id": result.get("id")}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.backend_port, reload=True)
