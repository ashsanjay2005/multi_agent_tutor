"""
FastAPI Application for AI Math Tutor Backend
"""

import logging
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

# ============================================================================
# LIFECYCLE & APP
# ============================================================================

app_graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_graph
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
    
    # Initialize graph
    try:
        app_graph = await get_graph()
        logger.info("LangGraph workflow initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize graph: {e}")
        raise
    
    yield
    
    # Cleanup
    logger.info("Shutting down...")
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
    global app_graph
    if app_graph is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Graph not initialized")
    
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
        initial_state: GraphState = {
            "input_type": request.type,
            "input_content": request.content,
            "user_id": request.user_id,
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
            "final_response_html": None,
            "requires_user_action": False
        }
        
        config = {"configurable": {"thread_id": thread_id}}
        result = await app_graph.ainvoke(initial_state, config)
        
        response_status = "completed"
        if result["requires_user_action"]:
            response_status = "requires_disambiguation" if result.get("candidate_topics") else "requires_clarification"
        
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
    global app_graph
    if app_graph is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Graph not initialized")
    
    try:
        config = {"configurable": {"thread_id": request.thread_id}}
        state = await app_graph.aget_state(config)
        
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
        await app_graph.aupdate_state(config, updated_state)
        # Invoke with None input to resume execution from current state
        final_state = await app_graph.ainvoke(None, config)
        
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
        # Replace single backslashes that aren't already escaped or valid JSON escapes
        # Valid JSON escapes: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
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
    """Generate practice problems on-demand (only when user clicks the button)."""
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.backend_port, reload=True)

