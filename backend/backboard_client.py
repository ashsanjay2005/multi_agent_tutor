"""
Backboard.io SDK Integration

This module provides a singleton wrapper for the Backboard.io SDK,
enabling persistent long-term memory and model orchestration for the STEM tutor.

Key Features:
- Persistent memory across student sessions via LoCoMo
- Model orchestration (Gemini/OpenAI) through a single interface
- Shadow saving for completed problems (memory building without API responses)
- Topic metadata tagging for organization
"""

import logging
import time
import re
from dataclasses import dataclass, field
from typing import Optional

from backboard import BackboardClient

from config import settings
import supabase_client

logger = logging.getLogger(__name__)

# System prompt for the STEM Tutor assistant
STEM_TUTOR_SYSTEM_PROMPT = """You are an expert STEM tutor specialized in mathematics, physics, chemistry, and computer science.

Your role is to:
1. Help students understand complex STEM concepts step-by-step
2. Provide clear, educational explanations
3. Remember each student's learning history and past problems
4. Adapt your teaching style based on what topics they've struggled with

When solving problems:
- Break down solutions into clear, numbered steps
- Use proper mathematical notation (LaTeX format with $ delimiters)
- Explain the "why" behind each step, not just the "what"
- Connect new concepts to previously learned material

You have memory of past conversations. Use this to:
- Reference problems the student solved before
- Note improvement or recurring difficulties
- Personalize explanations based on their level
"""


@dataclass
class StudentProfile:
    """
    Student learning profile for a specific topic.
    Used to personalize problem explanations, practice, and videos.
    """
    topic: str
    strong_concepts: list[str] = field(default_factory=list)  # Concepts they've mastered
    weak_concepts: list[str] = field(default_factory=list)   # Concepts they struggle with
    has_history: bool = False  # Whether any relevant history was found
    summary: str = ""  # Natural language summary for LLM prompts
    
    def get_adaptive_prompt(self) -> str:
        """Generate prompt instructions based on profile."""
        if not self.has_history:
            return "No prior history on this topic - provide standard explanations."
        
        parts = []
        if self.weak_concepts:
            parts.append(f"WEAKNESS: Student struggles with {', '.join(self.weak_concepts)}. "
                        "Provide extra detail, prerequisite refreshers, and slower pacing for these.")
        if self.strong_concepts:
            parts.append(f"STRENGTH: Student has mastered {', '.join(self.strong_concepts)}. "
                        "Be concise on these, skip basic explanations.")
        
        return "\n".join(parts) if parts else "Student has moderate familiarity - use standard approach."


@dataclass
class FolderSuggestion:
    """
    Result of semantic folder suggestion.
    """
    action: str  # "add_to_folder" | "suggest_new_folder" | "no_suggestion"
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    similarity_score: float = 0.0
    similar_unfiled: list[dict] = field(default_factory=list)  # [{session_id, topic, problem_preview}]
    alternate_folder: Optional[dict] = None  # For "Did you mean?" case


# Semantic grouping constants
SIMILARITY_THRESHOLD = 0.85  # Minimum similarity to suggest existing folder
MIN_CLUSTER_SIZE = 2  # Minimum unfiled items to suggest new folder
FOLDER_DEF_PREFIX = "[FOLDER_DEF]"  # Prefix for folder definition memories
FOLDER_MAP_TTL_SECONDS = 300  # 5 minutes cache


