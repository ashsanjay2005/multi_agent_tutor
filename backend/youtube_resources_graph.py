"""
LangGraph Workflow for YouTube Resource Discovery

This module implements a 3-node workflow:
1. ConceptExtractor - Extracts key mathematical concepts from the problem
2. ResourceRetriever - Searches YouTube for relevant tutorial videos
3. Summarizer - Generates relevance summaries for each video

The workflow supports pagination via an offset parameter for "Show 3 More" functionality.
"""

import os
import re
import logging
from typing import TypedDict, Optional
from pydantic import BaseModel, Field

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

from config import settings

logger = logging.getLogger(__name__)

# ============================================================================
# STATE DEFINITION
# ============================================================================

class YouTubeResourcesState(TypedDict):
    """State that flows through the YouTube resources workflow."""
    # Input
    problem_text: str
    topic: str
    offset: int  # For pagination (0, 3, 6, ...)
    
    # ConceptExtractor output
    key_concepts: list[str]
    search_queries: list[str]
    
    # ResourceRetriever output
    raw_videos: list[dict]  # [{video_id, title, thumbnail_url, youtube_url, description}]
    
    # Summarizer output
    annotated_videos: list[dict]  # raw_videos + relevance_summary


# ============================================================================
# PYDANTIC SCHEMAS FOR STRUCTURED OUTPUT
# ============================================================================

class ConceptExtractionResult(BaseModel):
    """Structured output for concept extraction."""
    key_concepts: list[str] = Field(
        description="2-4 key mathematical concepts from the problem (e.g., 'Adjoint Matrix', 'Determinant')"
    )
    search_queries: list[str] = Field(
        description="2-3 YouTube-optimized search queries (e.g., 'adjoint matrix tutorial', 'how to find matrix adjoint')"
    )


class VideoRelevanceSummary(BaseModel):
    """Structured output for a single video's relevance."""
    video_id: str
    relevance_summary: str = Field(
        description="1-2 sentence explanation of why this video helps with the problem"
    )


class BatchRelevanceSummaries(BaseModel):
    """Structured output for batch summarization."""
    summaries: list[VideoRelevanceSummary]


# ============================================================================
# NODE FUNCTIONS
# ============================================================================

def concept_extractor_node(state: YouTubeResourcesState) -> dict:
    """
    Extracts key mathematical concepts and generates YouTube search queries.
    Uses Gemini with structured output.
    """
    logger.info(f"[ConceptExtractor] Analyzing: {state['problem_text'][:50]}...")
    
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
        temperature=0.3,
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a STEM education specialist. Given a math problem and its topic, 
extract the key concepts and generate YouTube search queries that will find helpful tutorial videos.

Focus on:
- Core mathematical operations (e.g., "matrix adjoint", "cross product")
- General topic tutorials (e.g., "linear algebra matrices")
- Step-by-step guides (e.g., "how to find inverse matrix")

Make search queries natural and YouTube-friendly."""),
        ("human", """Problem: {problem_text}
Topic: {topic}

