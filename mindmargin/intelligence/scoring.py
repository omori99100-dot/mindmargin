"""Module 2 — Opportunity Scoring (weighted ranking)."""

import logging
import math
from datetime import datetime
from typing import Optional

from mindmargin.config import settings
from mindmargin.analytics.memory import (
    save_opportunity, get_opportunities, get_pipeline_history,
)
from mindmargin.intelligence.trend_engine import TrendIntelligenceEngine

logger = logging.getLogger(__name__)

# Scoring weights (configurable via settings.yaml)
WEIGHTS = {
    "trend_score": 0.25,
    "novelty": 0.20,
    "audience_match": 0.15,
    "evergreen_score": 0.15,
    "competition_inverse": 0.10,
    "historical_performance": 0.10,
    "seasonality": 0.05,
}

MIN_OPPORTUNITY_SCORE = 30.0


class OpportunityScorer:
    """Ranks topic candidates using weighted scoring."""

    def __init__(self, weights: Optional[dict[str, float]] = None):
        self.weights = weights or dict(WEIGHTS)

    def score_all(self, candidates: list[dict]) -> list[dict]:
        """Score and rank all candidates. Returns sorted list with opportunity_score."""
        if not candidates:
            return []

        scored = []
        for c in candidates:
            try:
                s = self._score_single(c)
                scored.append(s)
            except Exception as e:
                logger.warning(f"Scoring failed for '{c.get('topic', '?')}': {e}")

        scored.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)

        # Inject confidence estimates
        from mindmargin.intelligence.confidence import enrich_opportunities
        scored = enrich_opportunities(scored)

        # Persist to DB
        for s in scored:
            save_opportunity(
                topic=s["topic"], source=s.get("source", ""),
                opportunity_score=s["opportunity_score"],
                trend_score=s.get("trend_score", 0),
                competition=s.get("competition", 0),
                novelty=s.get("novelty", 0),
                seasonality=s.get("seasonality", 0),
                audience_match=s.get("audience_match", 0),
                evergreen_score=s.get("evergreen_score", 0),
                historical_performance=s.get("historical_performance", 0),
                confidence=s.get("confidence", 0),
            )

        return scored

    def _score_single(self, candidate: dict) -> dict:
        topic = candidate.get("topic", "")
        trend_score = candidate.get("trend_score", 0) * 100
        competition = candidate.get("competition", 0.5)
        novelty = candidate.get("novelty", 0.5) * 100
        seasonality = candidate.get("seasonality", 0.0) * 100

        # Compute derived scores
        audience_match = self._compute_audience_match(topic)
        evergreen_score = self._compute_evergreen(topic, novelty / 100)
        historical_perf = self._compute_historical_performance(topic)

        competition_inverse = (1.0 - competition) * 100

        opportunity = (
            self.weights["trend_score"] * trend_score
            + self.weights["novelty"] * novelty
            + self.weights["audience_match"] * audience_match
            + self.weights["evergreen_score"] * evergreen_score
            + self.weights["competition_inverse"] * competition_inverse
            + self.weights["historical_performance"] * historical_perf
            + self.weights["seasonality"] * seasonality
        )

        confidence = candidate.get("confidence", 0.5)

        result = dict(candidate)
        result.update({
            "opportunity_score": round(opportunity, 1),
            "audience_match": round(audience_match, 1),
            "evergreen_score": round(evergreen_score, 1),
            "historical_performance": round(historical_perf, 1),
            "confidence": confidence,
        })
        return result

    def _compute_audience_match(self, topic: str) -> float:
        """Estimate how well a topic matches the channel audience based on history."""
        from mindmargin.analytics.memory import get_top_performers
        performers = get_top_performers(10)
        if not performers:
            return 50.0

        topic_lower = topic.lower()
        match_count = 0
        for p in performers:
            t = p.get("topic", "").lower()
            words = set(t.split())
            topic_words = set(topic_lower.split())
            if words & topic_words:
                match_count += 1

        return min(50 + (match_count / len(performers)) * 50, 100)

    def _compute_evergreen(self, topic: str, novelty: float) -> float:
        """Score how evergreen a topic is (0-100)."""
        evergreen_keywords = [
            "history", "story", "explained", "how", "why", "rise and fall",
            "collapse", "documentary", "case study", "lessons", "analysis",
        ]
        topic_lower = topic.lower()
        hits = sum(1 for kw in evergreen_keywords if kw in topic_lower)
        base = min(hits * 20, 80)
        evergreen = base + (1.0 - novelty) * 20
        return min(evergreen, 100)

    def _compute_historical_performance(self, topic: str) -> float:
        """Score based on similar topics' past performance."""
        from mindmargin.analytics.memory import get_pipeline_history
        history = get_pipeline_history(100)
        if not history:
            return 50.0

        topic_lower = topic.lower()
        topic_words = set(topic_lower.split())
        scores = []
        for p in history:
            t = p.get("topic", "").lower()
            views = p.get("views", 0) or 0
            if views > 0:
                words = set(t.split())
                overlap = len(words & topic_words)
                if overlap > 0:
                    scores.append(views * overlap)

        if not scores:
            return 50.0
        avg_score = sum(scores) / len(scores)
        return min(avg_score / 50, 100)


def run_opportunity_scoring() -> list[dict]:
    """Full pipeline: collect trends → score → return ranked opportunities."""
    engine = TrendIntelligenceEngine()
    candidates = engine.collect()
    scorer = OpportunityScorer()
    scored = scorer.score_all(candidates)
    filtered = [s for s in scored if s.get("opportunity_score", 0) >= MIN_OPPORTUNITY_SCORE]
    logger.info(f"Opportunity scoring: {len(candidates)} candidates → "
                f"{len(scored)} scored → {len(filtered)} above threshold")
    return filtered or scored
