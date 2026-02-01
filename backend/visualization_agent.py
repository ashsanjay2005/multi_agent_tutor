"""
Visualization Agent for AI Math Tutor (V2)

This module implements the Selective Visualization Agent that generates
Plotly graphs for STEM problems using a local Python REPL.

Uses local execution with plotly + kaleido for PNG rendering.
"""

import io
import base64
import logging
import hashlib
import asyncio
from typing import Optional, List
from pydantic import BaseModel, Field

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

from google import genai
from google.genai import types
from config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class VisualizationStep(BaseModel):
    """A single visualization step with optional graph."""
    step: int = Field(description="Step number")
    text: str = Field(description="Explanation with LaTeX")
    has_visual: bool = Field(description="Whether this step includes a graph")
    image_url: Optional[str] = Field(default=None, description="GCS URL to the generated plot")
    alt_text: Optional[str] = Field(default=None, description="Accessibility description of the graph")


class VisualizationOutput(BaseModel):
    """Complete output from the Visualization Agent."""
    needs_visualization: bool = Field(description="Whether any step requires a graph")
    total_steps: int = Field(description="Total number of visualization steps")
    steps: List[VisualizationStep] = Field(default_factory=list)
    fallback_text_only: bool = Field(default=False, description="True if visualization failed after retries")


# ============================================================================
# VISUALIZATION DECISION LOGIC
# ============================================================================

VISUAL_KEYWORDS = {
    # Graphing
    "graph", "plot", "sketch", "draw", "curve", "function",
    # Physics
    "force diagram", "free body", "vector", "trajectory", "motion",
    # Chemistry
    "molecular", "structure", "geometry", "orbital", "vsepr",
    # Geometry
    "triangle", "circle", "coordinate", "plane", "angle",
}

NON_VISUAL_KEYWORDS = {
    "solve", "calculate", "simplify", "evaluate", "find the value",
    "prove", "derive", "factor", "expand",
}


def should_visualize(problem: str, topic: str) -> bool:
    """
    Determines if a problem benefits from visual explanation.
    """
    problem_lower = problem.lower()
    topic_lower = topic.lower() if topic else ""
    
    # Check for explicit visual keywords
    for keyword in VISUAL_KEYWORDS:
        if keyword in problem_lower or keyword in topic_lower:
            logger.info(f"Visualization needed: matched keyword '{keyword}'")
            return True
    
    # Check for function-like patterns that suggest graphing
    import re
    function_pattern = r'y\s*=|f\(x\)\s*=|graph of|plot of'
    if re.search(function_pattern, problem_lower):
        logger.info("Visualization needed: function pattern detected")
        return True
    
    # Check for non-visual indicators
    for keyword in NON_VISUAL_KEYWORDS:
        if keyword in problem_lower:
            logger.info(f"No visualization: matched non-visual keyword '{keyword}'")
            return False
    
    return False


# ============================================================================
# PLOTLY CODE GENERATION PROMPT
# ============================================================================

PLOTLY_PROMPT_TEMPLATE = """You are a visualization expert. Generate Plotly Python code to create a graph for this math problem.

**Problem:** {problem}
**Topic:** {topic}

**Requirements:**
1. Create a Plotly figure using `plotly.graph_objects` as `go`
2. Do NOT use plotly.express (px) - only use graph_objects
3. Use a dark theme with background color '#0B1220'
4. Use purple (#9333EA) as the primary line color
5. Show important features: intercepts, asymptotes, key points
6. Add axis labels and a descriptive title
7. The code must create a variable called `fig` that is the Plotly Figure
8. Do NOT call fig.show() or fig.write_image() - just create the figure
9. numpy is available as `np`

**Example structure:**
```python
import numpy as np
import plotly.graph_objects as go

# Create data
x = np.linspace(-10, 10, 500)
y = # your function here

# Create figure
fig = go.Figure()
fig.add_trace(go.Scatter(x=x, y=y, mode='lines', name='f(x)', line=dict(color='#9333EA', width=2)))

# Style for dark theme
fig.update_layout(
    title='Graph Title',
    xaxis_title='x',
    yaxis_title='y',
    plot_bgcolor='#0B1220',
    paper_bgcolor='#0B1220',
    font=dict(color='white'),
    xaxis=dict(gridcolor='#1E293B', zerolinecolor='#475569'),
    yaxis=dict(gridcolor='#1E293B', zerolinecolor='#475569')
)
```

Generate the complete code for plotting: {problem}"""


