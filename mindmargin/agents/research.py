import logging
from datetime import datetime

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text

logger = logging.getLogger(__name__)

TREND_KEYWORDS = [
    "scandal", "collapse", "fraud", "crash", "billion", "exposed",
    "inside", "truth", "secrets", "fall", "failure", "bankrupt",
    "investigation", "whistleblower", "trial", "scam", "controversy",
]

SECTION_TEMPLATES = [
    "Background & History",
    "Key Figures",
    "Timeline of Events",
    "Root Causes & Contributing Factors",
    "The Turning Point",
    "Aftermath & Consequences",
    "Behavioral Economics Analysis",
    "Lessons Learned",
    "Relevance Today",
]


def score_topic(topic: str) -> dict:
    """Score a topic's viral/documentary potential based on keyword analysis."""
    topic_lower = topic.lower()
    matched = [kw for kw in TREND_KEYWORDS if kw in topic_lower]
    score = min(40 + len(matched) * 8, 100)

    return {
        "topic": topic,
        "trend_score": score,
        "matched_keywords": matched,
        "keyword_count": len(matched),
        "recommendation": "proceed" if score >= 50 else "reconsider",
        "scored_at": datetime.utcnow().isoformat(),
    }


def build_research(topic: str) -> dict:
    """Build structured research data from the topic."""
    sections = []
    for i, title in enumerate(SECTION_TEMPLATES, 1):
        sections.append({
            "section_id": i,
            "title": title,
            "content": f"Research notes for {topic} — {title}. "
                       f"To be expanded with LLM-generated analysis in production.",
            "sources": [],
        })

    return {
        "topic": topic,
        "sections": sections,
        "section_count": len(sections),
    }


class ResearchAgent:
    """Local trend scoring + structured research generation. No external APIs."""

    def __init__(self):
        self.name = "research"

    def run(self, topic: str, pipeline_id: str) -> dict:
        logger.info(f"ResearchAgent: scoring topic '{topic}'")

        trend = score_topic(topic)
        research = build_research(topic)

        dirs = ensure_dirs(topic, pipeline_id)
        write_text(dirs["research"] / "trend_score.json",
                   __import__("json").dumps(trend, indent=2))
        write_text(dirs["research"] / "research_data.json",
                   __import__("json").dumps(research, indent=2))

        return {
            "agent": self.name,
            "status": "completed",
            "trend": trend,
            "research": research,
        }
