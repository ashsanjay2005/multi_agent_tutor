"""
FastAPI Application for AI Math Tutor Backend
"""

import logging
import asyncio
import uuid
from typing import Literal, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import base64

from config import settings
from graph import (
    get_graph,
    teaching_architect_node,
    step_solver_node,
    parallel_teaching_nodes,
    assembler_node,
)
from state import GraphState
from rate_limiter import (
    init_rate_limiter, 
    close_rate_limiter, 
    get_rate_limiter,
    RateLimitConfig
)
from cache import init_video_cache, get_video_cache
from youtube_resources_graph import get_youtube_graph, YouTubeResourcesState
from auth_context import (
    AuthContext,
    create_anonymous_token,
    require_auth_context,
    require_cloud_user,
    require_matching_user,
)
import supabase_client

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

MAX_TEXT_CONTENT_CHARS = 20_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class AnalyzeRequest(BaseModel):
    type: Literal["text", "image"] = Field(...)
    content: str = Field(..., min_length=1)
    user_id: Optional[str] = None
    thread_id: Optional[str] = Field(None)
    
    @validator("content")
    def validate_content(cls, v, values):
        if values.get("type") == "image":
            try:
                decoded = base64.b64decode(v, validate=True)
            except Exception:
                raise ValueError("Invalid base64 encoding")
            if len(decoded) > MAX_IMAGE_BYTES:
                raise ValueError("Image too large. Maximum size is 10MB.")
        elif len(v) > MAX_TEXT_CONTENT_CHARS:
            raise ValueError("Text input too large. Maximum length is 20,000 characters.")
        return v


class AnonymousSessionResponse(BaseModel):
    user_id: str
    access_token: str
    token_type: str = "bearer"
    expires_at: int

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
    final_graph_url: Optional[str] = None  # Final complete graph for graphing problems
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

@app.post("/v1/anonymous_session", response_model=AnonymousSessionResponse)
async def create_anonymous_session():
    """Issue a backend-signed anonymous identity for local extension mode."""
    user_id, token, expires_at = create_anonymous_token()
    return AnonymousSessionResponse(
        user_id=user_id,
        access_token=token,
        expires_at=expires_at,
    )