# ============================================================================
# LOCAL PLOTLY EXECUTION
# ============================================================================

def execute_plotly_code_sync(code: str) -> Optional[bytes]:
    """
    Execute Plotly code in a local sandbox and return PNG bytes.
    
    This runs Plotly code with pre-injected modules (no import needed).
    """
    try:
        # Strip import statements from the code since we pre-inject modules
        import re
        code_lines = code.split('\n')
        filtered_lines = []
        for line in code_lines:
            # Skip import lines
            if re.match(r'^\s*(import|from)\s+', line):
                continue
            filtered_lines.append(line)
        clean_code = '\n'.join(filtered_lines)
        
        logger.info(f"Executing cleaned code ({len(clean_code)} chars)")
        
        # Create execution environment with pre-injected modules
        # Only use graph_objects (no pandas required, unlike plotly.express)
        exec_globals = {
            '__builtins__': {
                'range': range,
                'len': len,
                'abs': abs,
                'min': min,
                'max': max,
                'sum': sum,
                'round': round,
                'int': int,
                'float': float,
                'list': list,
                'tuple': tuple,
                'dict': dict,
                'str': str,
                'bool': bool,
                'True': True,
                'False': False,
                'None': None,
                'print': print,
                'zip': zip,
                'enumerate': enumerate,
                'sorted': sorted,
            },
            # Pre-injected modules - only graph_objects (no pandas dependency)
            'np': np,
            'numpy': np,
            'go': go,
            'plotly': __import__('plotly'),
        }
        
        local_vars = {}
        
        # Execute the cleaned code
        exec(clean_code, exec_globals, local_vars)
        
        # Get the figure - check both local_vars and exec_globals
        fig = local_vars.get('fig') or exec_globals.get('fig')
        if fig is None:
            logger.error("Code did not create a 'fig' variable")
            logger.debug(f"local_vars keys: {list(local_vars.keys())}")
            return None
        
        # Export to PNG bytes using kaleido
        img_bytes = pio.to_image(fig, format='png', width=800, height=600, scale=2)
        logger.info(f"Generated PNG image: {len(img_bytes)} bytes")
        
        return img_bytes
        
    except Exception as e:
        logger.error(f"Plotly execution error: {e}")
        return None


async def execute_plotly_code(code: str, max_retries: int = 3) -> tuple[Optional[bytes], int]:
    """
    Execute Plotly code asynchronously with retry logic.
    """
    retries = 0
    last_error = None
    
    while retries < max_retries:
        try:
            # Run sync execution in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, execute_plotly_code_sync, code)
            
            if result is not None:
                return result, retries + 1
            
            retries += 1
            last_error = "No figure generated"
            
        except Exception as e:
            last_error = str(e)
            logger.error(f"Plotly execution error (attempt {retries + 1}): {e}")
            retries += 1
    
    logger.error(f"All {max_retries} retries exhausted. Last error: {last_error}")
    return None, retries


# ============================================================================
# GCS IMAGE UPLOAD
# ============================================================================

async def upload_to_gcs(image_bytes: bytes, problem_hash: str) -> Optional[str]:
    """
    Upload PNG to Google Cloud Storage and return a V4 signed URL.
    """
    try:
        from google.cloud import storage
        from datetime import timedelta
        import os
        import time
        
        # Verify credentials are set
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set, using base64 fallback")
            return f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
        
        # Initialize client
        client = storage.Client()
        bucket_name = settings.gcs_bucket_name
        bucket = client.bucket(bucket_name)
        
        # Create unique filename
        timestamp = int(time.time())
        filename = f"plots/{problem_hash}_{timestamp}.png"
        
        # Upload PNG bytes
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type="image/png")
        
        logger.info(f"Uploaded plot to GCS: gs://{bucket_name}/{filename}")
        
        # Generate V4 signed URL (1 hour expiry)
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET"
        )
        
        return signed_url
        
    except ImportError:
        logger.warning("google-cloud-storage not installed, using base64 fallback")
        return f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
    
    except Exception as e:
        logger.error(f"GCS upload failed: {e}")
        # Fallback to base64
        return f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"


