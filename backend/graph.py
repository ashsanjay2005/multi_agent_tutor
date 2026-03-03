"""
LangGraph Workflow for AI Math Tutor

This module implements the agentic workflow with:
- Conditional entry routing (text vs image)
- Confidence-based routing
- Parallel execution of teaching agents
- Human-in-the-loop support for ambiguous topics
"""

import asyncio
import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from state import GraphState
from config import settings
from backboard_client import get_backboard_service, is_backboard_available

logger = logging.getLogger(__name__)

def parse_json_output(text: str):
    """Clean and parse JSON from LLM output, handling markdown code blocks."""
    try:
        # Strip markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        return json.loads(text.strip())
    except Exception as e:
        logger.warning(f"JSON Parsing Error: {e}")
        return None


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
    logger.info(f"[TextClassifier] Processing text: {state['input_content'][:50]}...")
    
    # Try Backboard first for memory-aware classification
    backboard_thread_id = state.get("backboard_thread_id")
    result = None
    
    if is_backboard_available() and backboard_thread_id:
        try:
            backboard = await get_backboard_service()
            
            system_prompt = """You are a STEM classifier that identifies EXACT operations and concepts.
            Return ONLY valid JSON matching this schema:
            {
                "subject": "Math/Physics/Chemistry...",
                "category": "Broad category",
                "specific_topic": "EXACT operation",
                "confidence": 0.0-1.0,
                "ambiguous": boolean,
                "alternatives": ["alt1", "alt2"]
            }
            
            CRITICAL: 
            - Use 1.0 confidence for clear math problems.
            - "x" between vectors = Cross Product
            - "dot" = Dot Product
            - "solve system" = Gaussian Elimination
            """
            
            response_text = await backboard.send_message(
                thread_id=backboard_thread_id,
                content=f"Classify this problem: {state['input_content']}",
                metadata={"task": "classification"},
                send_to_llm=True
            )
            
            json_data = parse_json_output(response_text)
            if json_data:
                result = ClassificationResult(**json_data)
                logger.debug(f"[TextClassifier] Backboard result: {result}")
                
        except Exception as e:
            logger.warning(f"[TextClassifier] Backboard failed: {e}, falling back to standard LLM")
    
    # Fallback to LangChain if Backboard didn't produce a result
    if not result:
        # --- Option 1: Google Gemini (Free Tier) ---
        llm = ChatGoogleGenerativeAI(
            model=settings.text_model,
            google_api_key=settings.google_api_key,
            temperature=0
        )
        
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
            result = await chain.ainvoke({"problem": state["input_content"]})
        except Exception as e:
            logger.error(f"[TextClassifier] LangChain fallback failed: {e}")

    # Process result (from Backboard or LangChain)
    if result:
        try:
            logger.debug(f"[TextClassifier] Raw result: subject={result.subject}, category={result.category}, specific_topic={result.specific_topic}, confidence={result.confidence}")
            
            # SAFETY CHECK: If the AI identified a topic but gave 0 confidence, override it.
            if result.specific_topic and result.specific_topic != "Unknown" and result.confidence < 0.5:
                logger.warning(f"Overriding low confidence ({result.confidence}) for detected topic: {result.specific_topic}")
                result.confidence = 0.95
            
            # SAFETY CHECK 2: If we have math operators in input, guarantee high confidence
            math_indicators = ['+', '-', '=', 'x', '÷', '^', 'derivative', 'integral', 'equation', '[', ']']
            if any(indicator in state["input_content"].lower() for indicator in math_indicators):
                if result.confidence < 0.9:
                    logger.warning(f"[TextClassifier] Input has math indicators, forcing confidence from {result.confidence} to 1.0")
                    result.confidence = 1.0
            
            # Build full topic string: Subject - Category - Specific Topic
            full_topic = f"{result.subject} - {result.category} - {result.specific_topic}"
            if result.subject == "Unknown":
                full_topic = None
            
            logger.info(f"[TextClassifier] Final: topic={full_topic}, confidence={result.confidence}")
            
            return {
                **state,
                "topic": full_topic if result.confidence >= settings.confidence_threshold_low else None,
                "confidence_score": result.confidence,
                "detected_ambiguity": result.ambiguous,
                "candidate_topics": result.alternatives
            }
        except Exception as e:
             logger.error(f"[TextClassifier] Processing error: {e}", exc_info=True)

    # Final Fallback
    return {
        **state,
        "topic": None,
        "confidence_score": 0.3,
        "detected_ambiguity": True,
        "candidate_topics": ["Math - Algebra", "Math - Calculus", "Physics - Mechanics"]
    }