Extract key concepts and generate 2-3 search queries.""")
    ])
    
    chain = prompt | llm.with_structured_output(ConceptExtractionResult)
    
    try:
        result: ConceptExtractionResult = chain.invoke({
            "problem_text": state["problem_text"],
            "topic": state["topic"]
        })
        
        logger.info(f"[ConceptExtractor] Concepts: {result.key_concepts}")
        logger.info(f"[ConceptExtractor] Queries: {result.search_queries}")
        
        return {
            "key_concepts": result.key_concepts,
            "search_queries": result.search_queries
        }
    except Exception as e:
        logger.error(f"[ConceptExtractor] Error: {e}")
        # Fallback: use topic as search query
        fallback_query = state["topic"].replace(" - ", " ") + " tutorial"
        return {
            "key_concepts": [state["topic"].split(" - ")[-1]],
            "search_queries": [fallback_query]
        }


async def resource_retriever_node(state: YouTubeResourcesState) -> dict:
    """
    Searches for YouTube videos using web search (Tavily or fallback).
    Returns 3 videos starting from the offset.
    """
    import httpx
    
    logger.info(f"[ResourceRetriever] Searching with offset={state['offset']}")
    
    # We'll use a simple approach: search YouTube directly via web scraping simulation
    # In production, you'd use Tavily or YouTube Data API
    
    videos = []
    queries = state.get("search_queries", [])
    offset = state.get("offset", 0)
    
    # For MVP: Use a simulated search that returns placeholder data
    # Replace with actual Tavily/YouTube API in production
    
    try:
        # Try using Tavily if available
        tavily_api_key = os.environ.get("TAVILY_API_KEY", "")
        
        if tavily_api_key:
            from tavily import TavilyClient
            client = TavilyClient(api_key=tavily_api_key)
            
            for query in queries[:2]:  # Use first 2 queries
                search_query = f"site:youtube.com {query}"
                results = client.search(search_query, max_results=3)
                
                for r in results.get("results", []):
                    if "youtube.com/watch" in r.get("url", ""):
                        # Extract video ID from URL
                        url = r["url"]
                        video_id_match = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
                        if video_id_match:
                            video_id = video_id_match.group(1)
                            videos.append({
                                "video_id": video_id,
                                "title": r.get("title", ""),
                                "description": r.get("content", ""),
                                "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                                "youtube_url": f"https://www.youtube.com/watch?v={video_id}"
                            })
        else:
            # Fallback: Generate mock data for development
            logger.warning("[ResourceRetriever] No TAVILY_API_KEY, using mock data")
            
            topic_slug = state["topic"].lower().replace(" - ", "-").replace(" ", "-")
            for i in range(6):  # Generate enough for pagination
                videos.append({
                    "video_id": f"mock_{topic_slug}_{i}",
                    "title": f"{state['topic'].split(' - ')[-1]} Tutorial - Part {i + 1}",
                    "description": f"Learn about {state.get('key_concepts', ['this topic'])[0]} step by step.",
                    "thumbnail_url": f"https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
                    "youtube_url": f"https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                })
                
    except Exception as e:
        logger.error(f"[ResourceRetriever] Error: {e}")
        # Return empty on error
        return {"raw_videos": []}
    
    # Deduplicate by video_id
    seen_ids = set()
    unique_videos = []
    for v in videos:
        if v["video_id"] not in seen_ids:
            seen_ids.add(v["video_id"])
            unique_videos.append(v)
    
    # Apply offset and limit
    paginated_videos = unique_videos[offset:offset + 3]
    
    logger.info(f"[ResourceRetriever] Found {len(paginated_videos)} videos (offset={offset})")
    
    return {"raw_videos": paginated_videos}


def summarizer_node(state: YouTubeResourcesState) -> dict:
    """
    Generates relevance summaries for each video explaining why it helps with the problem.
    """
    raw_videos = state.get("raw_videos", [])
    
    if not raw_videos:
        logger.info("[Summarizer] No videos to summarize")
        return {"annotated_videos": []}
    
    logger.info(f"[Summarizer] Generating summaries for {len(raw_videos)} videos")
    
    llm = ChatGoogleGenerativeAI(
        model=settings.text_model,
        google_api_key=settings.google_api_key,
        temperature=0.5,
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a helpful tutor explaining why certain YouTube videos are relevant to a student's math problem.

For each video, write a brief 1-2 sentence summary explaining how it will help the student understand the problem better. Be specific and encouraging.

Example: "This video covers the fundamentals of matrix adjoints, which is exactly what you need to understand before solving this problem."
"""),
        ("human", """Problem: {problem_text}
Key concepts: {key_concepts}

Videos to summarize:
{videos_text}

Generate a relevance summary for each video.""")
    ])
    
    # Format videos for the prompt
    videos_text = "\n".join([
        f"- Video ID: {v['video_id']}, Title: {v['title']}, Description: {v.get('description', 'N/A')[:100]}"
        for v in raw_videos
    ])
    
    chain = prompt | llm.with_structured_output(BatchRelevanceSummaries)
    
    try:
        result: BatchRelevanceSummaries = chain.invoke({
            "problem_text": state["problem_text"],
            "key_concepts": ", ".join(state.get("key_concepts", [])),
            "videos_text": videos_text
        })
        
        # Merge summaries with raw videos
        summary_map = {s.video_id: s.relevance_summary for s in result.summaries}
        
        annotated = []
        for v in raw_videos:
            annotated.append({
                **v,
                "relevance_summary": summary_map.get(
                    v["video_id"], 
                    f"This video covers {state.get('key_concepts', ['the topic'])[0]} which is relevant to your problem."
                )
            })
        
        logger.info(f"[Summarizer] Generated {len(annotated)} annotated videos")
        return {"annotated_videos": annotated}
        
    except Exception as e:
        logger.error(f"[Summarizer] Error: {e}")
        # Fallback: add generic summaries
        annotated = []
        for v in raw_videos:
            annotated.append({
                **v,
                "relevance_summary": f"This video covers {state.get('key_concepts', ['the topic'])[0]} which may help with your problem."
            })
        return {"annotated_videos": annotated}


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

def create_youtube_resources_graph():
    """
    Creates and compiles the YouTube resources workflow graph.
    
    Flow: concept_extractor -> resource_retriever -> summarizer -> END
    """
    workflow = StateGraph(YouTubeResourcesState)
    
    # Add nodes
    workflow.add_node("concept_extractor", concept_extractor_node)
    workflow.add_node("resource_retriever", resource_retriever_node)
    workflow.add_node("summarizer", summarizer_node)
    
    # Define edges (linear flow)
    workflow.set_entry_point("concept_extractor")
    workflow.add_edge("concept_extractor", "resource_retriever")
    workflow.add_edge("resource_retriever", "summarizer")
    workflow.add_edge("summarizer", END)
    
    # Compile
    graph = workflow.compile()
    
    return graph


# Global instance for reuse
_youtube_graph = None

def get_youtube_graph():
    """Returns the compiled YouTube resources graph (singleton)."""
    global _youtube_graph
    if _youtube_graph is None:
        _youtube_graph = create_youtube_resources_graph()
    return _youtube_graph
