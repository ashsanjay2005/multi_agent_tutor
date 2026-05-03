"""
Visualization helpers for graphing-oriented tutor responses.

The graph solver marks individual solution steps with simple visual element
tokens. This module turns those tokens into Plotly PNGs and returns inline data
URLs so visualizations do not require another storage service.
"""

from __future__ import annotations

import asyncio
import ast
import base64
import logging
import operator
import re
from typing import Optional

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class VisualizationStep(BaseModel):
    step: int = Field(description="Step number")
    text: str = Field(description="Explanation with LaTeX")
    has_visual: bool = Field(description="Whether this step includes a graph")
    image_url: Optional[str] = Field(default=None, description="Inline PNG data URL")
    alt_text: Optional[str] = Field(default=None, description="Accessibility description")


class VisualizationOutput(BaseModel):
    needs_visualization: bool
    total_steps: int
    steps: list[VisualizationStep] = Field(default_factory=list)
    fallback_text_only: bool = False


VISUAL_KEYWORDS = {
    "graph", "plot", "sketch", "draw", "curve",
    "coordinate", "plane", "intercept", "asymptote",
}

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCS = {
    "abs": np.abs,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "sqrt": np.sqrt,
    "log": np.log,
    "ln": np.log,
    "exp": np.exp,
}
_ALLOWED_CONSTANTS = {
    "pi": np.pi,
    "e": np.e,
}


def should_visualize(problem: str, topic: str) -> bool:
    problem_lower = problem.lower()
    topic_lower = (topic or "").lower()
    if any(keyword in problem_lower or keyword in topic_lower for keyword in VISUAL_KEYWORDS):
        return True
    return bool(re.search(
        r"\b(?:graph|plot|sketch|draw)\b.*(?:y\s*=|f\s*\(\s*x\s*\)\s*=)|\b(?:graph|plot)\s+of\b",
        problem_lower,
    ))


def _png_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_visual_element(element: str) -> dict:
    match = re.match(r"vertical_asymptote_x=(.+)", element)
    if match and (x := _to_float(match.group(1))) is not None:
        return {"type": "vertical_asymptote", "data": {"x": x}}

    match = re.match(r"horizontal_asymptote_y=(.+)", element)
    if match and (y := _to_float(match.group(1))) is not None:
        return {"type": "horizontal_asymptote", "data": {"y": y}}

    match = re.match(r"oblique_asymptote_(?:y=)?(.+)", element)
    if match:
        return {"type": "oblique_asymptote", "data": {"expr": match.group(1)}}

    match = re.match(r"x_intercept_\(([^,]+),\s*0\)", element)
    if match and (x := _to_float(match.group(1))) is not None:
        return {"type": "x_intercept", "data": {"x": x}}

    match = re.match(r"y_intercept_\(0,\s*([^)]+)\)", element)
    if match and (y := _to_float(match.group(1))) is not None:
        return {"type": "y_intercept", "data": {"y": y}}

    match = re.match(r"point_\(([^,]+),\s*([^)]+)\)", element)
    if match:
        x = _to_float(match.group(1))
        y = _to_float(match.group(2))
        if x is not None and y is not None:
            return {"type": "point", "data": {"x": x, "y": y}}

    match = re.match(r"positive_region_\(([^,]+),\s*([^)]+)\)", element)
    if match:
        return {"type": "positive_region", "data": {"start": match.group(1), "end": match.group(2)}}

    match = re.match(r"negative_region_\(([^,]+),\s*([^)]+)\)", element)
    if match:
        return {"type": "negative_region", "data": {"start": match.group(1), "end": match.group(2)}}

    if element == "function_curve":
        return {"type": "function_curve", "data": {}}

    return {"type": None, "data": {}}


def _normalize_expression(expression: str) -> str:
    expr = expression.strip()
    expr = expr.replace("^", "**")
    expr = expr.replace("−", "-")
    expr = re.sub(r"(\d)([x(])", r"\1*\2", expr)
    expr = re.sub(r"\)(\d|x)", r")*\1", expr)
    expr = re.sub(r"(x)\(", r"\1*(", expr)
    return expr


