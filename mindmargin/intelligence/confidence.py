"""Phase 4 — Confidence Estimation.

Computes per-opportunity confidence scores based on:
- Amount of historical data
- Freshness of trend data
- Source agreement (multiple providers)
- Similarity to past successful topics
- Variance across scoring components
- Prediction consistency (from feedback engine)
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


class ConfidenceEstimator:
    """Estimates confidence for opportunity scores using multiple signals."""

    def estimate(self, opportunity: dict) -> float:
        """Compute a 0-100 confidence score for a single opportunity.

        Combines 6 factors with equal weights.
        """
        factors = [
            ("data_volume", self._data_volume_factor(opportunity), 0.20),
            ("freshness", self._freshness_factor(opportunity), 0.20),
            ("source_agreement", self._source_agreement_factor(opportunity), 0.15),
            ("similarity_success", self._similarity_to_success(opportunity), 0.15),
            ("score_variance", self._score_variance_factor(opportunity), 0.15),
            ("prediction_consistency", self._prediction_consistency(opportunity), 0.15),
        ]

        total = sum(weight * score for _, score, weight in factors)
        return round(min(total, 100), 1)

    def estimate_many(self, opportunities: list[dict]) -> list[dict]:
        """Add confidence to a list of opportunity dicts (mutates in place)."""
        for opp in opportunities:
            try:
                opp["confidence"] = self.estimate(opp)
            except Exception as e:
                logger.warning(f"Confidence estimation failed for '{opp.get('topic', '?')}': {e}")
                opp["confidence"] = opp.get("confidence", 50.0)
        return opportunities

    def _data_volume_factor(self, opp: dict) -> float:
        """How much historical data supports this estimate. 0-100."""
        from mindmargin.analytics.memory import get_pipeline_history, get_outcomes

        history = get_pipeline_history(100)
        if not history:
            return 20.0

        outcomes = get_outcomes(limit=50)

        pipeline_count = len(history)
        outcome_count = len(outcomes)

        score = min(pipeline_count * 5, 50) + min(outcome_count * 8, 50)
        return min(score, 100)

    def _freshness_factor(self, opp: dict) -> float:
        """How recent the trend data is. 0-100."""
        scored_at = opp.get("scored_at", "")
        if not scored_at:
            return 50.0

        try:
            if "T" in scored_at:
                dt = datetime.fromisoformat(scored_at)
            else:
                dt = datetime.strptime(scored_at, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return 50.0

        hours_ago = (datetime.now() - dt).total_seconds() / 3600
        if hours_ago < 6:
            return 100.0
        elif hours_ago < 24:
            return 85.0
        elif hours_ago < 72:
            return 65.0
        elif hours_ago < 168:
            return 40.0
        else:
            return max(20.0, 100.0 - hours_ago / 24 * 2)

    def _source_agreement_factor(self, opp: dict) -> float:
        """How many trend sources agree on this topic. 0-100."""
        topic = opp.get("topic", "")
        if not topic:
            return 50.0

        from mindmargin.analytics.memory import get_trend_sources
        sources = get_trend_sources(limit=200, min_confidence=0)
        matching = [s for s in sources if s.get("topic", "").lower() == topic.lower()]

        if not matching:
            source = opp.get("source", "")
            return 40.0 if source else 30.0

        unique_sources = len(set(m["source"] for m in matching))
        avg_confidence = sum(m.get("confidence", 0) or 0 for m in matching) / len(matching)

        score = min(unique_sources * 25, 60) + avg_confidence * 40
        return min(score, 100)

    def _similarity_to_success(self, opp: dict) -> float:
        """How similar this topic is to past successful topics. 0-100."""
        from mindmargin.analytics.memory import get_top_performers
        performers = get_top_performers(metric="views", limit=10)
        if not performers:
            return 50.0

        topic = opp.get("topic", "").lower()
        topic_words = set(topic.split())

        max_similarity = 0.0
        for p in performers:
            p_topic = p.get("topic", "").lower()
            p_words = set(p_topic.split())
            if not topic_words or not p_words:
                continue
            overlap = len(topic_words & p_words)
            similarity = overlap / max(len(topic_words), len(p_words), 1)
            views = p.get("views", 0) or 0
            if views > 0:
                similarity *= min(math.log10(views + 1) / 3, 1)
            max_similarity = max(max_similarity, similarity)

        return min(max_similarity * 100, 100)

    def _score_variance_factor(self, opp: dict) -> float:
        """Low variance = higher confidence. 0-100."""
        components = [
            opp.get("trend_score", 0) or 0,
            opp.get("novelty", 0) or 0,
            opp.get("audience_match", 0) or 0,
            opp.get("evergreen_score", 0) or 0,
            opp.get("historical_performance", 0) or 0,
        ]
        val_max = 100 if any(c > 1 for c in components) else 1
        normalized = [(c / val_max) if val_max > 0 else c for c in components]

        mean = sum(normalized) / max(len(normalized), 1)
        variance = sum((x - mean) ** 2 for x in normalized) / max(len(normalized), 1)
        std = math.sqrt(variance)

        score = max(0, 100 - std * 100)
        return min(score, 100)

    def _prediction_consistency(self, opp: dict) -> float:
        """How consistent predictions have been for similar topics. 0-100."""
        from mindmargin.analytics.memory import get_outcomes, get_prediction_errors

        outcomes = get_outcomes(limit=30)
        if len(outcomes) < 3:
            return 50.0

        errors = [o.get("prediction_error", 0) or 0 for o in outcomes]
        if not errors:
            return 50.0

        mean_error = sum(errors) / len(errors)
        abs_errors = [abs(e) for e in errors]
        mae = sum(abs_errors) / len(abs_errors)

        consistency = max(0, 100 - mae * 2)
        bias_penalty = min(abs(mean_error) * 3, 30)

        return max(10, consistency - bias_penalty)


def estimate_confidence(opportunity: dict) -> float:
    """Convenience entry point for single opportunity."""
    estimator = ConfidenceEstimator()
    return estimator.estimate(opportunity)


def enrich_opportunities(opportunities: list[dict]) -> list[dict]:
    """Add confidence estimates to a list of opportunity dicts."""
    estimator = ConfidenceEstimator()
    return estimator.estimate_many(opportunities)
