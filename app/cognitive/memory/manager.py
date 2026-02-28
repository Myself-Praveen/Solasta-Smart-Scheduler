"""
Solasta — Memory Manager

Manages short-term working memory (context window),
long-term episodic memory (experience recall), and
context optimisation (summarisation to prevent token overflow).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.cognitive.llm.provider import llm_gateway
from app.core.logging import get_logger
from app.db.repository import MemoryRepository

logger = get_logger(__name__)


class ShortTermMemory:
    """
    Working memory for the current goal execution.
    Stores recent tool outputs and conversation context.
    Fixed capacity with FIFO eviction.
    """

    def __init__(self, max_items: int = 20):
        self._items: List[Dict[str, Any]] = []
        self._max_items = max_items

    def add(self, key: str, data: Any) -> None:
        self._items.append({"key": key, "data": data})
        if len(self._items) > self._max_items:
            self._items.pop(0)

    def get(self, key: str) -> Optional[Any]:
        for item in reversed(self._items):
            if item["key"] == key:
                return item["data"]
        return None

    def get_recent(self, n: int = 5) -> List[Dict[str, Any]]:
        return self._items[-n:]

    def to_context_string(self, max_chars: int = 2000) -> str:
        """Serialise recent memory items into a context string for LLM prompts."""
        parts = []
        total = 0
        for item in reversed(self._items):
            entry = f"[{item['key']}]: {str(item['data'])[:300]}"
            if total + len(entry) > max_chars:
                break
            parts.append(entry)
            total += len(entry)
        return "\n".join(reversed(parts))

    def clear(self) -> None:
        self._items.clear()


class LongTermMemory:
    """
    Episodic memory backed by the persistence layer.
    Stores summaries of past successful goals for experience recall.
    """

    @staticmethod
    async def store_experience(
        goal_id: str,
        goal_summary: str,
        outcome: Dict[str, Any],
    ) -> None:
        """Store a completed goal experience for future recall."""
        await MemoryRepository.store(goal_id, goal_summary, outcome)
        logger.info("long_term_memory_stored", goal_id=goal_id)

    @staticmethod
    async def recall_experiences(query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Recall past experiences similar to the current query."""
        results = await MemoryRepository.recall_similar(query, limit)
        logger.info("long_term_memory_recalled", count=len(results))
        return results


class ContextOptimiser:
    """
    Summarises verbose tool outputs before injecting them into
    downstream prompts to prevent context window overflow.
    """

    @staticmethod
    async def summarise(text: str, max_length: int = 500, goal_id: str = "") -> str:
        """Use a fast LLM to compress text while preserving key information."""
        if len(text) <= max_length:
            return text

        try:
            summary, _ = await llm_gateway.generate(
                prompt=(
                    f"Summarise the following in under {max_length} characters, "
                    f"preserving all key data points and numbers:\n\n{text[:3000]}"
                ),
                system="You are a concise summariser. Output only the summary, no preamble.",
                goal_id=goal_id,
                agent_type="summariser",
            )
            return summary[:max_length]
        except Exception:
            # Fallback: simple truncation
            return text[:max_length] + "... [truncated]"