def _eval_ast(node: ast.AST, x: np.ndarray):
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, x)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id == "x":
            return x
        if node.id in _ALLOWED_CONSTANTS:
            return _ALLOWED_CONSTANTS[node.id]
        raise ValueError(f"Unsupported name: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _eval_ast(node.left, x)
        right = _eval_ast(node.right, x)
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_ast(node.operand, x))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        func = _ALLOWED_FUNCS.get(node.func.id)
        if func is None or node.keywords:
            raise ValueError(f"Unsupported function: {node.func.id}")
        return func(*[_eval_ast(arg, x) for arg in node.args])
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def _eval_expression(expression: str, x: np.ndarray) -> Optional[np.ndarray]:
    try:
        parsed = ast.parse(_normalize_expression(expression), mode="eval")
        y = np.asarray(_eval_ast(parsed, x), dtype=float)
        if y.shape == ():
            y = np.full_like(x, float(y))
        return np.where(np.abs(y) > 50, np.nan, y)
    except Exception as e:
        logger.debug(f"Could not evaluate graph expression '{expression}': {e}")
        return None


def _range_endpoint(value: str) -> float:
    if value in {"-inf", "-infty", "-∞"}:
        return -10
    if value in {"inf", "infty", "∞"}:
        return 10
    return float(value)


