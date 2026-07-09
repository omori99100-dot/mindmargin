"""Research Agent — expanded documentary research collection.

Phase 21: Collects comprehensive data across 17 categories for
professional documentary production.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text

logger = logging.getLogger(__name__)

TREND_KEYWORDS = [
    "scandal", "collapse", "fraud", "crash", "billion", "exposed",
    "inside", "truth", "secrets", "fall", "failure", "bankrupt",
    "investigation", "whistleblower", "trial", "scam", "controversy",
    "revolution", "disruption", "war", "crisis", "disaster", "meltdown",
    "ponzi", "theft", "embezzlement", "bribery", "corruption",
]

EXPANDED_RESEARCH_CATEGORIES = [
    "timeline", "founders", "financials", "market_share", "acquisitions",
    "key_decisions", "internal_conflicts", "public_reactions", "quotes",
    "legal", "interviews", "earnings", "historical_context",
    "psychological_biases", "lessons", "contrasting_views", "current_status",
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
    """Build comprehensive structured research data for documentary production."""
    sections = []

    research_template = {
        "timeline": {
            "description": "Key events with exact dates — founding, IPO, peak, crisis,结局",
            "entries": [],
        },
        "founders": {
            "description": "Names, roles, backgrounds, key decisions of founders and key figures",
            "entries": [],
        },
        "financials": {
            "description": "Revenue figures, market cap, stock price peaks, losses, funding rounds",
            "entries": [],
        },
        "market_share": {
            "description": "Industry position, competitors, market dynamics over time",
            "entries": [],
        },
        "acquisitions": {
            "description": "Major M&A activity, partnerships, investments made or received",
            "entries": [],
        },
        "key_decisions": {
            "description": "The 3-5 critical decisions that shaped the outcome",
            "entries": [],
        },
        "internal_conflicts": {
            "description": "Leadership disputes, board battles, cultural problems, employee issues",
            "entries": [],
        },
        "public_reactions": {
            "description": "Media coverage, customer sentiment, employee morale, public opinion",
            "entries": [],
        },
        "quotes": {
            "description": "Direct quotes from executives, analysts, employees (with attribution)",
            "entries": [],
        },
        "legal": {
            "description": "Court cases, SEC filings, investigations, settlements, regulatory actions",
            "entries": [],
        },
        "interviews": {
            "description": "Notable public statements, press conferences, earnings call highlights",
            "entries": [],
        },
        "earnings": {
            "description": "Quarterly/annual results showing financial trajectory",
            "entries": [],
        },
        "historical_context": {
            "description": "Industry trends, economic conditions, technological shifts of the era",
            "entries": [],
        },
        "psychological_biases": {
            "description": "Overconfidence, sunk cost, confirmation bias, groupthink at play",
            "entries": [],
        },
        "lessons": {
            "description": "What behavioral economists and business analysts say about this case",
            "entries": [],
        },
        "contrasting_views": {
            "description": "Different perspectives on what went wrong — alternative explanations",
            "entries": [],
        },
        "current_status": {
            "description": "What exists today as a result — bankruptcy, acquisition, transformation",
            "entries": [],
        },
    }

    for category, details in research_template.items():
        sections.append({
            "category": category,
            "description": details["description"],
            "data": details["entries"],
            "status": "pending",
        })

    return {
        "topic": topic,
        "categories": sections,
        "category_count": len(sections),
        "version": "2.0",
    }


class ResearchAgent:
    """Comprehensive documentary research collection. Phase 21 expanded edition."""

    def __init__(self, provider_manager=None):
        self.name = "research"
        self._pm = provider_manager
        self._llm = None

    def _get_llm(self):
        if self._llm is None and self._pm:
            self._llm = self._pm.get()
        return self._llm

    def run(self, topic: str, pipeline_id: str) -> dict:
        logger.info(f"ResearchAgent: comprehensive research for '{topic}'")

        trend = score_topic(topic)
        research = build_research(topic)

        # If LLM is available, enhance research with AI-generated content
        llm = self._get_llm()
        if llm:
            try:
                research = self._enhance_with_llm(topic, research, llm)
            except Exception as e:
                logger.warning(f"LLM research enhancement failed: {e}")
        else:
            logger.warning("No LLM available for research enhancement — using empty stubs")

        dirs = ensure_dirs(topic, pipeline_id)
        write_text(dirs["research"] / "trend_score.json",
                   json.dumps(trend, indent=2))
        write_text(dirs["research"] / "research_data.json",
                   json.dumps(research, indent=2))

        return {
            "agent": self.name,
            "status": "completed",
            "trend": trend,
            "research": research,
        }

    def _enhance_with_llm(self, topic: str, research: dict, llm) -> dict:
        """Use LLM to populate research categories with real data."""
        from mindmargin.prompts import RESEARCH_SYSTEM, RESEARCH_PROMPT

        prompt = RESEARCH_PROMPT.format(topic=topic)
        result = llm.generate_json_sync(prompt, system=RESEARCH_SYSTEM, task="research")

        if isinstance(result, dict) and result:
            # Merge LLM results into research categories
            populated = 0
            for category in research["categories"]:
                cat_name = category["category"]
                if cat_name in result:
                    data = result[cat_name]
                    if isinstance(data, list):
                        category["data"] = data
                    elif isinstance(data, str):
                        category["data"] = [{"text": data}]
                    category["status"] = "completed"
                    populated += 1

            # Also capture trend_score from LLM if available
            if "trend_score" in result:
                research["trend_score_llm"] = result["trend_score"]

            logger.info(f"Research enhanced: {populated}/{len(research['categories'])} categories populated")
        else:
            logger.warning("Research LLM returned empty/invalid result — categories remain empty")

        return research