@app.get("/v1/quota")
async def get_quota(
    user_id: Optional[str] = None,
    auth: AuthContext = Depends(require_auth_context),
):
    """Get current rate limit quota status for a user."""
    resolved_user_id = require_matching_user(auth, user_id)
    try:
        limiter = await get_rate_limiter()
        user_tier = "free"  # In production, look up from DB
        quota = await limiter.get_quota_status(resolved_user_id, tier=user_tier)
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
async def analyze_problem(
    request: AnalyzeRequest,
    auth: AuthContext = Depends(require_auth_context),
):
    global app_graph, app_graph_ckpt, _db_pool
    user_id = require_matching_user(auth, request.user_id)
    
    # Lazy init: if graph failed during startup, retry now
    if app_graph is None:
        try:
            logger.info("Graph not initialized — attempting lazy initialization...")
            _db_pool, app_graph_ckpt, app_graph = await get_graph()
            logger.info("Lazy graph initialization succeeded!")
        except Exception as e:
            logger.error(f"Lazy graph initialization failed: {e}")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Database unavailable: {e}")
    if app_graph_ckpt is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Checkpointed graph unavailable")
    
    # Check rate limit
    try:
        limiter = await get_rate_limiter()
        # Default to free tier - in production, you'd look up user tier from DB
        user_tier = "free"  
        allowed, remaining, reset_in = await limiter.check_rate_limit(
            user_id,
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
        # Offload images to Supabase Storage (reduces checkpoint blob size ~80%)
        content_for_state = request.content
        if request.type == "image":
            try:
                image_url = await supabase_client.upload_image(
                    request.content, thread_id, user_id=user_id
                )
                content_for_state = image_url
                logger.info(f"[Analyze] Image offloaded to storage: {image_url[:80]}...")
            except Exception as e:
                logger.warning(f"[Analyze] Image upload failed, using base64 fallback: {e}")
        
        initial_state: GraphState = {
            "input_type": request.type,
            "input_content": content_for_state,
            "user_id": user_id,
            "thread_id": thread_id,
            "topic": None,
            "confidence_score": 0.0,
            "detected_ambiguity": False,
            "candidate_topics": [],
            "teaching_plan": None,
            "worked_example": None,
            "practice_problem": None,
            "video_url": None,
            "solution_steps": None,
            "visualization_steps": None,
            "visualization_fallback": False,
            "is_graphing_problem": False,
            "step_images": None,
            "final_graph_url": None,
            "final_response_html": None,
            "requires_user_action": False
        }
        
        # Use checkpointed graph so human-in-the-loop disambiguation can resume.
        config = {"configurable": {"thread_id": thread_id}}
        result = await app_graph_ckpt.ainvoke(initial_state, config)
        
        response_status = "completed"
        if result["requires_user_action"]:
            response_status = "requires_disambiguation" if result.get("candidate_topics") else "requires_clarification"
        
        # Persist session + messages to Supabase only for verified cloud users.
        if auth.is_cloud:
            try:
                session = await supabase_client.create_session(
                    user_id=user_id,
                    title=result.get("input_content", "")[:100],
                    topic=result.get("topic", ""),
                    model=settings.text_model,
                    langgraph_thread_id=thread_id,
                )
                session_id = session["id"]

                # Save user message
                await supabase_client.save_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="user",
                    content_text=request.content[:500] if request.type == "text" else "[image]",
                )

                # Save assistant response
                await supabase_client.save_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content_text=result.get("worked_example", "")[:500],
                    content_json={
                        "solution_steps": result.get("solution_steps"),
                        "final_answer": result.get("worked_example"),
                        "final_graph_url": result.get("final_graph_url"),
                        "topic": result.get("topic"),
                        "confidence": result.get("confidence_score"),
                    },
                )
                # Save to saved_problems table
                await supabase_client.save_problem(
                    user_id=user_id,
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
                        "final_graph_url": result.get("final_graph_url"),
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
            final_graph_url=result.get("final_graph_url"),
            extracted_problem=result.get("input_content")  # Contains extracted text for images
        )
    except Exception as e:
        logger.error(f"[Analyze] Error: {e}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))

@app.post("/v1/resume", response_model=AnalyzeResponse)
async def resume_workflow(
    request: ResumeRequest,
    auth: AuthContext = Depends(require_auth_context),
):
    global app_graph_ckpt
    if app_graph_ckpt is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Graph not initialized")
    
    try:
        config = {"configurable": {"thread_id": request.thread_id}}
        state = await app_graph_ckpt.aget_state(config)
        
        if not state:
             raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")

        base_state = getattr(state, "values", state)
        if not base_state:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
        if base_state.get("user_id") != auth.user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Thread does not belong to user")

        # Resume by updating topic and proceeding
        updated_state = {
            **base_state,
            "topic": request.selected_topic,
            "confidence_score": 1.0,
            "detected_ambiguity": False,
            "candidate_topics": [],
            "requires_user_action": False,
        }
        
        # The disambiguation node is terminal. Continue with the teaching
        # pipeline explicitly after the user selects the intended topic.
        teaching_state = await teaching_architect_node(updated_state)
        solved_state = await step_solver_node(teaching_state)
        parallel_state = await parallel_teaching_nodes(solved_state)
        final_state = await assembler_node(parallel_state)
        await app_graph_ckpt.aupdate_state(config, final_state)
        
        return AnalyzeResponse(
            thread_id=request.thread_id,
            status="completed",
            requires_user_action=False,
            final_response_html=final_state.get("final_response_html"),
            topic=final_state.get("topic"),
            confidence_score=final_state.get("confidence_score"),
            solution_steps=final_state.get("solution_steps"),
            final_answer=final_state.get("worked_example"),
            final_graph_url=final_state.get("final_graph_url"),
            extracted_problem=final_state.get("input_content"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Resume] Error: {e}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))