def _extract_function_expression(problem: str) -> str:
    patterns = [
        r"f\s*\(\s*x\s*\)\s*=\s*([^\n,;]+)",
        r"y\s*=\s*([^\n,;]+)",
        r"graph(?:\s+of)?\s+([^\n,;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, problem, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "x"


def build_cumulative_graph(
    cumulative_elements: list[str],
    function_expr: str,
    title: str = "Graph",
    new_elements: list[str] | None = None,
    include_function: bool = False,
) -> Optional[bytes]:
    try:
        fig = go.Figure()
        x = np.linspace(-10, 10, 1000)
        parsed_elements = [parse_visual_element(e) for e in cumulative_elements]
        has_function_curve = any(e.get("type") == "function_curve" for e in parsed_elements)

        y = _eval_expression(function_expr, x)
        if y is not None and (include_function or has_function_curve):
            fig.add_trace(go.Scatter(
                x=x,
                y=y,
                mode="lines",
                name="f(x)",
                line=dict(color="#9333EA", width=2.5),
            ))

        new_element_set = set(new_elements or [])
        for elem_str in cumulative_elements:
            parsed = parse_visual_element(elem_str)
            elem_type = parsed.get("type")
            data = parsed.get("data", {})
            color = "#9333EA" if elem_str in new_element_set else "#6B7280"

            if elem_type == "vertical_asymptote":
                fig.add_vline(x=data["x"], line_dash="dash", line_color="#F97316", annotation_text=f"x={data['x']}")
            elif elem_type == "horizontal_asymptote":
                fig.add_hline(y=data["y"], line_dash="dash", line_color="#10B981", annotation_text=f"y={data['y']}")
            elif elem_type == "oblique_asymptote":
                y_asymptote = _eval_expression(data["expr"], x)
                if y_asymptote is not None:
                    fig.add_trace(go.Scatter(
                        x=x,
                        y=y_asymptote,
                        mode="lines",
                        name=f"y={data['expr']}",
                        line=dict(color="#22C55E", width=2, dash="dash"),
                    ))
            elif elem_type == "x_intercept":
                fig.add_trace(go.Scatter(
                    x=[data["x"]],
                    y=[0],
                    mode="markers",
                    name=f"x-int ({data['x']}, 0)",
                    marker=dict(color="#EF4444", size=10),
                ))
            elif elem_type == "y_intercept":
                fig.add_trace(go.Scatter(
                    x=[0],
                    y=[data["y"]],
                    mode="markers",
                    name=f"y-int (0, {data['y']})",
                    marker=dict(color="#3B82F6", size=10),
                ))
            elif elem_type == "point":
                fig.add_trace(go.Scatter(
                    x=[data["x"]],
                    y=[data["y"]],
                    mode="markers",
                    name=f"({data['x']}, {data['y']})",
                    marker=dict(color=color, size=8),
                ))
            elif elem_type in {"positive_region", "negative_region"}:
                try:
                    fill = "rgba(34, 197, 94, 0.12)" if elem_type == "positive_region" else "rgba(239, 68, 68, 0.12)"
                    fig.add_vrect(
                        x0=_range_endpoint(data["start"]),
                        x1=_range_endpoint(data["end"]),
                        fillcolor=fill,
                        layer="below",
                        line_width=0,
                    )
                except ValueError:
                    logger.debug(f"Could not parse region bounds for {elem_str}")

        fig.update_layout(
            title=title,
            xaxis_title="x",
            yaxis_title="y",
            plot_bgcolor="#0B1220",
            paper_bgcolor="#0B1220",
            font=dict(color="white"),
            xaxis=dict(gridcolor="#1E293B", zerolinecolor="#475569", range=[-10, 10]),
            yaxis=dict(gridcolor="#1E293B", zerolinecolor="#475569", range=[-15, 15]),
            showlegend=True,
            legend=dict(font=dict(size=10)),
            margin=dict(l=40, r=20, t=60, b=40),
        )
        return pio.to_image(fig, format="png", width=600, height=400, scale=2)
    except Exception as e:
        logger.warning(f"Failed to build visualization graph: {e}")
        return None


async def generate_step_visualizations(
    problem: str,
    topic: str,
    solution_steps: list[dict],
    function_expr: str | None = None,
) -> dict:
    logger.info(f"[Visualization] Generating progressive visuals for {len(solution_steps)} steps")
    visual_steps = [step for step in solution_steps if step.get("needs_visual")]
    if not visual_steps:
        return {}

    expression = function_expr or _extract_function_expression(problem)
    cumulative_elements: list[str] = []
    step_images: dict = {}

    for step in solution_steps:
        if not step.get("needs_visual"):
            continue
        step_number = step.get("step_number", 0)
        new_elements = step.get("visual_elements", []) or []
        cumulative_elements.extend(new_elements)
        if not cumulative_elements:
            continue

        image_bytes = build_cumulative_graph(
            cumulative_elements=cumulative_elements,
            function_expr=expression,
            title=f"Step {step_number}: {step.get('title', 'Graph')}",
            new_elements=new_elements,
            include_function=("function_curve" in new_elements or step_number == len(solution_steps)),
        )
        if image_bytes:
            step_images[step_number] = _png_data_url(image_bytes)

    if cumulative_elements:
        final_bytes = build_cumulative_graph(
            cumulative_elements=cumulative_elements,
            function_expr=expression,
            title=f"Complete Graph: {topic}",
            include_function=True,
        )
        if final_bytes:
            step_images["final"] = _png_data_url(final_bytes)

    return step_images


async def generate_visualization(problem: str, topic: str, solution_steps: list[dict]) -> VisualizationOutput:
    if not should_visualize(problem, topic):
        return VisualizationOutput(needs_visualization=False, total_steps=0)

    loop = asyncio.get_event_loop()
    image_bytes = await loop.run_in_executor(
        None,
        build_cumulative_graph,
        ["function_curve"],
        _extract_function_expression(problem),
        f"Graph: {topic}",
        ["function_curve"],
        True,
    )
    if not image_bytes:
        return VisualizationOutput(needs_visualization=True, total_steps=0, fallback_text_only=True)

    return VisualizationOutput(
        needs_visualization=True,
        total_steps=1,
        steps=[
            VisualizationStep(
                step=1,
                text=f"Visual representation of {topic}",
                has_visual=True,
                image_url=_png_data_url(image_bytes),
                alt_text=f"Graph for {topic}",
            )
        ],
    )
