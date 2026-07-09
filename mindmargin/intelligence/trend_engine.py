"""Module 1 — Trend Intelligence Engine with pluggable providers."""

import json
import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from mindmargin.config import settings
from mindmargin.analytics.memory import save_trend_source, get_trend_sources
from mindmargin.core.pipeline_logger import PipelineLogger

logger = logging.getLogger(__name__)


class TrendProvider(ABC):
    """Abstract base for trend data providers."""

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Return list of {topic, trend_score, competition, novelty, seasonality, confidence}."""
        ...


class HistoricalAnniversariesProvider(TrendProvider):
    """Generates topics from historical events on today's date."""

    def name(self) -> str:
        return "historical_anniversaries"

    def fetch(self) -> list[dict]:
        today = datetime.utcnow()
        month_day = today.strftime("%m-%d")

        _anniversaries = {
            "07-04": [("US Independence Day History", 0.7)],
            "10-29": [("1929 Stock Market Crash", 0.9), ("Black Tuesday History", 0.8)],
            "09-15": [("Lehman Brothers Collapse", 0.85)],
            "12-02": [("Enron Bankruptcy", 0.85)],
            "03-10": [("Silicon Valley Bank Collapse", 0.8)],
            "05-06": [("2010 Flash Crash", 0.7)],
            "01-15": [("US Airways Flight 1549 Hudson Landing", 0.6)],
            "08-09": [("2007 BNP Paribas Freezes Funds — Financial Crisis Start", 0.75)],
            "11-09": [("Berlin Wall Fall", 0.65)],
            "06-15": [("Magna Carta Signed", 0.5)],
        }
        results = []
        for topic, score in _anniversaries.get(month_day, []):
            results.append({
                "topic": topic,
                "trend_score": score,
                "competition": random.uniform(0.3, 0.6),
                "novelty": random.uniform(0.5, 0.8),
                "seasonality": 0.0,
                "confidence": 0.7,
            })
        if not results:
            results.append({
                "topic": f"On This Day: Historical Events {month_day}",
                "trend_score": 0.5,
                "competition": 0.4,
                "novelty": 0.7,
                "seasonality": 0.0,
                "confidence": 0.5,
            })
        return results


class ChannelNicheProvider(TrendProvider):
    """Generates topics from the channel's existing successful content."""

    def __init__(self):
        from mindmargin.analytics.memory import get_top_performers
        self._performers = get_top_performers(5)

    def name(self) -> str:
        return "channel_niche"

    def fetch(self) -> list[dict]:
        from mindmargin.analytics.growth_engine import expand_topic_tree
        results = []
        seen = set()
        for p in self._performers:
            topic = p.get("topic", "")
            if topic in seen:
                continue
            seen.add(topic)
            try:
                expansions = expand_topic_tree(topic, max_depth=1)
                for exp in expansions[:3]:
                    child = exp.get("child_topic", "")
                    conf = exp.get("confidence", 0.5)
                    results.append({
                        "topic": child or f"{topic} — follow-up analysis",
                        "trend_score": conf * 0.8,
                        "competition": 0.3,
                        "novelty": 0.6,
                        "seasonality": 0.1,
                        "confidence": conf,
                    })
            except Exception:
                results.append({
                    "topic": f"{topic} — deeper investigation",
                    "trend_score": 0.5,
                    "competition": 0.4,
                    "novelty": 0.5,
                    "seasonality": 0.1,
                    "confidence": 0.6,
                })
        return results


class ExistingVideosProvider(TrendProvider):
    """Suggests topics from previously published videos that had untapped potential."""

    def name(self) -> str:
        return "existing_videos"

    def fetch(self) -> list[dict]:
        from mindmargin.analytics.memory import get_pipeline_history
        history = get_pipeline_history(50)
        results = []
        for p in history:
            views = p.get("views", 0) or 0
            topic = p.get("topic", "")
            if views > 0 and topic:
                new_topic = f"What Happened Next: {topic}"
                results.append({
                    "topic": new_topic,
                    "trend_score": min(views / 1000, 0.9),
                    "competition": 0.3,
                    "novelty": 0.7,
                    "seasonality": 0.1,
                    "confidence": min(views / 5000, 0.95),
                })
        return results


class TrendIntelligenceEngine:
    """Aggregates trend data from all providers, normalizes, and stores results."""

    def __init__(self):
        self.pipeline_id = f"trend_{datetime.utcnow().strftime('%Y%m%d')}"
        self._plog = PipelineLogger(self.pipeline_id) if settings.production.enable_structured_logs else None

    def collect(self) -> list[dict]:
        """Collect topics from all registered providers."""
        providers: list[TrendProvider] = [
            HistoricalAnniversariesProvider(),
            ChannelNicheProvider(),
            ExistingVideosProvider(),
        ]
        all_topics: list[dict] = []
        for provider in providers:
            try:
                topics = provider.fetch()
                for t in topics:
                    t["source"] = provider.name()
                    save_trend_source(
                        source=provider.name(), topic=t["topic"],
                        trend_score=t.get("trend_score", 0),
                        competition=t.get("competition", 0),
                        novelty=t.get("novelty", 0),
                        seasonality=t.get("seasonality", 0),
                        confidence=t.get("confidence", 0),
                        raw_data=json.dumps(t),
                    )
                    all_topics.append(t)
                logger.info(f"Trend provider '{provider.name()}': {len(topics)} topics")
            except Exception as e:
                logger.warning(f"Trend provider '{provider.name()}' failed: {e}")

        if self._plog:
            self._plog.log("trend_collection_complete", stage="trend_intelligence",
                          metadata={"total_topics": len(all_topics),
                                   "providers": [p.name() for p in providers]})

        return all_topics

    def get_cached(self, limit: int = 50, min_confidence: float = 0.3) -> list[dict]:
        return get_trend_sources(limit=limit, min_confidence=min_confidence)