# ============================================================================
# PROGRAMMATIC CUMULATIVE GRAPH BUILDER
# ============================================================================

def parse_visual_element(element: str) -> dict:
    """
    Parse a visual_element string like 'vertical_asymptote_x=1' into structured data.
    """
    import re
    
    result = {"type": None, "data": {}}
    
    # vertical_asymptote_x=<value>
    match = re.match(r'vertical_asymptote_x=(.+)', element)
    if match:
        return {"type": "vertical_asymptote", "data": {"x": float(match.group(1))}}
    
    # horizontal_asymptote_y=<value>
    match = re.match(r'horizontal_asymptote_y=(.+)', element)
    if match:
        return {"type": "horizontal_asymptote", "data": {"y": float(match.group(1))}}
    
    # oblique_asymptote_<expression>
    match = re.match(r'oblique_asymptote_(.+)', element)
    if match:
        return {"type": "oblique_asymptote", "data": {"expr": match.group(1)}}
    
    # x_intercept_(<x>,0)
    match = re.match(r'x_intercept_\(([^,]+),\s*0\)', element)
    if match:
        return {"type": "x_intercept", "data": {"x": float(match.group(1))}}
    
    # y_intercept_(0,<y>)
    match = re.match(r'y_intercept_\(0,\s*([^)]+)\)', element)
    if match:
        return {"type": "y_intercept", "data": {"y": float(match.group(1))}}
    
    # point_(<x>,<y>)
    match = re.match(r'point_\(([^,]+),\s*([^)]+)\)', element)
    if match:
        return {"type": "point", "data": {"x": float(match.group(1)), "y": float(match.group(2))}}
    
    # positive_region_(<start>,<end>)
    match = re.match(r'positive_region_\(([^,]+),\s*([^)]+)\)', element)
    if match:
        return {"type": "positive_region", "data": {"start": match.group(1), "end": match.group(2)}}
    
    # negative_region_(<start>,<end>)
    match = re.match(r'negative_region_\(([^,]+),\s*([^)]+)\)', element)
    if match:
        return {"type": "negative_region", "data": {"start": match.group(1), "end": match.group(2)}}
    
    # function_curve
    if element == "function_curve":
        return {"type": "function_curve", "data": {}}
    
    return result


