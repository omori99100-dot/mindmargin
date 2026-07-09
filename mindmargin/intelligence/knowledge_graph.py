"""Phase 7 — Knowledge Graph.

Topic relationship graph for:
- Discovering adjacent opportunities
- Preventing duplicate coverage
- Recommending expansion paths
- Improving opportunity scoring
"""

import logging
import math
import re
from datetime import datetime
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """Topic relationship graph built from DB data."""

    def build(self) -> dict:
        """Rebuild the knowledge graph from existing data.

        Extracts keywords, discovers relationships, and stores in DB.
        Returns stats about what was built.
        """
        from mindmargin.analytics.memory import (
            get_pipeline_history, get_trend_sources, get_topic_lineages,
            get_opportunities, get_channel_memory,
            save_topic_keyword, save_topic_relationship, save_audience_topic,
        )

        topics = self._collect_all_topics()
        if not topics:
            return {"topics_found": 0, "relationships_created": 0, "keywords_extracted": 0}

        keyword_count = 0
        for topic in topics:
            keywords = self._extract_keywords(topic)
            for kw, weight in keywords:
                save_topic_keyword(topic, kw, weight)
                keyword_count += 1

        rel_count = 0
        topic_list = list(topics)
        for i in range(len(topic_list)):
            for j in range(i + 1, len(topic_list)):
                strength = self._compute_relationship(topic_list[i], topic_list[j])
                if strength > 0.3:
                    save_topic_relationship(
                        topic_list[i], topic_list[j], "related", round(strength, 2),
                    )
                    rel_count += 1

        lineages = get_topic_lineages()
        for lin in lineages:
            parent = lin.get("parent_topic", "")
            child = lin.get("child_topic", "")
            conf = lin.get("confidence", 0.5) or 0.5
            perf = lin.get("performance_inheritance", 0) or 0
            strength = (conf + perf) / 2
            save_topic_relationship(parent, child, "parent", round(strength, 2))
            save_topic_relationship(child, parent, "child", round(strength, 2))
            rel_count += 2

        memory = get_channel_memory(50)
        for entry in memory:
            topic = entry.get("topic", "")
            if topic:
                score = entry.get("performance_score", 50) or 50
                af = min(score / 100, 1.0)
                save_audience_topic(topic, af, af)

        logger.info(f"Knowledge graph: {len(topics)} topics, {keyword_count} keywords, "
                    f"{rel_count} relationships")
        return {
            "topics_found": len(topics),
            "keywords_extracted": keyword_count,
            "relationships_created": rel_count,
        }

    def _collect_all_topics(self) -> set[str]:
        from mindmargin.analytics.memory import (
            get_pipeline_history, get_trend_sources, get_opportunities,
            get_topic_lineages, get_channel_memory,
        )

        topics = set()

        for p in get_pipeline_history(500):
            t = p.get("topic", "")
            if t:
                topics.add(t)

        for s in get_trend_sources(limit=500, min_confidence=0):
            t = s.get("topic", "")
            if t:
                topics.add(t)

        for o in get_opportunities(min_score=0, limit=500):
            t = o.get("topic", "")
            if t:
                topics.add(t)

        for l in get_topic_lineages(limit=500):
            p = l.get("parent_topic", "")
            c = l.get("child_topic", "")
            if p:
                topics.add(p)
            if c:
                topics.add(c)

        for m in get_channel_memory(200):
            t = m.get("topic", "")
            if t:
                topics.add(t)

        return topics

    def _extract_keywords(self, topic: str) -> list[tuple[str, float]]:
        """Extract meaningful keywords from a topic string."""
        topic_lower = topic.lower()
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "are", "was", "were",
            "this", "that", "its", "their", "what", "how", "why", "all",
        }

        words = re.findall(r"\w+", topic_lower)
        keywords = [(w, 1.0) for w in words if w not in stop_words and len(w) > 2]

        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if len(bigram) > 6:
                keywords.append((bigram, 1.5))

        return keywords

    def _compute_relationship(self, topic_a: str, topic_b: str) -> float:
        """Compute relationship strength (0-1) between two topics."""
        if topic_a == topic_b:
            return 0.0

        from mindmargin.analytics.memory import get_topic_keywords
        a_keywords = {k["keyword"] for k in get_topic_keywords(topic_a, limit=20)}
        b_keywords = {k["keyword"] for k in get_topic_keywords(topic_b, limit=20)}

        if not a_keywords or not b_keywords:
            a_words = set(re.findall(r"\w+", topic_a.lower()))
            b_words = set(re.findall(r"\w+", topic_b.lower()))
            intersection = a_words & b_words
            union = a_words | b_words
            if not union:
                return 0.0
            overlap = sum(2 for w in intersection if len(w) > 3) + sum(1 for w in intersection if len(w) <= 3)
            return min(overlap / max(len(union), 1), 1.0)

        intersection = a_keywords & b_keywords
        if not intersection:
            return 0.0

        jaccard = len(intersection) / max(len(a_keywords | b_keywords), 1)
        weight_score = sum(
            min(k["weight"] for k in get_topic_keywords(topic_a, limit=20) if k["keyword"] in intersection)
            for _ in [1]
        ) / max(len(intersection), 1)

        return min(jaccard * 0.7 + weight_score * 0.3, 1.0)

    def find_adjacent_topics(self, topic: str, max_results: int = 10) -> list[dict]:
        """Find topics related to the given topic via the graph."""
        from mindmargin.analytics.memory import get_topic_relationships
        relations = get_topic_relationships(topic, limit=50)

        adjacent = []
        seen = set()
        for r in relations:
            other = r["target_topic"] if r["source_topic"] == topic else r["source_topic"]
            if other and other not in seen:
                seen.add(other)
                adjacent.append({
                    "topic": other,
                    "relationship": r.get("relationship_type", "related"),
                    "strength": r.get("strength", 0),
                })

        adjacent.sort(key=lambda x: x["strength"], reverse=True)
        return adjacent[:max_results]

    def recommend_expansion(self, topic: str, max_results: int = 5) -> list[dict]:
        """Recommend topic expansion paths from the graph."""
        adjacent = self.find_adjacent_topics(topic, max_results=20)

        from mindmargin.analytics.memory import get_pipeline_history, get_opportunities
        published = {p.get("topic", "") for p in get_pipeline_history(200)}
        scored_topics = {o.get("topic", "") for o in get_opportunities(min_score=0, limit=200)}

        recommendations = []
        for adj in adjacent:
            t = adj["topic"]
            if t in published:
                continue
            recommendations.append({
                "topic": t,
                "expansion_from": topic,
                "relationship": adj["relationship"],
                "strength": adj["strength"],
                "already_scored": t in scored_topics,
            })

        recommendations.sort(key=lambda x: x["strength"], reverse=True)
        return recommendations[:max_results]

    def is_duplicate_coverage(self, topic: str, threshold: float = 0.5) -> tuple[bool, str, float]:
        """Check if a topic is too similar to already-published content."""
        from mindmargin.analytics.memory import get_pipeline_history

        history = get_pipeline_history(200)
        for p in history:
            published_topic = p.get("topic", "")
            if not published_topic:
                continue
            strength = self._compute_relationship(topic, published_topic)
            if strength >= threshold:
                return True, published_topic, strength

        return False, "", 0.0

    def get_expansion_opportunities(self, max_results: int = 20) -> list[dict]:
        """Find all expansion opportunities by scanning the graph."""
        from mindmargin.analytics.memory import (
            get_pipeline_history, get_topic_relationships,
        )

        history = get_pipeline_history(200)
        published = [p.get("topic", "") for p in history if p.get("topic")]

        expansions = []
        seen = set()

        for p_topic in published:
            adjacent = self.find_adjacent_topics(p_topic, max_results=5)
            for adj in adjacent:
                if adj["topic"] not in seen and adj["topic"] not in published:
                    seen.add(adj["topic"])
                    expansions.append({
                        "topic": adj["topic"],
                        "source_topic": p_topic,
                        "strength": adj["strength"],
                        "relationship": adj["relationship"],
                    })

        expansions.sort(key=lambda x: x["strength"], reverse=True)
        return expansions[:max_results]


def build_knowledge_graph() -> dict:
    """Convenience entry point to build/rebuild the graph."""
    kg = KnowledgeGraph()
    return kg.build()


def find_adjacent(topic: str, max_results: int = 10) -> list[dict]:
    """Convenience entry point for adjacency lookup."""
    kg = KnowledgeGraph()
    return kg.find_adjacent_topics(topic, max_results)