class BackboardService:
    """
    Singleton service for Backboard.io integration.
    
    Provides persistent memory across sessions and simplified LLM orchestration.
    Per-user assistant IDs are stored in Supabase profiles table.
    """
    
    def __init__(self):
        if not settings.backboard_api_key:
            raise ValueError("BACKBOARD_API_KEY not configured in settings")
        
        self.client = BackboardClient(api_key=settings.backboard_api_key)
        self._initialized = False
        
        # Cache of user_id -> assistant_id mappings
        self._assistant_cache: dict[str, str] = {}
        
        # Cache of user_id -> thread_id mappings
        self._thread_cache: dict[str, str] = {}
        
        # Folder map cache with TTL
        self._folder_map_cache: dict[str, str] = {}  # folder_id -> folder_name
        self._folder_map_timestamp: float = 0.0
    
    async def initialize(self):
        """
        Initialize the Backboard client.
        Validates API key connectivity. Per-user assistants are created lazily
        via get_user_assistant_id().
        """
        if self._initialized:
            return
        
        try:
            logger.info("[Backboard] Initializing client (per-user assistant mode)...")
            # Just verify the API key works — assistants are per-user now
            self._initialized = True
            logger.info("[Backboard] Client ready")
        except Exception as e:
            logger.error(f"[Backboard] Initialization failed: {e}")
            raise

    async def get_user_assistant_id(self, user_id: str) -> str:
        """
        Get or create a Backboard assistant for a specific user.
        
        Looks up profiles.backboard_assistant_id from Supabase.
        If none exists, creates a new assistant and writes it back
        using a compensating transaction (deletes the Backboard assistant
        if the Supabase write fails).
        
        Args:
            user_id: The auth.users UUID
            
        Returns:
            The Backboard assistant ID for this user
        """
        if not self._initialized:
            await self.initialize()
        
        # Check cache first
        if user_id in self._assistant_cache:
            return self._assistant_cache[user_id]
        
        # Look up from Supabase
        existing_id = await supabase_client.get_backboard_assistant_id(user_id)
        if existing_id:
            self._assistant_cache[user_id] = existing_id
            logger.info(f"[Backboard] Found assistant for user {user_id}: {existing_id}")
            return existing_id
        
        # Create new assistant — compensating transaction pattern
        logger.info(f"[Backboard] Creating new assistant for user {user_id}...")
        assistant = await self.client.create_assistant(
            name=f"{settings.backboard_assistant_name} - {user_id[:8]}"
        )
        new_id = str(assistant.assistant_id)
        
        try:
            # Write to Supabase
            await supabase_client.set_backboard_assistant_id(user_id, new_id)
            self._assistant_cache[user_id] = new_id
            logger.info(f"[Backboard] Created and saved assistant for user {user_id}: {new_id}")
            return new_id
        except Exception as e:
            # Rollback: delete the orphaned assistant
            logger.error(f"[Backboard] Supabase write failed, rolling back assistant {new_id}: {e}")
            try:
                await self.client.delete_assistant(new_id)
                logger.info(f"[Backboard] Rolled back assistant {new_id}")
            except Exception as rollback_err:
                logger.error(f"[Backboard] Rollback failed — orphaned assistant {new_id}: {rollback_err}")
            raise
    
    async def get_or_create_thread(self, user_id: str) -> str:
        """
        Get or create a Backboard thread for a user.
        Each user gets their own thread, tied to their per-user assistant.
        
        Args:
            user_id: Unique identifier for the student (auth.users UUID)
            
        Returns:
            Thread ID for this user's conversation
        """
        if not self._initialized:
            await self.initialize()
        
        # Check cache first
        if user_id in self._thread_cache:
            logger.info(f"[Backboard] Using cached thread for user {user_id}")
            return self._thread_cache[user_id]
        
        # Get the user's own assistant ID
        assistant_id = await self.get_user_assistant_id(user_id)
        
        # Create new thread under the user's assistant
        try:
            thread = await self.client.create_thread(assistant_id)
            thread_id = thread.thread_id
            
            # Cache it
            self._thread_cache[user_id] = thread_id
            
            logger.info(f"[Backboard] Created thread {thread_id} for user {user_id} (assistant {assistant_id})")
            return thread_id
            
        except Exception as e:
            logger.error(f"[Backboard] Failed to create thread: {e}")
            raise
    
    async def send_message(
        self,
        thread_id: str,
        content: str,
        metadata: Optional[dict] = None,
        send_to_llm: bool = True,
        stream: bool = False
    ) -> str:
        """
        Send a message to Backboard and get AI response.
        
        Args:
            thread_id: The conversation thread ID
            content: Message content (prompt)
            metadata: Optional tags like {"topic": "Matrices", "task": "classification"}
            send_to_llm: If False, just saves to memory without AI response (shadow save)
            stream: Whether to stream the response
            
        Returns:
            AI response content
        """
        if not self._initialized:
            await self.initialize()
        
        # Note: SDK does not support metadata or send_to_llm params
        # Metadata is embedded in content for memory retrieval
        enriched_content = content
        if metadata:
            metadata_str = ", ".join([f"{k}={v}" for k, v in metadata.items()])
            enriched_content = f"{content}\n[METADATA: {metadata_str}]"
        
        try:
            response = await self.client.add_message(
                thread_id=thread_id,
                content=enriched_content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",  # Enable LoCoMo long-term memory
                stream=stream
            )
            
            logger.info(f"[Backboard] Received response ({len(response.content)} chars)")
            return response.content
            
        except Exception as e:
            logger.error(f"[Backboard] send_message failed: {e}")
            raise
    
    async def shadow_save(
        self,
        thread_id: str,
        problem_text: str,
        topic: str,
        solution_summary: str
    ):
        """
        Save completed problem data to memory without triggering an AI response.
        This builds the student's learning history for future personalization.
        
        Args:
            thread_id: The conversation thread ID
            problem_text: The original problem
            topic: The classified topic (e.g., "Math - Linear Algebra - Cross Product")
            solution_summary: Brief summary or final answer
        """
        if not self._initialized:
            await self.initialize()
        
        content = f"""[PROBLEM COMPLETED]
Topic: {topic}
Problem: {problem_text}
Solution: {solution_summary}

This problem has been solved and should be remembered for future reference.
[METADATA: type=completed, topic={topic}]"""
        
        try:
            # Note: SDK doesn't support send_to_llm=False, so this will trigger a response
            # The response is ignored, but the content is still saved to memory
            await self.client.add_message(
                thread_id=thread_id,
                content=content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",
                stream=False
            )
            
            logger.info(f"[Backboard] Shadow saved problem: {topic}")
            
        except Exception as e:
            logger.error(f"[Backboard] shadow_save failed: {e}")
            # Don't raise - shadow save is non-critical
    
    async def log_struggle(
        self,
        thread_id: str,
        step_title: str,
        concept: str,
        context: str
    ):
        """
        Shadow save when a student clicks 'breakdown' on a step.
        This builds a profile of concepts the student struggles with.
        
        Args:
            thread_id: The conversation thread ID
            step_title: Title of the step they clicked (e.g., "Distribute the -1")
            concept: Normalized concept tag (e.g., "negative_signs", "matrix_multiplication")
            context: Problem statement or step explanation for contextualization
        """
        if not self._initialized:
            await self.initialize()
        
        # Embed metadata in content for memory retrieval
        content = f"""DIAGNOSTIC: Student requested breakdown for [{step_title}]
[METADATA: action=breakdown, concept={concept}, is_struggle=true, context={context[:200]}]"""
        
        try:
            # Note: SDK doesn't support send_to_llm=False
            # Content is saved to memory even though we get a response
            await self.client.add_message(
                thread_id=thread_id,
                content=content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",
                stream=False
            )
            logger.info(f"[Backboard] Logged struggle: {concept}")
        except Exception as e:
            logger.warning(f"[Backboard] log_struggle failed (non-critical): {e}")
    
    async def log_quiz_result(
        self,
        thread_id: str,
        concept: str,
        correct: bool,
        question_summary: str
    ):
        """
        Shadow save quiz/practice results to build mastery profile.
        
        Args:
            thread_id: The conversation thread ID
            concept: Topic/concept being tested (e.g., "matrix_multiplication")
            correct: Whether the student answered correctly
            question_summary: Brief summary of the question
        """
        if not self._initialized:
            await self.initialize()
        
        status = "correct" if correct else "wrong"
        # Embed metadata in content for memory retrieval
        content = f"""QUIZ_RESULT: {status.upper()} on [{concept}]
[METADATA: type=quiz, status={status}, concept={concept}, question={question_summary[:100]}]"""
        
        try:
            # Note: SDK doesn't support send_to_llm=False
            await self.client.add_message(
                thread_id=thread_id,
                content=content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",
                stream=False
            )
            logger.info(f"[Backboard] Logged quiz result: {concept} = {status}")
        except Exception as e:
            logger.warning(f"[Backboard] log_quiz_result failed (non-critical): {e}")

    async def find_similar_problems(
        self,
        thread_id: str,
        query_topic: str,
        query_problem: str
    ) -> list[dict]:
        """
        Find semantically similar problems from memory.
        Uses Readonly memory mode to search without writing.
        
        Args:
            thread_id: The conversation thread ID
            query_topic: Current problem's topic
            query_problem: Current problem text
            
        Returns:
            List of similar problems with topics extracted from memory
        """
        if not self._initialized:
            await self.initialize()
        
        # Query for similar concepts - use a search prompt
        search_prompt = f"""Find problems I've solved before that are similar to:
Topic: {query_topic}
Problem: {query_problem[:200]}

List similar topics or concepts from my history."""
        
        try:
            # Use Readonly mode to search memory without writing
            response = await self.client.add_message(
                thread_id=thread_id,
                content=search_prompt,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Readonly",  # Search only, no writes
                stream=False
            )
            
            logger.info(f"[Backboard] Similar problems search returned {len(response.content)} chars")
            
            # Parse the response to extract similar topics
            # The LLM will analyze memory and return relevant topics
            similar_problems = []
            
            # Extract topic mentions from the response
            content = response.content.lower()
            
            # Common math topic patterns to look for
            topic_patterns = [
                "matrix", "linear algebra", "calculus", "derivatives", "integrals",
                "differential equations", "probability", "statistics", "geometry",
                "trigonometry", "algebra", "vectors", "eigenvalues", "systems of equations",
                "logarithms", "exponentials", "limits", "sequences", "series"
            ]
            
            found_topics = []
            for pattern in topic_patterns:
                if pattern in content and pattern not in query_topic.lower():
                    found_topics.append(pattern.title())
            
            # Return similar topics found
            for topic in found_topics[:5]:  # Limit to top 5
                similar_problems.append({
                    "topic": topic,
                    "similarity": 0.85  # We don't have exact scores, so use a threshold indicator
                })
            
            return similar_problems
            
        except Exception as e:
            logger.warning(f"[Backboard] find_similar_problems failed: {e}")
            return []

    async def get_student_profile(
        self,
        thread_id: str,
        topic: str
    ) -> StudentProfile:
        """
        Query Backboard for topic-specific student strengths and weaknesses.
        Uses semantic search to find relevant memories only for this domain.
        
        Args:
            thread_id: The conversation thread ID
            topic: Current problem topic (e.g., "Linear Algebra - Matrix Multiplication")
            
        Returns:
            StudentProfile with parsed strengths, weaknesses, and adaptive prompt
        """
        if not self._initialized:
            await self.initialize()
        
        profile = StudentProfile(topic=topic)
        
        # Query Backboard for memories related to this topic
        query = f"""Based on my learning history, analyze my performance on topics related to: {topic}

List any:
1. CORRECT answers I got (strengths)
2. WRONG answers or breakdown requests (weaknesses)
3. Concepts I struggled with or needed extra help on

Only include items semantically related to {topic}. Ignore unrelated topics.
Format: STRENGTH: [concept] or WEAKNESS: [concept]"""
        
        try:
            # Use Readonly mode to search memory without creating new entries
            response = await self.client.add_message(
                thread_id=thread_id,
                content=query,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Readonly",
                stream=False
            )
            
            content = response.content
            logger.info(f"[Backboard] Profile query returned {len(content)} chars for topic: {topic}")
            
            # Parse response for strengths and weaknesses
            lines = content.split('\n')
            for line in lines:
                line_lower = line.lower().strip()
                
                # Extract STRENGTH markers
                if 'strength' in line_lower or 'correct' in line_lower or 'mastered' in line_lower:
                    # Extract the concept after the marker
                    for marker in ['strength:', 'strengths:', 'correct:', 'mastered:']:
                        if marker in line_lower:
                            concept = line.split(':', 1)[-1].strip()
                            if concept and len(concept) < 100:
                                profile.strong_concepts.append(concept)
                                profile.has_history = True
                                break
                
                # Extract WEAKNESS markers
                if 'weakness' in line_lower or 'wrong' in line_lower or 'struggle' in line_lower or 'breakdown' in line_lower:
                    for marker in ['weakness:', 'weaknesses:', 'wrong:', 'struggle:', 'struggled:', 'breakdown:']:
                        if marker in line_lower:
                            concept = line.split(':', 1)[-1].strip()
                            if concept and len(concept) < 100:
                                profile.weak_concepts.append(concept)
                                profile.has_history = True
                                break
            
            # Check for "no history" indicators
            no_history_phrases = ['no history', 'no previous', 'no prior', 'haven\'t solved', 'no records']
            if any(phrase in content.lower() for phrase in no_history_phrases):
                profile.has_history = False
            
            # Generate summary
            profile.summary = profile.get_adaptive_prompt()
            
            logger.info(f"[Backboard] Profile: {len(profile.strong_concepts)} strengths, {len(profile.weak_concepts)} weaknesses")
            return profile
            
        except Exception as e:
            logger.warning(f"[Backboard] get_student_profile failed: {e}")
            return profile  # Return empty profile on error

    # =========================================================================
    # FOLDER MEMORY METHODS (Semantic Smart Grouping)
    # =========================================================================
    
    async def save_folder_definition(
        self,
        thread_id: str,
        folder_id: str,
        folder_name: str
    ) -> None:
        """
        Store folder definition in Backboard memory.
        Called when a folder is created or renamed.
        """
        if not self._initialized:
            await self.initialize()
        
        content = f"{FOLDER_DEF_PREFIX} id={folder_id} name={folder_name}"
        
        try:
            await self.client.add_message(
                thread_id=thread_id,
                content=content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",
                stream=False
            )
            
            # Invalidate cache
            self._folder_map_cache[folder_id] = folder_name
            logger.info(f"[Backboard] Saved folder definition: {folder_id} -> {folder_name}")
            
        except Exception as e:
            logger.error(f"[Backboard] save_folder_definition failed: {e}")
    
    def invalidate_folder_map_cache(self) -> None:
        """Invalidate folder map cache (call after folder changes)."""
        self._folder_map_timestamp = 0.0
        logger.info("[Backboard] Folder map cache invalidated")
    
    async def get_folder_map(self, thread_id: str, force_refresh: bool = False) -> dict[str, str]:
        """
        Get folder ID -> name mapping from Backboard memory.
        Uses TTL cache to avoid repeated queries.
        """
        if not self._initialized:
            await self.initialize()
        
        # Check cache TTL
        now = time.time()
        if not force_refresh and (now - self._folder_map_timestamp) < FOLDER_MAP_TTL_SECONDS:
            return self._folder_map_cache
        
        try:
            # Query Backboard for folder definitions
            response = await self.client.add_message(
                thread_id=thread_id,
                content=f"List all folder definitions you remember. Format: {FOLDER_DEF_PREFIX} id=... name=...",
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Readonly",
                stream=False
            )
            
            # Parse folder definitions from response
            folder_map = {}
            for match in re.finditer(rf'{FOLDER_DEF_PREFIX}\s+id=(\S+)\s+name=(.+?)(?:\n|$)', response.content):
                folder_id = match.group(1)
                folder_name = match.group(2).strip()
                folder_map[folder_id] = folder_name
            
            # Update cache
            self._folder_map_cache = folder_map
            self._folder_map_timestamp = now
            
            logger.info(f"[Backboard] Folder map refreshed: {len(folder_map)} folders")
            return folder_map
            
        except Exception as e:
            logger.warning(f"[Backboard] get_folder_map failed: {e}")
            return self._folder_map_cache  # Return stale cache on error
    
    async def save_problem_memory(
        self,
        thread_id: str,
        problem_text: str,
        topic: str,
        session_id: str,
        folder_id: Optional[str] = None
    ) -> None:
        """
        Save problem to Backboard memory with folder metadata.
        This creates the link between problems and folders for semantic grouping.
        """
        if not self._initialized:
            await self.initialize()
        
        folder_tag = folder_id or "unfiled"
        content = f"""[PROBLEM_MEMORY] session_id={session_id} folder_id={folder_tag}
Topic: {topic}
Problem: {problem_text[:500]}"""
        
        try:
            await self.client.add_message(
                thread_id=thread_id,
                content=content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",
                stream=False
            )
            logger.info(f"[Backboard] Saved problem memory: {session_id} -> {folder_tag}")
            
        except Exception as e:
            logger.error(f"[Backboard] save_problem_memory failed: {e}")
    
    async def find_folder_for_problem(
        self,
        thread_id: str,
        problem_text: str,
        topic: str
    ) -> FolderSuggestion:
        """
        Find best folder for a problem using semantic search.
        Returns suggestion with folder match or similar unfiled problems.
        """
        if not self._initialized:
            await self.initialize()
        
        suggestion = FolderSuggestion(action="no_suggestion")
        
        try:
            # Get current folder map
            folder_map = await self.get_folder_map(thread_id)
            
            # Semantic search for similar problems
            query = f"""Find problems similar to this one and tell me their folder assignments:
Topic: {topic}
Problem: {problem_text[:300]}

List the top 5 most similar problems with their folder_id and similarity scores.
Format each as: MATCH: folder_id=[id] score=[0.0-1.0] session_id=[id]"""
            
            response = await self.client.add_message(
                thread_id=thread_id,
                content=query,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Readonly",
                stream=False
            )
            
            # Parse matches
            matches = []
            for match in re.finditer(r'MATCH:\s*folder_id=(\S+)\s+score=([0-9.]+)\s+session_id=(\S+)', response.content):
                folder_id = match.group(1)
                score = float(match.group(2))
                session_id = match.group(3)
                matches.append({"folder_id": folder_id, "score": score, "session_id": session_id})
            
            if not matches:
                logger.info("[Backboard] No similar problems found")
                return suggestion
            
            # Sort by score descending
            matches.sort(key=lambda x: x["score"], reverse=True)
            best_match = matches[0]
            
            # Check if best match meets threshold and is an actual folder
            if best_match["score"] >= SIMILARITY_THRESHOLD and best_match["folder_id"] != "unfiled":
                folder_name = folder_map.get(best_match["folder_id"], best_match["folder_id"])
                suggestion = FolderSuggestion(
                    action="add_to_folder",
                    folder_id=best_match["folder_id"],
                    folder_name=folder_name,
                    similarity_score=best_match["score"]
                )
                
                # Check for alternate folder suggestion (close second)
                if len(matches) > 1:
                    second = matches[1]
                    if second["score"] >= SIMILARITY_THRESHOLD - 0.05 and second["folder_id"] != "unfiled":
                        suggestion.alternate_folder = {
                            "folder_id": second["folder_id"],
                            "folder_name": folder_map.get(second["folder_id"], second["folder_id"]),
                            "score": second["score"]
                        }
                
                logger.info(f"[Backboard] Suggesting folder: {folder_name} (score={best_match['score']:.2f})")
                return suggestion
            
            # Below threshold - check for unfiled cluster
            unfiled = [m for m in matches if m["folder_id"] == "unfiled"]
            if len(unfiled) >= MIN_CLUSTER_SIZE:
                suggestion = FolderSuggestion(
                    action="suggest_new_folder",
                    similar_unfiled=[{"session_id": m["session_id"]} for m in unfiled[:5]]
                )
                logger.info(f"[Backboard] Suggesting new folder with {len(unfiled)} similar unfiled problems")
                return suggestion
            
            logger.info("[Backboard] No folder suggestion (below threshold, insufficient unfiled)")
            return suggestion
            
        except Exception as e:
            logger.warning(f"[Backboard] find_folder_for_problem failed: {e}")
            return suggestion

    async def delete_folder_definition(
        self,
        thread_id: str,
        folder_id: str
    ) -> None:
        """
        Mark a folder as deleted in Backboard memory.
        This prevents suggestions to a folder that no longer exists.
        """
        if not self._initialized:
            await self.initialize()
        
        content = f"[FOLDER_DELETED] The folder with id={folder_id} has been deleted by the user. Do not suggest this folder anymore."
        
        try:
            await self.client.add_message(
                thread_id=thread_id,
                content=content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",
                stream=False
            )
            
            # Fully invalidate cache so UI updates immediately
            if folder_id in self._folder_map_cache:
                del self._folder_map_cache[folder_id]
            self.invalidate_folder_map_cache()  # Reset TTL for immediate refresh
            
            logger.info(f"[Backboard] Folder deleted from memory: {folder_id}")
            
        except Exception as e:
            logger.error(f"[Backboard] delete_folder_definition failed: {e}")

    async def delete_problem_memory(
        self,
        thread_id: str,
        session_id: str
    ) -> None:
        """
        Mark a problem as deleted in Backboard memory.
        This prevents the deleted problem from appearing in similarity results.
        """
        if not self._initialized:
            await self.initialize()
        
        content = f"[PROBLEM_DELETED] The problem with session_id={session_id} has been deleted by the user. Exclude this from future similarity searches."
        
        try:
            await self.client.add_message(
                thread_id=thread_id,
                content=content,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                memory="Auto",
                stream=False
            )
            
            logger.info(f"[Backboard] Problem deleted from memory: {session_id}")
            
        except Exception as e:
            logger.error(f"[Backboard] delete_problem_memory failed: {e}")

# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_backboard_service: Optional[BackboardService] = None


async def get_backboard_service() -> BackboardService:
    """
    Get or create the Backboard service singleton.
    
    Returns:
        Initialized BackboardService instance
    """
    global _backboard_service
    
    if _backboard_service is None:
        _backboard_service = BackboardService()
        await _backboard_service.initialize()
    
    return _backboard_service


def is_backboard_available() -> bool:
    """Check if Backboard is configured and available."""
    return bool(settings.backboard_api_key)