@app.post("/v1/expand_step", response_model=ExpandStepResponse)
async def expand_step(
    request: ExpandStepRequest,
    auth: AuthContext = Depends(require_auth_context),
):
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
    user_id: Optional[str] = Field(None, description="Deprecated; derived from Authorization")


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
async def generate_practice(
    request: PracticeRequest,
    auth: AuthContext = Depends(require_auth_context),
):
    """Generate practice problems on-demand."""
    require_matching_user(auth, request.user_id)
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
    
    try:
        prompt = f"""Generate {request.num_questions} multiple choice practice questions on the topic: {request.topic}

Original problem for context: {request.original_problem}

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
async def get_youtube_resources(
    request: ResourcesRequest,
    auth: AuthContext = Depends(require_auth_context),
):
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
    
    # 2. Keep the resources query focused on the current problem/topic.
    student_weakness = None
    
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
    user_id: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    comment: str = ""


@app.get("/v1/sessions", response_model=list[SessionListItem])
async def list_sessions(
    user_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    include_archived: bool = False,
    auth: AuthContext = Depends(require_auth_context),
):
    """Get paginated session list for a user."""
    resolved_user_id = require_matching_user(auth, user_id)
    require_cloud_user(auth)
    sessions = await supabase_client.get_user_sessions(
        user_id=resolved_user_id,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    return [SessionListItem(**s) for s in sessions]


@app.get("/v1/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(
    session_id: str,
    user_id: Optional[str] = None,
    auth: AuthContext = Depends(require_auth_context),
):
    """Get all messages for a session."""
    resolved_user_id = require_matching_user(auth, user_id)
    require_cloud_user(auth)
    messages = await supabase_client.get_session_messages(
        session_id=session_id,
        user_id=resolved_user_id,
    )
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@app.post("/v1/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    request: FeedbackRequest,
    auth: AuthContext = Depends(require_auth_context),
):
    """Submit user feedback on a session or message."""
    user_id = require_matching_user(auth, request.user_id)
    require_cloud_user(auth)
    result = await supabase_client.save_feedback(
        user_id=user_id,
        rating=request.rating,
        session_id=request.session_id,
        message_id=request.message_id,
        comment=request.comment,
    )
    return {"status": "saved", "feedback_id": result.get("id")}


# ============================================================================
# GOOGLE DOCS CHEAT SHEET GENERATION
# ============================================================================

class CheatSheetProblem(BaseModel):
    """A problem sent from the frontend for cheat sheet context."""
    problem: str
    topic: str
    final_answer: str = ""


class GenerateCheatSheetRequest(BaseModel):
    """Request to generate a cheat sheet and write it to Google Docs."""
    user_id: Optional[str] = Field(None, description="Deprecated; derived from Authorization")
    folder_name: str = Field(..., description="Folder display name")
    problems: list[CheatSheetProblem] = Field(..., description="Problems from the folder")
    google_access_token: str = Field(..., description="OAuth access token for Google Docs API")


class GenerateCheatSheetResponse(BaseModel):
    """Response with the created Google Doc URL."""
    doc_url: str
    doc_title: str


def _markdown_to_docs_requests(markdown_text: str) -> list[dict]:
    """
    Convert Markdown text into Google Docs API batchUpdate requests.

    Supports:
    - # H1, ## H2, ### H3 headings → HEADING_1/2/3
    - **bold text** → updateTextStyle bold
    - - bullet items → BULLET_DISC_CIRCLE_SQUARE list
    - Regular paragraphs → NORMAL_TEXT
    - LaTeX $...$ wrapped in bold for visibility

    Strategy: Build a list of "segments" first, then convert to insertText +
    updateParagraphStyle + updateTextStyle requests. Google Docs insertText
    works with a cursor index; we insert at index 1 (after the implicit
    empty paragraph) and build forward.
    """
    import re

    lines = markdown_text.strip().split("\n")

    # Each segment: { text, heading_level (0=normal), is_bullet, bold_ranges }
    segments = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            segments.append({"text": "\n", "heading_level": 0, "is_bullet": False, "bold_ranges": []})
            continue

        heading_level = 0
        is_bullet = False

        # Detect headings
        heading_match = re.match(r'^(#{1,3})\s+(.*)', stripped)
        if heading_match:
            heading_level = len(heading_match.group(1))
            stripped = heading_match.group(2)

        # Detect bullets
        if stripped.startswith("- ") or stripped.startswith("• "):
            is_bullet = True
            stripped = stripped[2:]

        # Find bold ranges **text**
        bold_ranges = []
        clean_text = ""
        last_end = 0
        for m in re.finditer(r'\*\*(.*?)\*\*', stripped):
            clean_text += stripped[last_end:m.start()]
            bold_start = len(clean_text)
            clean_text += m.group(1)
            bold_end = len(clean_text)
            bold_ranges.append((bold_start, bold_end))
            last_end = m.end()
        clean_text += stripped[last_end:]

        # Replace LaTeX $...$ with styled markers
        clean_text = re.sub(r'\$(.+?)\$', r'[\1]', clean_text)

        segments.append({
            "text": clean_text + "\n",
            "heading_level": heading_level,
            "is_bullet": is_bullet,
            "bold_ranges": bold_ranges,
        })

    # Build requests: insert all text first, then apply styles
    # We insert at index 1 (start of document body)
    requests = []
    current_index = 1

    # First pass: insert all text
    full_text = ""
    for seg in segments:
        full_text += seg["text"]

    if not full_text.strip():
        return []

    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": full_text,
        }
    })

    # Second pass: apply paragraph styles and text formatting
    current_index = 1
    for seg in segments:
        text_len = len(seg["text"])
        if text_len == 0:
            continue

        # Apply heading style
        if seg["heading_level"] > 0:
            heading_map = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3"}
            requests.append({
                "updateParagraphStyle": {
                    "range": {
                        "startIndex": current_index,
                        "endIndex": current_index + text_len,
                    },
                    "paragraphStyle": {
                        "namedStyleType": heading_map.get(seg["heading_level"], "HEADING_3"),
                    },
                    "fields": "namedStyleType",
                }
            })

        # Apply bullet list style
        if seg["is_bullet"]:
            requests.append({
                "createParagraphBullets": {
                    "range": {
                        "startIndex": current_index,
                        "endIndex": current_index + text_len,
                    },
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })

        # Apply bold formatting
        for bold_start, bold_end in seg["bold_ranges"]:
            abs_start = current_index + bold_start
            abs_end = current_index + bold_end
            if abs_start < abs_end:
                requests.append({
                    "updateTextStyle": {
                        "range": {
                            "startIndex": abs_start,
                            "endIndex": abs_end,
                        },
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                })

        current_index += text_len

    return requests


@app.post("/v1/generate_cheatsheet", response_model=GenerateCheatSheetResponse)
async def generate_cheatsheet(
    request: GenerateCheatSheetRequest,
    auth: AuthContext = Depends(require_auth_context),
):
    """
    Generate a cheat sheet from folder data and write it to Google Docs.

    Flow:
    1. Combine folder problem data sent from frontend
    2. Generate cheat sheet content via LLM (Gemini)
    3. Parse Markdown → Google Docs batchUpdate requests
    4. Create new Google Doc and apply formatting
    5. Return the document URL
    """
    import httpx
    import json
    import re
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage

    user_id = require_matching_user(auth, request.user_id)
    logger.info(f"[CheatSheet] Generating for folder '{request.folder_name}', "
                f"user={user_id}, problems={len(request.problems)}")

    if not request.problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No problems provided")

    # ------------------------------------------------------------------
    # 1. Build problem summary for the LLM
    # ------------------------------------------------------------------
    problems_text = ""
    for i, p in enumerate(request.problems[:20], 1):  # Cap at 20 problems
        problems_text += f"\n{i}. **Topic**: {p.topic}\n"
        problems_text += f"   **Problem**: {p.problem[:300]}\n"
        if p.final_answer:
            problems_text += f"   **Answer**: {p.final_answer[:200]}\n"

    # ------------------------------------------------------------------
    # 3. Generate cheat sheet content via LLM
    # ------------------------------------------------------------------
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
        temperature=0.4,
    )

    prompt = f"""You are creating a **study cheat sheet** for a student's "{request.folder_name}" folder.

