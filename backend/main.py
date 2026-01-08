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

@app.post("/v1/explain_step")
async def explain_step(request: ExplainStepRequest):
    logger.info(f"[ExplainStep] Topic: {request.topic}")
    return {
        "explanation": f"Explanation for {request.step_text}...",
        "topic": request.topic
    }


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