def build_cumulative_graph(
    cumulative_elements: List[str],
    function_expr: str,
    title: str = "Graph",
    new_elements: List[str] = None,
    include_function: bool = False
) -> Optional[bytes]:
    """
    Build a Plotly graph programmatically from parsed visual elements.
    
    Args:
        cumulative_elements: All visual elements accumulated so far
        function_expr: The function expression (e.g. "(x-2)^2*(x+1)/(x-1)")
        title: Graph title
        new_elements: Elements new in this step (will be highlighted in purple)
        include_function: Whether to plot the actual function curve
    
    Returns:
        PNG bytes of the graph, or None if failed
    """
    import re
    
    try:
        fig = go.Figure()
        
        # Parse all elements
        parsed_elements = [parse_visual_element(e) for e in cumulative_elements]
        new_element_set = set(new_elements or [])
        
        # Check if function_curve is in elements
        has_function_curve = any(e.get("type") == "function_curve" for e in parsed_elements)
        
        # Try to create a plottable function from the expression
        x = np.linspace(-10, 10, 1000)
        y = None
        
        # Clean up the function expression for numpy
        try:
            # Replace common math notation with numpy
            expr_clean = function_expr.replace("^", "**")
            expr_clean = re.sub(r'(\d)([x(])', r'\1*\2', expr_clean)  # 2x -> 2*x
            expr_clean = re.sub(r'\)(\d)', r')*\1', expr_clean)  # )2 -> )*2
            expr_clean = re.sub(r'\)(x)', r')*\1', expr_clean)  # )x -> )*x
            expr_clean = re.sub(r'(x)\(', r'\1*(', expr_clean)  # x( -> x*(
            
            # Evaluate
            y = eval(expr_clean, {"x": x, "np": np, "abs": np.abs})
            
            # Handle discontinuities (asymptotes)
            if y is not None:
                y = np.where(np.abs(y) > 50, np.nan, y)
        except Exception as e:
            logger.warning(f"Could not parse function expression: {e}")
        
        # Add function curve if we have it and include_function is True or function_curve is in elements
        if y is not None and (include_function or has_function_curve):
            fig.add_trace(go.Scatter(
                x=x, y=y, mode='lines', name='f(x)',
                line=dict(color='#9333EA', width=2.5)
            ))
        
        # Process each element
        for i, elem_str in enumerate(cumulative_elements):
            parsed = parse_visual_element(elem_str)
            is_new = elem_str in new_element_set
            color = '#9333EA' if is_new else '#6B7280'  # Purple for new, grey for old
            
            elem_type = parsed.get("type")
            data = parsed.get("data", {})
            
            if elem_type == "vertical_asymptote":
                fig.add_vline(
                    x=data["x"], 
                    line_dash="dash", 
                    line_color='#F97316',  # Orange
                    annotation_text=f"x={data['x']}"
                )
            
            elif elem_type == "horizontal_asymptote":
                fig.add_hline(
                    y=data["y"], 
                    line_dash="dash", 
                    line_color='#10B981',  # Green
                    annotation_text=f"y={data['y']}"
                )
            
            elif elem_type == "x_intercept":
                fig.add_trace(go.Scatter(
                    x=[data["x"]], y=[0],
                    mode='markers', name=f'x-int ({data["x"]}, 0)',
                    marker=dict(color='#EF4444', size=10)  # Red
                ))
            
            elif elem_type == "y_intercept":
                fig.add_trace(go.Scatter(
                    x=[0], y=[data["y"]],
                    mode='markers', name=f'y-int (0, {data["y"]})',
                    marker=dict(color='#3B82F6', size=10)  # Blue
                ))
            
            elif elem_type == "point":
                fig.add_trace(go.Scatter(
                    x=[data["x"]], y=[data["y"]],
                    mode='markers', name=f'({data["x"]}, {data["y"]})',
                    marker=dict(color=color, size=8)
                ))
            
            elif elem_type == "oblique_asymptote":
                # Try to parse and plot the oblique asymptote expression
                try:
                    expr = data.get("expr", "x")
                    # Clean up expression for numpy
                    expr_clean = expr.replace("^", "**")
                    expr_clean = re.sub(r'(\d)([x(])', r'\1*\2', expr_clean)
                    expr_clean = re.sub(r'\)(\d)', r')*\1', expr_clean)
                    expr_clean = re.sub(r'\)(x)', r')*\1', expr_clean)
                    
                    y_asym = eval(expr_clean, {"x": x, "np": np, "abs": np.abs})
                    fig.add_trace(go.Scatter(
                        x=x, y=y_asym, mode='lines',
                        name=f'Oblique: y={expr}',
                        line=dict(color='#22C55E', width=2, dash='dash')  # Green dashed
                    ))
                    logger.info(f"Added oblique asymptote: y={expr}")
                except Exception as e:
                    logger.warning(f"Could not plot oblique asymptote: {e}")
            
            elif elem_type == "positive_region":
                # Add shading for positive region (above x-axis)
                start = data.get("start", "-10")
                end = data.get("end", "10")
                try:
                    x_start = float(start) if start not in ["-inf", "inf"] else (-10 if start == "-inf" else 10)
                    x_end = float(end) if end not in ["-inf", "inf"] else (-10 if end == "-inf" else 10)
                    fig.add_vrect(x0=x_start, x1=x_end, fillcolor='rgba(34, 197, 94, 0.15)', 
                                  layer='below', line_width=0)
                    logger.info(f"Added positive region: ({start}, {end})")
                except Exception as e:
                    logger.warning(f"Could not parse positive region: {e}")
            
            elif elem_type == "negative_region":
                # Add shading for negative region (below x-axis)
                start = data.get("start", "-10")
                end = data.get("end", "10")
                try:
                    x_start = float(start) if start not in ["-inf", "inf"] else (-10 if start == "-inf" else 10)
                    x_end = float(end) if end not in ["-inf", "inf"] else (-10 if end == "-inf" else 10)
                    fig.add_vrect(x0=x_start, x1=x_end, fillcolor='rgba(239, 68, 68, 0.15)', 
                                  layer='below', line_width=0)
                    logger.info(f"Added negative region: ({start}, {end})")
                except Exception as e:
                    logger.warning(f"Could not parse negative region: {e}")
            
            # Log unrecognized elements
            elif elem_type is None:
                logger.warning(f"Unrecognized visual element: {elem_str}")
        
        # Style for dark theme
        fig.update_layout(
            title=title,
            xaxis_title='x',
            yaxis_title='y',
            plot_bgcolor='#0B1220',
            paper_bgcolor='#0B1220',
            font=dict(color='white'),
            xaxis=dict(gridcolor='#1E293B', zerolinecolor='#475569', range=[-10, 10]),
            yaxis=dict(gridcolor='#1E293B', zerolinecolor='#475569', range=[-15, 15]),
            showlegend=True,
            legend=dict(font=dict(size=10))
        )
        
        # Convert to PNG bytes
        img_bytes = pio.to_image(fig, format="png", width=600, height=400, scale=2)
        logger.info(f"Built cumulative graph with {len(cumulative_elements)} elements: {len(img_bytes)} bytes")
        return img_bytes
        
    except Exception as e:
        logger.error(f"Failed to build cumulative graph: {e}")
        return None