PROBLEMS IN THIS FOLDER:
{problems_text}

---

Create a well-organized cheat sheet in **Markdown format** with the following structure:

# {request.folder_name} — Cheat Sheet

## Key Concepts & Definitions
- Define the most important concepts covered in these problems
- Include precise mathematical definitions where relevant

## Essential Formulas & Theorems
- List all important formulas cleanly using readable Unicode text (e.g., y = mx + b)
- Do NOT use raw LaTeX commands; Google Docs cannot natively render them.
- Include when and how to apply each formula

## Problem-Solving Strategies
- Step-by-step strategies for common problem types
- Decision trees for choosing the right approach

## Common Mistakes to Avoid
- Based on recurring patterns and common errors in the provided problems
- Include tips for avoiding these pitfalls

## Quick Reference Examples
- One worked example for each major concept
- Keep examples concise but complete

## Study Tips
- Specific recommendations based on the folder's topics and problem types
- Priority areas for further practice

RULES:
1. Use Markdown headings (## for sections, ### for subsections)
2. Use **bold** for key terms
3. Use bullet points for lists
4. VERY IMPORTANT: Do NOT use raw LaTeX (like \\lambda, \\frac, or \\begin{{bmatrix}}). Instead, use plain text with Unicode math symbols (e.g., λ, x², 1/2). Format matrices simply like [[1, 2], [3, 4]].
5. Keep it concise — this is a CHEAT SHEET, not a textbook
6. Focus on the specific topics from the problems above
7. Make it immediately useful for exam preparation"""

    try:
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        cheatsheet_markdown = result.content
        logger.info(f"[CheatSheet] Generated {len(cheatsheet_markdown)} chars of content")
    except Exception as e:
        logger.error(f"[CheatSheet] LLM generation failed: {e}", exc_info=True)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Failed to generate cheat sheet content: {str(e)[:100]}"
        )

    # ------------------------------------------------------------------
    # 4. Create Google Doc and write content via batchUpdate
    # ------------------------------------------------------------------
    doc_title = f"{request.folder_name} — Cheat Sheet"
    headers = {
        "Authorization": f"Bearer {request.google_access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step A: Create empty document
        try:
            create_resp = await client.post(
                "https://docs.googleapis.com/v1/documents",
                headers=headers,
                json={"title": doc_title},
            )
            if create_resp.status_code == 401:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    "Google Docs access token expired or invalid. Please re-authorize."
                )
            if create_resp.status_code != 200:
                logger.error(f"[CheatSheet] Google Docs create failed: {create_resp.text}")
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"Google Docs API error: {create_resp.status_code}"
                )

            doc_data = create_resp.json()
            doc_id = doc_data["documentId"]
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            logger.info(f"[CheatSheet] Created document: {doc_id}")
        except httpx.HTTPError as e:
            logger.error(f"[CheatSheet] Google Docs create request failed: {e}")
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Failed to connect to Google Docs API"
            )

        # Step B: Convert Markdown to batchUpdate requests
        batch_requests = _markdown_to_docs_requests(cheatsheet_markdown)

        if batch_requests:
            try:
                update_resp = await client.post(
                    f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
                    headers=headers,
                    json={"requests": batch_requests},
                )
                if update_resp.status_code != 200:
                    logger.error(f"[CheatSheet] batchUpdate failed: {update_resp.text}")
                    # Doc was created but formatting failed — still return URL
                    logger.warning("[CheatSheet] Returning doc URL despite formatting error")
                else:
                    logger.info(f"[CheatSheet] Applied {len(batch_requests)} formatting requests")
            except httpx.HTTPError as e:
                logger.warning(f"[CheatSheet] batchUpdate request failed: {e}")
                # Doc was created, formatting just didn't apply

    logger.info(f"[CheatSheet] Done! Doc URL: {doc_url}")
    return GenerateCheatSheetResponse(doc_url=doc_url, doc_title=doc_title)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.backend_port, reload=True)
