"""
LangGraph Workflow for AI Math Tutor

This module implements the agentic workflow with:
- Conditional entry routing (text vs image)
- Confidence-based routing
- Parallel execution of teaching agents
- Human-in-the-loop support for ambiguous topics
"""

import asyncio
from typing import Literal
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END

# UPDATED: Async imports for LangGraph v0.2+
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

# LLM Imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
# from langchain_openai import ChatOpenAI  # OpenAI support (commented out)

from state import GraphState
from config import settings


# ============================================================================
# PYDANTIC SCHEMAS FOR STRUCTURED OUTPUT
# ============================================================================

class ClassificationResult(BaseModel):
    """Structured output for STEM topic classification."""
    subject: str = Field(
        description="One of: Math, Physics, Chemistry, Biology, Computer Science"
    )
    category: str = Field(
        description="Broad category. Math: Algebra/Calculus/Linear Algebra/Statistics. Physics: Mechanics/Electromagnetism/Thermodynamics. Chemistry: Stoichiometry/Organic/Thermodynamics"
    )
    specific_topic: str = Field(
        description="EXACT operation or concept. Examples: 'Cross Product', 'Dot Product', 'Gaussian Elimination', 'Matrix Multiplication', 'Molar Mass Calculation', 'Derivative - Power Rule', 'Newton Second Law'"
    )
    confidence: float = Field(
        description="Use 1.0 for ANY clear STEM problem. Reserve 0.0-0.3 ONLY for non-STEM gibberish."
    )
    ambiguous: bool = Field(
        description="Set to false if confidence >= 0.9. Only true if genuinely unclear between multiple topics."
    )
    alternatives: list[str] = Field(
        default_factory=list, 
        description="Leave empty unless ambiguous=true. If ambiguous, provide 2-3 alternative specific topics."
    )


class TeachingPlan(BaseModel):
    """Structured output for teaching plan generation."""
    html_content: str = Field(description="HTML formatted teaching plan with <span class='step-trigger'> for keywords")
    keywords: list[str] = Field(description="List of key concepts covered")


class SolutionStep(BaseModel):
    """Single step in a worked solution."""
    step_number: int = Field(description="Step number starting from 1")
    title: str = Field(description="Short title like 'Identify the vectors' or 'Apply the formula'")
    explanation: str = Field(description="Clear explanation of what we're doing in this step")
    math_expression: str = Field(default="", description="LaTeX math expression if applicable, empty string if not")


class WorkedSolution(BaseModel):
    """Complete step-by-step solution."""
    problem_restatement: str = Field(description="Restate the problem clearly in one sentence")
    steps: list[SolutionStep] = Field(description="3-6 solution steps")
    final_answer: str = Field(description="The final answer with units if applicable")
    key_concepts: list[str] = Field(description="2-4 key concepts used in this solution")


# ============================================================================
# NODE FUNCTIONS
# ============================================================================

async def text_classifier_node(state: GraphState) -> GraphState:
    """Classifies the STEM topic from text input using a lightweight LLM with structured output."""
    print(f"[TextClassifier] Processing text: {state['input_content'][:50]}...")
    
    # --- Option 1: Google Gemini (Free Tier) ---
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
        temperature=0
    )
    
    # --- Option 2: OpenAI (Production) ---
    # llm = ChatOpenAI(
    #     model="gpt-4o-mini",
    #     api_key=settings.openai_api_key,
    #     temperature=0
    # )
    
    # Create LCEL chain with structured output - GRANULAR CLASSIFICATION
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a STEM classifier that identifies EXACT operations and concepts.

FEW-SHOT EXAMPLES:

Input: "[9 8 3] x [2 1 4]" or "cross product of vectors"
Output: {{"subject": "Math", "category": "Linear Algebra", "specific_topic": "Cross Product", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "[3, 4] · [1, 2]" or "dot product"
Output: {{"subject": "Math", "category": "Linear Algebra", "specific_topic": "Dot Product", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "multiply matrices [[1,2],[3,4]] and [[5,6],[7,8]]"
Output: {{"subject": "Math", "category": "Linear Algebra", "specific_topic": "Matrix Multiplication", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "solve system: 2x + 3y = 5, x - y = 1" or "row reduce"
Output: {{"subject": "Math", "category": "Linear Algebra", "specific_topic": "Gaussian Elimination", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "find eigenvalues of [[1,2],[3,4]]"
Output: {{"subject": "Math", "category": "Linear Algebra", "specific_topic": "Eigenvalues", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "2x+5=13"
Output: {{"subject": "Math", "category": "Algebra", "specific_topic": "Linear Equations", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "d/dx (3x^2 + 2x)" or "derivative of x^2"
Output: {{"subject": "Math", "category": "Calculus", "specific_topic": "Derivative - Power Rule", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "∫ sin(x) dx" or "integral of cos"
Output: {{"subject": "Math", "category": "Calculus", "specific_topic": "Integral - Trigonometric", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "F=ma with 10N force" or "calculate acceleration"
Output: {{"subject": "Physics", "category": "Mechanics", "specific_topic": "Newton Second Law", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "balance: Fe + O2 -> Fe2O3"
Output: {{"subject": "Chemistry", "category": "Stoichiometry", "specific_topic": "Balancing Equations", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "how many moles in 44g CO2"
Output: {{"subject": "Chemistry", "category": "Stoichiometry", "specific_topic": "Molar Mass Calculation", "confidence": 1.0, "ambiguous": false, "alternatives": []}}

Input: "asdfgh random gibberish"
Output: {{"subject": "Unknown", "category": "Unknown", "specific_topic": "Unknown", "confidence": 0.0, "ambiguous": true, "alternatives": []}}

CRITICAL DETECTION RULES:
- "x" or "×" between vectors/brackets like [a,b,c] x [d,e,f] → Cross Product
- "·" or "dot" between vectors → Dot Product
- "multiply" + "matrices" → Matrix Multiplication
- "solve system" or "row reduce" or augmented matrix → Gaussian Elimination
- "eigenvalue" or "λ" or "characteristic" → Eigenvalues
- "d/dx" or "derivative" → Derivative (specify rule type)
- "∫" or "integral" → Integral (specify type)
- Chemical formulas with arrows → Balancing Equations
- "moles" or "grams" with chemical formula → Molar Mass Calculation"""),
        ("human", "Classify this problem with EXACT operation: {problem}")
    ])
    
    # Chain with structured output
    chain = prompt | llm.with_structured_output(ClassificationResult)
    
    try:
        # CRITICAL: Invoke chain with correct parameter name
        result = await chain.ainvoke({"problem": state["input_content"]})
        
        print(f"[TextClassifier] Raw result: subject={result.subject}, category={result.category}, specific_topic={result.specific_topic}, confidence={result.confidence}")
        
        # SAFETY CHECK: If the AI identified a topic but gave 0 confidence, override it.
        if result.specific_topic and result.specific_topic != "Unknown" and result.confidence < 0.5:
            print(f"⚠️ Overriding low confidence ({result.confidence}) for detected topic: {result.specific_topic}")
            result.confidence = 0.95
        
        # SAFETY CHECK 2: If we have math operators in input, guarantee high confidence
        math_indicators = ['+', '-', '=', 'x', '÷', '^', 'derivative', 'integral', 'equation', '[', ']']
        if any(indicator in state["input_content"].lower() for indicator in math_indicators):
            if result.confidence < 0.9:
                print(f"[TextClassifier] ⚠️  Input has math indicators, forcing confidence from {result.confidence} to 1.0")
                result.confidence = 1.0
        
        # Build full topic string: Subject - Category - Specific Topic
        full_topic = f"{result.subject} - {result.category} - {result.specific_topic}"
        if result.subject == "Unknown":
            full_topic = None
        
        print(f"[TextClassifier] Final: topic={full_topic}, confidence={result.confidence}")
        
        return {
            **state,
            "topic": full_topic if result.confidence >= settings.confidence_threshold_low else None,
            "confidence_score": result.confidence,
            "detected_ambiguity": result.ambiguous,
            "candidate_topics": result.alternatives
        }
    except Exception as e:
        print(f"[TextClassifier] Error: {e}")
        # Fallback to low confidence if LLM fails
        return {
            **state,
            "topic": None,
            "confidence_score": 0.3,
            "detected_ambiguity": True,
            "candidate_topics": ["Math - Algebra", "Math - Calculus", "Physics - Mechanics"]
        }


async def vision_classifier_node(state: GraphState) -> GraphState:
    """Classifies the STEM topic from image input using Gemini multimodal."""
    print(f"[VisionClassifier] Processing image...")
    
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    import json
    import re
    
    llm = ChatGoogleGenerativeAI(
        model=settings.vision_model,
        google_api_key=settings.google_api_key,
        temperature=0
    )
    
    # Retry logic for rate limits
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            image_data = state["input_content"]
            
            # SINGLE API CALL: Extract problem AND classify together
            combined_message = HumanMessage(
                content=[
                    {"type": "text", "text": """Analyze this image of a STEM problem.

TASK 1: Extract the exact problem text, equations, or question shown.
TASK 2: Classify the topic.

Respond in this EXACT JSON format:
{
  "extracted_problem": "The problem text you see in the image",
  "subject": "Math|Physics|Chemistry|Biology|Computer Science",
  "category": "Linear Algebra|Calculus|Mechanics|Stochastic Processes|etc",
  "specific_topic": "Cross Product|Derivative|Ornstein-Uhlenbeck Process|etc",
  "confidence": 1.0
}

Be specific with the topic. Use confidence 1.0 for clear STEM problems."""},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}}
                ]
            )
            
            result = await llm.ainvoke([combined_message])
            response_text = result.content
            
            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*?\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError(f"Could not parse JSON from: {response_text[:200]}")
            
            extracted_text = data.get("extracted_problem", "")
            subject = data.get("subject", "Math")
            category = data.get("category", "Unknown")
            specific_topic = data.get("specific_topic", "Unknown")
            confidence = float(data.get("confidence", 0.9))
            
            full_topic = f"{subject} - {category} - {specific_topic}"
            
            print(f"[VisionClassifier] Extracted: {extracted_text[:80]}...")
            print(f"[VisionClassifier] Classified as: {full_topic} (confidence: {confidence})")
            
            return {
                **state,
                "input_content": extracted_text,  # Replace image with text for step_solver
                "topic": full_topic,
                "confidence_score": confidence,
                "detected_ambiguity": False,
                "candidate_topics": []
            }
            
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "ResourceExhausted" in error_str or "quota" in error_str.lower():
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"[VisionClassifier] Rate limited, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
            
            print(f"[VisionClassifier] Error: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                **state,
                "topic": None,
                "confidence_score": 0.3,
                "detected_ambiguity": True,
                "candidate_topics": ["API rate limit reached. Please try again in a minute or paste the text instead."]
            }
    
    # Should not reach here
    return {
        **state,
        "topic": None,
        "confidence_score": 0.3,
        "detected_ambiguity": True, 
        "candidate_topics": ["Failed after retries. Please paste the text instead."]
    }


async def router_node(state: GraphState) -> GraphState:
    """Evaluates confidence and logs state for debugging."""
    confidence = state.get("confidence_score", 0.0)
    topic = state.get("topic", "None")
    
    print(f"[Router] DEBUG - Full State Keys: {list(state.keys())}")
    print(f"[Router] Confidence: {confidence:.2f}")
    print(f"[Router] Topic: {topic}")
    print(f"[Router] Detected Ambiguity: {state.get('detected_ambiguity', False)}")
    
    # CRITICAL: Ensure we return the state unchanged to pass to route_by_confidence
    return state


def route_by_confidence(state: GraphState) -> Literal["clarify", "disambiguate", "teach"]:
    """Routes based on confidence score with comprehensive logging."""
    confidence = state.get("confidence_score", 0.0)
    detected_ambiguity = state.get("detected_ambiguity", False)
    
    print(f"[RouteByConfidence] Received confidence: {confidence}")
    print(f"[RouteByConfidence] Thresholds - Low: {settings.confidence_threshold_low}, High: {settings.confidence_threshold_high}")
    
    if confidence < settings.confidence_threshold_low:
        print(f"[RouteByConfidence] → Routing to CLARIFY (confidence {confidence} < {settings.confidence_threshold_low})")
        return "clarify"
    elif confidence < settings.confidence_threshold_high or detected_ambiguity:
        print(f"[RouteByConfidence] → Routing to DISAMBIGUATE")
        return "disambiguate"
    else:
        print(f"[RouteByConfidence] → Routing to TEACH")
        return "teach"


async def clarification_node(state: GraphState) -> GraphState:
    print("[Clarification] Requesting user clarification...")
    return {
        **state,
        "requires_user_action": True,
        "final_response_html": "<p>Could you please provide more details?</p>"
    }


async def disambiguation_node(state: GraphState) -> GraphState:
    print(f"[Disambiguation] Pausing for user selection...")
    topics_html = "".join([f"<li data-topic='{t}'>{t}</li>" for t in state["candidate_topics"]])
    return {
        **state,
        "requires_user_action": True,
        "final_response_html": f"<p>Please select the topic:</p><ul>{topics_html}</ul>"
    }


async def teaching_architect_node(state: GraphState) -> GraphState:
    """Generates a structured STEM teaching plan using LCEL chain with structured output."""
    print(f"[TeachingArchitect] Creating lesson plan for: {state['topic']}")
    
    # --- Option 1: Google Gemini (Free Tier) ---
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
        temperature=0.3
    )
    
    # --- Option 2: OpenAI (Production) ---
    # llm = ChatOpenAI(
    #     model="gpt-4o-mini",
    #     api_key=settings.openai_api_key,
    #     temperature=0.3
    # )
    
    # Create LCEL chain with structured output
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert STEM teacher creating a step-by-step teaching plan.

Create a teaching plan for {topic}. Adapt your approach based on the subject:
- Math: Focus on formulas, equations, algebraic steps
- Physics: Include units, laws, free-body diagrams
- Chemistry: Include chemical equations, stoichiometry, periodic trends
- Biology: Include processes, systems, classifications
- Computer Science: Include algorithms, data structures, logic

Requirements:
1. Use <h3> for section headers
2. Write 3-5 major steps in <ol> lists
3. Wrap important concepts in <span class='step-trigger'>keyword</span> (these are clickable)
4. Keep it concise - explain the approach, don't solve yet
5. Use proper HTML: <p>, <ol>, <li>, <h3> tags

Example format:
<h3>Approach</h3>
<p>To solve this problem, follow these steps:</p>
<ol>
  <li>Identify the <span class='step-trigger'>given information</span> and units</li>
  <li>Apply the <span class='step-trigger'>relevant formula or principle</span></li>
  <li>Solve using appropriate <span class='step-trigger'>problem-solving methods</span></li>
</ol>
"""),
        ("human", "Topic: {topic}\nProblem: {problem}\n\nCreate the teaching plan.")
    ])
    
    # Chain with structured output
    chain = prompt | llm.with_structured_output(TeachingPlan)
    
    try:
        result = await chain.ainvoke({
            "topic": state["topic"],
            "problem": state["input_content"][:200]
        })
        
        return {
            **state,
            "teaching_plan": result.html_content
        }
    except Exception as e:
        print(f"[TeachingArchitect] Error: {e}")
        # Fallback plan
        return {
            **state,
            "teaching_plan": f"<p>Step-by-step approach for {state['topic']}</p>"
        }


async def step_solver_node(state: GraphState) -> GraphState:
    """Generates a step-by-step worked solution for the problem."""
    print(f"[StepSolver] Solving: {state['input_content'][:50]}...")
    
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
        temperature=0.2
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a STEM tutor solving problems step-by-step.

TOPIC: {topic}
PROBLEM: {problem}

Create a detailed step-by-step solution. Each step should:
1. Have a clear, short title
2. Explain what we're doing and why
3. Include math expressions in LaTeX format (use $ delimiters)

Topic-specific guidance:
- Cross Product: Use the determinant method with i, j, k unit vectors
- Dot Product: Multiply corresponding components and sum
- Matrix Multiplication: Show row × column operations
- Derivatives: Apply power rule, chain rule, etc. step by step
- Integrals: Show substitution or direct integration
- Stoichiometry: Show unit conversions and molar calculations
- Linear Equations: Show isolation of variable steps

Generate 3-6 clear steps that a student can follow."""),
        ("human", "Solve this step by step: {problem}")
    ])
    
    chain = prompt | llm.with_structured_output(WorkedSolution)
    
    try:
        result = await chain.ainvoke({
            "topic": state["topic"],
            "problem": state["input_content"]
        })
        
        # Convert to dict format for JSON serialization
        steps_dict = [
            {
                "step_number": s.step_number,
                "title": s.title,
                "explanation": s.explanation,
                "math_expression": s.math_expression
            }
            for s in result.steps
        ]
        
        print(f"[StepSolver] Generated {len(steps_dict)} steps")
        
        return {
            **state,
            "solution_steps": steps_dict,
            "worked_example": result.final_answer
        }
    except Exception as e:
        print(f"[StepSolver] Error: {e}")
        return {
            **state,
            "solution_steps": [{"step_number": 1, "title": "Error", "explanation": "Failed to generate solution", "math_expression": ""}],
            "worked_example": "Solution generation failed"
        }


async def practice_node(state: GraphState) -> GraphState:
    print(f"[Practice] Creating practice problem...")
    await asyncio.sleep(0.7)
    return {**state, "practice_problem": "## Try it yourself!\n\n..."}


async def video_node(state: GraphState) -> GraphState:
    print(f"[Video] Searching for video...")
    await asyncio.sleep(0.5)
    return {**state, "video_url": "https://youtube.com/watch?v=example"}


async def parallel_teaching_nodes(state: GraphState) -> GraphState:
    """Runs practice and video agents concurrently (step_solver runs before this)."""
    print("[ParallelExecution] Running practice and video agents concurrently...")
    results = await asyncio.gather(
        practice_node(state),
        video_node(state)
    )
    merged_state = {**state}
    for result in results:
        merged_state.update(result)
    return merged_state


async def assembler_node(state: GraphState) -> GraphState:
    print("[Assembler] Compiling final response...")
    final_html = f"<html><body><h1>{state['topic']}</h1></body></html>"
    return {
        **state,
        "final_response_html": final_html,
        "requires_user_action": False
    }


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

def route_input_type(state: GraphState) -> Literal["text_classifier", "vision_classifier"]:
    if state["input_type"] == "text":
        return "text_classifier"
    else:
        return "vision_classifier"


def create_stem_tutor_graph(checkpointer) -> StateGraph:
    workflow = StateGraph(GraphState)
    
    # Classification nodes
    workflow.add_node("text_classifier", text_classifier_node)
    workflow.add_node("vision_classifier", vision_classifier_node)
    workflow.add_node("router", router_node)
    
    # Decision nodes
    workflow.add_node("clarification", clarification_node)
    workflow.add_node("disambiguation", disambiguation_node)
    
    # Teaching nodes
    workflow.add_node("teaching_architect", teaching_architect_node)
    workflow.add_node("step_solver", step_solver_node)  # NEW: Step-by-step solution
    workflow.add_node("parallel_teaching", parallel_teaching_nodes)
    workflow.add_node("assembler", assembler_node)
    
    # Entry point routing
    workflow.set_conditional_entry_point(
        route_input_type,
        {"text_classifier": "text_classifier", "vision_classifier": "vision_classifier"}
    )
    
    # Classifier to router
    workflow.add_edge("text_classifier", "router")
    workflow.add_edge("vision_classifier", "router")
    
    # Confidence-based routing
    workflow.add_conditional_edges(
        "router",
        route_by_confidence,
        {
            "clarify": "clarification",
            "disambiguate": "disambiguation",
            "teach": "teaching_architect"
        }
    )
    
    # Terminal nodes
    workflow.add_edge("clarification", END)
    workflow.add_edge("disambiguation", END)
    
    # Teaching pipeline: architect → step_solver → parallel → assembler
    workflow.add_edge("teaching_architect", "step_solver")
    workflow.add_edge("step_solver", "parallel_teaching")
    workflow.add_edge("parallel_teaching", "assembler")
    workflow.add_edge("assembler", END)
    
    return workflow.compile(checkpointer=checkpointer)


# ============================================================================
# GRAPH INSTANCE (Updated for v2.0)
# ============================================================================

async def get_graph():
    """Returns the compiled graph with PostgreSQL checkpointer."""
    # 1. Create Async Connection Pool (Required for LangGraph v0.2+)
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        max_size=20,
        kwargs={"autocommit": True, "prepare_threshold": 0}
    )

    # 2. Create Async Checkpointer
    checkpointer = AsyncPostgresSaver(pool)
    
    # 3. Setup Tables (must await)
    await checkpointer.setup()
    
    return create_stem_tutor_graph(checkpointer)