async def generate_step_visualizations(
    problem: str,
    topic: str,
    solution_steps: List[dict],
    function_expr: str = None
) -> dict:
    """
    Generate progressive cumulative visualizations for each step.
    Uses programmatic graph building instead of LLM code generation.
    
    Returns:
        dict: {step_number: image_url} for each step that needs visualization
    """
    logger.info(f"[ProgViz] Generating progressive visualizations for {len(solution_steps)} steps")
    
    # Filter steps that need visualization
    visual_steps = [s for s in solution_steps if s.get("needs_visual", False)]
    if not visual_steps:
        logger.info("[ProgViz] No steps need visualization")
        return {}
    
    logger.info(f"[ProgViz] {len(visual_steps)} steps need visualization")
    
    # Extract function expression from problem if not provided
    if not function_expr:
        import re
        match = re.search(r'f\s*\(\s*x\s*\)\s*=\s*([^\n]+)', problem)
        if match:
            function_expr = match.group(1).strip()
        else:
            function_expr = "x"  # fallback
    
    # Initialize cumulative elements
    cumulative_elements = []
    step_images = {}
    
    for step in solution_steps:
        if not step.get("needs_visual", False):
            continue
        
        step_num = step.get("step_number", 0)
        new_elements = step.get("visual_elements", [])
        
        # Skip if no new elements for this step (avoid empty graphs)
        if not new_elements and not cumulative_elements:
            logger.info(f"[ProgViz] Step {step_num}: skipping - no elements")
            continue
        
        # Add new elements to cumulative list
        cumulative_elements.extend(new_elements)
        
        logger.info(f"[ProgViz] Step {step_num}: building graph with {len(cumulative_elements)} cumulative elements")
        
        # Build the graph
        step_title = step.get("title", f"Step {step_num}")
        img_bytes = build_cumulative_graph(
            cumulative_elements=cumulative_elements,
            function_expr=function_expr,
            title=f"Step {step_num}: {step_title}",
            new_elements=new_elements,
            include_function=("function_curve" in new_elements or step_num == len(solution_steps))
        )
        
        if img_bytes:
            # Upload to storage
            problem_hash = hashlib.md5(f"{problem}_step{step_num}".encode()).hexdigest()[:12]
            image_url = await upload_to_gcs(img_bytes, problem_hash)
            step_images[step_num] = image_url
            logger.info(f"[ProgViz] Step {step_num} image generated successfully")
        else:
            logger.warning(f"[ProgViz] Step {step_num} failed to generate image")
    
    # Generate final complete graph
    if cumulative_elements:
        logger.info("[ProgViz] Generating final complete graph")
        
        final_bytes = build_cumulative_graph(
            cumulative_elements=cumulative_elements,
            function_expr=function_expr,
            title=f"Complete Graph: {topic}",
            include_function=True  # Always include function in final graph
        )
        
        if final_bytes:
            problem_hash = hashlib.md5(f"{problem}_final".encode()).hexdigest()[:12]
            final_url = await upload_to_gcs(final_bytes, problem_hash)
            step_images["final"] = final_url
            logger.info("[ProgViz] Final graph generated successfully")
    
    return step_images


# ============================================================================
# MAIN VISUALIZATION FUNCTION
# ============================================================================

