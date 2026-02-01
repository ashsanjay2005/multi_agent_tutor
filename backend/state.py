"""
Graph State Definition for AI Math Tutor

This module defines the GraphState TypedDict that flows through the LangGraph workflow.
All nodes must accept and return updates to this structure.
"""

from typing import TypedDict, List, Optional, Literal


class GraphState(TypedDict):
    """
    The state object that flows through the entire LangGraph workflow.
    
    This state is persisted in PostgreSQL via the LangGraph checkpointer,
    allowing for stateless server scaling and human-in-the-loop interrupts.
    """
    
    # --- Input ---
    input_type: Literal["text", "image"]
    input_content: str  # Text string or Base64 image
    user_id: str
    thread_id: str
    
    # --- Classification ---
    topic: Optional[str]
    confidence_score: float  # 0.0 to 1.0
    detected_ambiguity: bool
    candidate_topics: List[str]  # Used for Disambiguation UI
    
    # --- Teaching Content (Populated by Parallel Agents) ---
    teaching_plan: Optional[str]
    worked_example: Optional[str]  # Markdown/LaTeX
    practice_problem: Optional[str]
    video_url: Optional[str]
    solution_steps: Optional[List[dict]]  # [{step_number, title, explanation, math_expression, needs_visual, visual_elements}]
    
    # --- Visualization (Parallel agent output) ---
    visualization_steps: Optional[List[dict]]  # [{step, text, has_visual, image_url, alt_text}]
    visualization_fallback: bool  # True if visualization failed after retries
    
    # --- Progressive Visualization (NEW) ---
    is_graphing_problem: bool  # True if the problem asks for a graph as the answer
    step_images: Optional[dict]  # {step_number: image_url} - per-step visualization URLs
    final_graph_url: Optional[str]  # URL to the final complete graph
    
    # --- Output ---
    final_response_html: Optional[str]
    requires_user_action: bool  # True if we are waiting for topic selection