async def vision_classifier_node(state: GraphState) -> GraphState:
    """Classifies the STEM topic from image input using Gemini multimodal."""
    logger.info("[VisionClassifier] Processing image...")
    
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    import json
    import re
    
    llm = ChatGoogleGenerativeAI(
        model=settings.vision_model,
        google_api_key=settings.google_api_key,
        temperature=0
    )
    
    # Retry logic for rate limits - API recommends 45s wait
    max_retries = 2
    retry_delay = 45  # Gemini free tier needs 45s to reset
    
    for attempt in range(max_retries):
        try:
            image_data = state["input_content"]
            
            # Support both URL (from Supabase Storage) and raw base64
            if image_data.startswith("http"):
                import base64 as b64
                import supabase_client
                raw_bytes = await supabase_client.download_image_bytes(image_data)
                image_b64 = b64.b64encode(raw_bytes).decode("utf-8")
            else:
                image_b64 = image_data
            
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
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                ]
            )
            
            result = await llm.ainvoke([combined_message])
            response_text = result.content
            
            logger.debug(f"[VisionClassifier] Raw response: {response_text[:300]}...")
            
            # Parse JSON from response - find matching braces
            start_idx = response_text.find('{')
            if start_idx == -1:
                raise ValueError(f"No JSON found in response: {response_text[:200]}")
            
            # Find the matching closing brace
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
            data = json.loads(json_str)
            
            extracted_text = data.get("extracted_problem", "")
            subject = data.get("subject", "Math")
            category = data.get("category", "Unknown")
            specific_topic = data.get("specific_topic", "Unknown")
            confidence = float(data.get("confidence", 0.9))
            
            full_topic = f"{subject} - {category} - {specific_topic}"
            
            logger.info(f"[VisionClassifier] Extracted: {extracted_text[:80]}...")
            logger.info(f"[VisionClassifier] Classified as: {full_topic} (confidence: {confidence})")
            
            return {
                **state,
                "input_content": extracted_text,  # Replace image with text for step_solver
                "topic": full_topic,
                "confidence_score": confidence,
                "detected_ambiguity": False,
                "candidate_topics": []
            }
            
        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = "429" in str(e) or "resourceexhausted" in error_str or "quota" in error_str
            is_parse_error = "json" in error_str or "unterminated" in error_str or "parse" in error_str
            
            # Retry on rate limits or parse errors (sometimes API returns truncated response)
            if (is_rate_limit or is_parse_error) and attempt < max_retries - 1:
                wait_time = retry_delay if is_rate_limit else 5  # 45s for rate limit, 5s for parse error
                logger.warning(f"[VisionClassifier] {'Rate limited' if is_rate_limit else 'Parse error'}, waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            
            logger.error(f"[VisionClassifier] Error: {e}", exc_info=True)
            
            # Show appropriate error message
            if is_rate_limit:
                error_msg = "API rate limit reached. Please try again in a minute or paste the text instead."
            else:
                error_msg = "Failed to analyze image. Please try again or paste the text instead."
            
            return {
                **state,
                "topic": None,
                "confidence_score": 0.3,
                "detected_ambiguity": True,
                "candidate_topics": [error_msg]
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
    
    logger.debug(f"[Router] State keys: {list(state.keys())}")
    logger.debug(f"[Router] Confidence: {confidence:.2f}, Topic: {topic}, Ambiguous: {state.get('detected_ambiguity', False)}")
    
    # CRITICAL: Ensure we return the state unchanged to pass to route_by_confidence
    return state


def route_by_confidence(state: GraphState) -> Literal["clarify", "disambiguate", "teach"]:
    """Routes based on confidence score with comprehensive logging."""
    confidence = state.get("confidence_score", 0.0)
    detected_ambiguity = state.get("detected_ambiguity", False)
    
    logger.debug(f"[RouteByConfidence] confidence={confidence}, thresholds=({settings.confidence_threshold_low}, {settings.confidence_threshold_high})")
    
    if confidence < settings.confidence_threshold_low:
        logger.info(f"[RouteByConfidence] → Routing to CLARIFY (confidence {confidence} < {settings.confidence_threshold_low})")
        return "clarify"
    elif confidence < settings.confidence_threshold_high or detected_ambiguity:
        logger.info("[RouteByConfidence] → Routing to DISAMBIGUATE")
        return "disambiguate"
    else:
        logger.info("[RouteByConfidence] → Routing to TEACH")
        return "teach"


async def clarification_node(state: GraphState) -> GraphState:
    logger.info("[Clarification] Requesting user clarification...")
    return {
        **state,
        "requires_user_action": True,
        "final_response_html": "<p>Could you please provide more details?</p>"
    }


async def disambiguation_node(state: GraphState) -> GraphState:
    logger.info("[Disambiguation] Pausing for user selection...")
    topics_html = "".join([f"<li data-topic='{t}'>{t}</li>" for t in state["candidate_topics"]])
    return {
        **state,
        "requires_user_action": True,
        "final_response_html": f"<p>Please select the topic:</p><ul>{topics_html}</ul>"
    }


async def teaching_architect_node(state: GraphState) -> GraphState:
    """Generates a structured STEM teaching plan using LCEL chain with structured output."""
    logger.info(f"[TeachingArchitect] Creating lesson plan for: {state['topic']}")
    
    # --- Option 1: Google Gemini (Free Tier) ---
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
    )
    
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
        logger.error(f"[TeachingArchitect] Error: {e}", exc_info=True)
        # Fallback plan
        return {
            **state,
            "teaching_plan": f"<p>Step-by-step approach for {state['topic']}</p>"
        }


async def step_solver_node(state: GraphState) -> GraphState:
    """Generates a step-by-step worked solution for the problem."""
    logger.info(f"[StepSolver] Solving: {state['input_content'][:50]}...")
    
    # Try Backboard first for memory-aware solution
    backboard_thread_id = state.get("backboard_thread_id")
    result = None
    student_profile_context = ""
    
    if is_backboard_available() and backboard_thread_id:
        try:
            backboard = await get_backboard_service()
            
            # PRE-FLIGHT MEMORY CHECK: Get student's topic-specific profile
            topic = state.get('topic', 'Unknown')
            profile = await backboard.get_student_profile(backboard_thread_id, topic)
            
            # Build adaptive context based on profile
            if profile.has_history:
                student_profile_context = f"""
STUDENT PROFILE FOR {topic}:
{profile.summary}

ADAPT YOUR RESPONSE:
"""
                if profile.weak_concepts:
                    student_profile_context += f"- WEAKNESS AREAS (add extra detail, prerequisite refreshers): {', '.join(profile.weak_concepts[:3])}\n"
                if profile.strong_concepts:
                    student_profile_context += f"- STRENGTH AREAS (be concise, skip basics): {', '.join(profile.strong_concepts[:3])}\n"
            else:
                student_profile_context = "\nNo prior history on this topic - provide balanced explanations.\n"
            
            # PROACTIVE TUTORING PROMPT with student profile
            proactive_prompt = f"""Solve this problem step-by-step: {state['input_content']}
Topic: {topic}
{student_profile_context}
INSTRUCTIONS:
1. If WEAKNESS shown: Provide EXTRA DETAIL, add 💡 Note callouts for common pitfalls, include prerequisite refreshers
2. If STRENGTH shown: Be concise, skip basic explanations, challenge the student
3. Use **bold** to highlight critical steps

CRITICAL FORMATTING RULES:
- Write explanations in PLAIN TEXT (English sentences with proper spacing)
- ONLY use LaTeX ($...$) for actual mathematical equations and expressions
- DO NOT wrap regular text like "The eigenvalues are" in LaTeX
- Good: "The eigenvalues are $\\lambda_1 = 5$ and $\\lambda_2 = 2$"
- Bad: "$Theeigenvaluesare\\lambda_1 = 5and\\lambda_2 = 2$"

Return ONLY valid JSON matching this schema:
{{
    "problem_restatement": "One sentence summary in plain text",
    "steps": [
        {{
            "step_number": 1,
            "title": "Short title (plain text, no LaTeX)",
            "explanation": "Plain text explanation with inline $math$ only for equations",
            "math_expression": "LaTeX expression for the key equation of this step"
        }}
    ],
    "final_answer": "Final answer (plain text with $math$ for the result)",
    "key_concepts": ["concept1", "concept2"]
}}

Create 3-6 clear steps. Keep text readable - only equations in LaTeX."""
            
            response_text = await backboard.send_message(
                thread_id=backboard_thread_id,
                content=proactive_prompt,
                metadata={"task": "solving", "topic": state.get("topic")},
                send_to_llm=True
            )
            
            json_data = parse_json_output(response_text)
            if json_data:
                result = WorkedSolution(**json_data)
                logger.info(f"[StepSolver] Backboard generated {len(result.steps)} steps (profile-aware)")
                
        except Exception as e:
            logger.warning(f"[StepSolver] Backboard failed: {e}, falling back to standard LLM")

    # Fallback to LangChain
    if not result:
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
    1. Have a clear, short title (plain text, no LaTeX)
    2. Explain what we're doing and why (plain text sentences)
    3. Include math expressions in LaTeX format ONLY for actual equations
    
    CRITICAL: Keep explanations readable!
    - DO NOT wrap regular text in LaTeX
    - Good: "To find the eigenvalues, we solve $det(A - \\lambda I) = 0$"
    - Bad: "$Tofindtheeigenvalueswesolvedet(A-\\lambda I)=0$"
    
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
        except Exception as e:
             logger.error(f"[StepSolver] LangChain fallback failed: {e}", exc_info=True)

    # Process Result
    if result:
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
        
        logger.info(f"[StepSolver] Generated {len(steps_dict)} steps")
        
        # EXPLICIT MEMORY SAVE: Save completed problem to Backboard memory
        # (memory="Auto" in send_message doesn't trigger writes reliably)
        if is_backboard_available() and backboard_thread_id:
            try:
                backboard = await get_backboard_service()
                await backboard.shadow_save(
                    thread_id=backboard_thread_id,
                    problem_text=state["input_content"][:500],  # Truncate for memory
                    topic=state.get("topic", "Unknown"),
                    solution_summary=result.final_answer
                )
                logger.info(f"[StepSolver] Saved to Backboard memory: {state.get('topic')}")
            except Exception as e:
                logger.warning(f"[StepSolver] Memory save failed (non-critical): {e}")
        
        return {
            **state,
            "solution_steps": steps_dict,
            "worked_example": result.final_answer
        }

    # Final Failure Case
    return {
        **state,
        "solution_steps": [{"step_number": 1, "title": "Error", "explanation": "Failed to generate solution", "math_expression": ""}],
        "worked_example": "Solution generation failed"
    }


async def practice_node(state: GraphState) -> GraphState:
    logger.info("[Practice] Creating practice problem...")
    await asyncio.sleep(0.7)
    return {**state, "practice_problem": "## Try it yourself!\n\n..."}


async def video_node(state: GraphState) -> GraphState:
    logger.info("[Video] Searching for video...")
    await asyncio.sleep(0.5)
    return {**state, "video_url": "https://youtube.com/watch?v=example"}


async def parallel_teaching_nodes(state: GraphState) -> GraphState:
    """Runs practice and video agents concurrently (step_solver runs before this)."""
    logger.info("[ParallelExecution] Running practice and video agents concurrently...")
    results = await asyncio.gather(
        practice_node(state),
        video_node(state)
    )
    merged_state = {**state}
    for result in results:
        merged_state.update(result)
    return merged_state


async def assembler_node(state: GraphState) -> GraphState:
    """Compiles final response."""
    logger.info("[Assembler] Compiling final response...")
    final_html = f"<html><body><h1>{state['topic']}</h1></body></html>"
    
    # Note: Memory is already saved by step_solver_node via send_message with memory="Auto"
    # No need to call shadow_save here - that would create duplicate memories
    
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


def create_stem_tutor_graph(checkpointer=None) -> StateGraph:
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
    """Returns (pool, checkpointed_graph, lightweight_graph).
    
    - checkpointed_graph: Used ONLY for disambiguation / human-in-the-loop
    - lightweight_graph: Default — zero checkpoint overhead
    
    The caller MUST store the pool reference and call `await pool.close()`
    during application shutdown.
    
    Retries up to 3 times with exponential backoff to handle transient
    Supabase PgBouncer DNS issues (e.g., after project unpause).
    """
    import asyncio
    
    max_retries = 3
    last_error = None
    
    for attempt in range(1, max_retries + 1):
        pool = None
        try:
            # 1. Create Async Connection Pool — Nano tier safe
            pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=0,       # Allow closing ALL idle connections (best for Supabase)
                max_size=3,       # Nano tier limit
                open=False,
                max_lifetime=60,  # Recycle connections every 60s
                num_workers=1,    # Serialize connection creation to avoid storms
                timeout=10,       # Connection timeout in seconds
                kwargs={
                    "autocommit": True, 
                    "prepare_threshold": None,  # Disable prepared statements
                    "keepalives": 1,
                    "keepalives_idle": 20,
                    "keepalives_interval": 10,
                    "keepalives_count": 5,
                },
            )
            await pool.open()     # Explicit, awaitable open — no warnings

            # 2. Create Async Checkpointer on the open pool
            checkpointer = AsyncPostgresSaver(pool)

            # 3. Setup checkpoint tables (idempotent CREATE IF NOT EXISTS)
            await checkpointer.setup()

            # 4. Build both graph variants
            checkpointed_graph = create_stem_tutor_graph(checkpointer=checkpointer)
            lightweight_graph = create_stem_tutor_graph(checkpointer=None)
            
            logger.info(f"Database pool connected successfully (attempt {attempt})")
            return pool, checkpointed_graph, lightweight_graph
            
        except Exception as e:
            last_error = e
            logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
            # Clean up the failed pool
            if pool:
                try:
                    await pool.close()
                except Exception:
                    pass
            if attempt < max_retries:
                wait_time = 2 ** attempt  # 2s, 4s
                logger.info(f"Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
    
    raise RuntimeError(f"Failed to connect to database after {max_retries} attempts: {last_error}")