async def generate_visualization(
    problem: str,
    topic: str,
    solution_steps: List[dict]
) -> VisualizationOutput:
    """
    Generate visualizations for a STEM problem using local Plotly execution.
    """
    # Check if visualization is needed
    if not should_visualize(problem, topic):
        logger.info("No visualization needed for this problem")
        return VisualizationOutput(
            needs_visualization=False,
            total_steps=0,
            steps=[],
            fallback_text_only=False
        )
    
    logger.info(f"Generating visualization for: {topic}")
    
    # Generate Plotly code using LLM
    client = genai.Client(api_key=settings.get_gemini_key)
    
    prompt = PLOTLY_PROMPT_TEMPLATE.format(
        problem=problem,
        topic=topic
    )
    
    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2)
        )
        
        plotly_code = response.text
        
        # Extract code from markdown if present
        if "```python" in plotly_code:
            import re
            code_match = re.search(r'```python\n(.*?)```', plotly_code, re.DOTALL)
            if code_match:
                plotly_code = code_match.group(1)
        elif "```" in plotly_code:
            import re
            code_match = re.search(r'```\n?(.*?)```', plotly_code, re.DOTALL)
            if code_match:
                plotly_code = code_match.group(1)
        
        logger.info(f"Generated Plotly code ({len(plotly_code)} chars)")
        
        # Execute the code locally
        image_bytes, retries = await execute_plotly_code(plotly_code)
        
        if image_bytes is None:
            logger.warning("Visualization failed, using text-only fallback")
            return VisualizationOutput(
                needs_visualization=True,
                total_steps=1,
                steps=[VisualizationStep(
                    step=1,
                    text=f"[Visualization unavailable] {topic}",
                    has_visual=False,
                    image_url=None,
                    alt_text="Graph generation failed after multiple attempts"
                )],
                fallback_text_only=True
            )
        
        # Upload to GCS
        problem_hash = hashlib.md5(problem.encode()).hexdigest()[:12]
        image_url = await upload_to_gcs(image_bytes, problem_hash)
        
        # Create visualization step
        viz_step = VisualizationStep(
            step=1,
            text=f"Visual representation of {topic}",
            has_visual=True,
            image_url=image_url,
            alt_text=f"Graph showing {topic}: {problem[:100]}"
        )
        
        logger.info(f"Visualization generated successfully (retries: {retries})")
        
        return VisualizationOutput(
            needs_visualization=True,
            total_steps=1,
            steps=[viz_step],
            fallback_text_only=False
        )
        
    except Exception as e:
        logger.error(f"Visualization generation failed: {e}")
        return VisualizationOutput(
            needs_visualization=True,
            total_steps=0,
            steps=[],
            fallback_text_only=True
        )


# ============================================================================
# CUMULATIVE PROGRESSIVE VISUALIZATION (NEW)
# ============================================================================

CUMULATIVE_GRAPH_PROMPT = """You are a visualization expert creating a cumulative graph for a math problem.

**Problem:** {problem}
**Function to graph:** {function_expr}

**Visual elements to include so far (ALL previous steps + this step):**
{cumulative_elements}

**NEW elements added in this step (highlight these in purple #9333EA):**
{new_elements}

**Requirements:**
1. Use plotly.graph_objects as `go`
2. Do NOT use plotly.express
3. Dark theme: background '#0B1220', grid '#1E293B'
4. Show ALL cumulative elements
5. Highlight NEW elements in purple (#9333EA), previous elements in grey (#6B7280)
6. Create a variable called `fig` that is the Plotly Figure
7. numpy is available as `np`

**Element types to handle:**
- vertical_asymptote_x=<val>: Add dashed vertical line at x=<val>
- x_intercept_(<x>,0): Add scatter point at (<x>, 0) 
- y_intercept_(0,<y>): Add scatter point at (0, <y>)
- oblique_asymptote_<expr>: Plot the asymptote curve in dashed line
- positive_region_(<start>,<end>): Shade green above x-axis
- negative_region_(<start>,<end>): Shade red below x-axis
- function_curve: Plot the actual function f(x)

Generate complete Plotly code."""


