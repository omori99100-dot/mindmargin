"""Module 3 — Channel Memory with topic dedup and semantic comparison."""

import hashlib
import logging
import re
from typing import Optional

from mindmargin.analytics.memory import (
    save_channel_memory, get_channel_memory, get_memory_topic_hashes,
    get_pipeline_history, get_top_performers,
)

logger = logging.getLogger(__name__)


def _topic_hash(topic: str) -> str:
    """Create a normalized hash for topic dedup."""
    normalized = re.sub(r"[^a-z0-9\s]", "", topic.lower().strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _keyword_extract(topic: str) -> list[str]:
    """Extract significant keywords from a topic string."""
    stop_words = {
        "the", "a", "an", "of", "in", "to", "and", "is", "was", "for",
        "how", "why", "what", "that", "this", "its", "are", "were",
    }
    words = re.findall(r"[a-zA-Z]{3,}", topic.lower())
    return [w for w in words if w not in stop_words]


def is_duplicate_topic(new_topic: str, threshold: float = 0.6) -> tuple[bool, str, float]:
    """Check if a topic has been used before.

    Returns (is_duplicate, matched_topic, similarity_score).
    """
    existing = get_channel_memory(200)
    new_hash = _topic_hash(new_topic)
    new_keywords = set(_keyword_extract(new_topic))

    for mem in existing:
        # Exact hash match
        if mem.get("topic_hash") == new_hash:
            return True, mem["topic"], 1.0

        # Keyword overlap similarity
        mem_keywords = set(_keyword_extract(mem.get("topic", "")))
        if new_keywords and mem_keywords:
            overlap = len(new_keywords & mem_keywords)
            similarity = overlap / max(len(new_keywords | mem_keywords), 1)
            if similarity >= threshold:
                return True, mem["topic"], round(similarity, 2)

    return False, "", 0.0


def get_narrative_recommendations() -> list[dict]:
    """Return recommended narrative styles based on top performers."""
    performers = get_top_performers(5)
    if not performers:
        return [
            {"style": "documentary", "confidence": 0.7},
            {"style": "narrative_storytelling", "confidence": 0.6},
        ]
    recs = [
        {"style": "documentary", "confidence": 0.7},
    ]
    for p in performers:
        topic = p.get("topic", "")
        views = p.get("views", 0) or 0
        if views > 500:
            recs.append({
                "style": "in_depth_case_study",
                "confidence": min(views / 10000, 0.9),
            })
            recs.append({
                "style": "cautionary_tale",
                "confidence": min(views / 5000, 0.85),
            })
    return recs


def update_channel_memory_from_history() -> int:
    """Scan pipeline history and update channel memory.

    Returns count of new memory entries added.
    """
    history = get_pipeline_history(200)
    existing_hashes = get_memory_topic_hashes()
    count = 0
    for p in history:
        topic = p.get("topic", "")
        pipeline_id = p.get("id", "")
        if not topic or not pipeline_id:
            continue
        t_hash = _topic_hash(topic)
        if t_hash in existing_hashes:
            continue
        keywords = ", ".join(_keyword_extract(topic))
        views = p.get("views", 0) or 0
        performance = min(views / 100, 100)
        title = p.get("title", "")[:200]
        save_channel_memory(
            pipeline_id=pipeline_id, topic=topic, topic_hash=t_hash,
            title=title, keywords=keywords,
            performance_score=performance,
        )
        existing_hashes.add(t_hash)
        count += 1
    if count:
        logger.info(f"Channel memory: {count} new entries")
    return count
