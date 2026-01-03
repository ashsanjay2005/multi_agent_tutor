"""
FastAPI Application for AI Math Tutor Backend
"""

import logging
import uuid
from typing import Literal, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import base64

from config import settings
from graph import get_graph
from state import GraphState

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
    try:
        app_graph = await get_graph()
        logger.info("LangGraph workflow initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize graph: {e}")
        raise
    yield
    logger.info("Shutting down...")

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

@app.post("/v1/analyze", response_model=AnalyzeResponse)
async def analyze_problem(request: AnalyzeRequest):
    global app_graph
    if app_graph is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Graph not initialized")
    
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
            final_answer=result.get("worked_example")
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.backend_port, reload=True)