async def generate_cumulative_visualizations(
    problem: str,
    topic: str,
    solution_steps: List[dict],
    function_expr: str = None
) -> dict:
    """
    Generate cumulative progressive visualizations for each step with needs_visual=True.
    
    Returns:
        dict: {step_number: image_url} for each step that needs visualization
    """
    logger.info(f"[CumulativeViz] Starting for {len(solution_steps)} steps")
    
    # Filter steps that need visualization
    visual_steps = [s for s in solution_steps if s.get("needs_visual", False)]
    if not visual_steps:
        logger.info("[CumulativeViz] No steps need visualization")
        return {}
    
    logger.info(f"[CumulativeViz] {len(visual_steps)} steps need visualization")
    
    # Initialize cumulative elements
    cumulative_elements = []
    step_images = {}
    
    # Extract function expression from problem if not provided
    if not function_expr:
        import re
        # Try to extract f(x) = ... pattern
        match = re.search(r'f\s*\(\s*x\s*\)\s*=\s*([^\n]+)', problem)
        if match:
            function_expr = match.group(1).strip()
        else:
            function_expr = "unknown function"
    
    client = genai.Client(api_key=settings.get_gemini_key)
    
    for step in solution_steps:
        if not step.get("needs_visual", False):
            continue
        
        step_num = step.get("step_number", 0)
        new_elements = step.get("visual_elements", [])
        
        # Add new elements to cumulative list
        cumulative_elements.extend(new_elements)
        
        logger.info(f"[CumulativeViz] Step {step_num}: new={new_elements}, cumulative={cumulative_elements}")
        
        # Format elements for prompt
        cumulative_str = "\n".join([f"- {elem}" for elem in cumulative_elements]) or "None yet"
        new_str = "\n".join([f"- {elem}" for elem in new_elements]) or "None"
        
        prompt = CUMULATIVE_GRAPH_PROMPT.format(
            problem=problem,
            function_expr=function_expr,
            cumulative_elements=cumulative_str,
            new_elements=new_str
        )
        
        try:
            # Generate Plotly code via LLM
            response = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            
            plotly_code = response.text
            
            # Extract code from markdown if present
            if "```python" in plotly_code:
                import re
                code_match = re.search(r'```python\n(.*?)```', plotly_code, re.DOTALL)
                if code_match:
                    plotly_code = code_match.group(1)
            elif "```" in plotly_code:
                import re
                code_match = re.search(r'```\n?(.*?)```', plotly_code, re.DOTALL)
                if code_match:
                    plotly_code = code_match.group(1)
            
            # Execute the code
            image_bytes, retries = await execute_plotly_code(plotly_code)
            
            if image_bytes is not None:
                # Upload to storage
                problem_hash = hashlib.md5(f"{problem}_step{step_num}".encode()).hexdigest()[:12]
                image_url = await upload_to_gcs(image_bytes, problem_hash)
                step_images[step_num] = image_url
                logger.info(f"[CumulativeViz] Step {step_num} image generated successfully")
            else:
                logger.warning(f"[CumulativeViz] Step {step_num} failed to generate image")
                
        except Exception as e:
            logger.error(f"[CumulativeViz] Step {step_num} error: {e}")
    
    # Generate final complete graph
    if cumulative_elements:
        logger.info("[CumulativeViz] Generating final complete graph")
        cumulative_str = "\n".join([f"- {elem}" for elem in cumulative_elements])
        
        final_prompt = CUMULATIVE_GRAPH_PROMPT.format(
            problem=problem,
            function_expr=function_expr,
            cumulative_elements=cumulative_str,
            new_elements="ALL elements (this is the final complete graph)"
        )
        
        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=final_prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            
            plotly_code = response.text
            if "```python" in plotly_code:
                import re
                code_match = re.search(r'```python\n(.*?)```', plotly_code, re.DOTALL)
                if code_match:
                    plotly_code = code_match.group(1)
            
            image_bytes, _ = await execute_plotly_code(plotly_code)
            
            if image_bytes is not None:
                problem_hash = hashlib.md5(f"{problem}_final".encode()).hexdigest()[:12]
                final_url = await upload_to_gcs(image_bytes, problem_hash)
                step_images["final"] = final_url
                logger.info("[CumulativeViz] Final graph generated successfully")
                
        except Exception as e:
            logger.error(f"[CumulativeViz] Final graph error: {e}")
    
    return step_images
