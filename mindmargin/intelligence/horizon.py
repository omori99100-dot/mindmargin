"""Phase 8 — Prediction Horizon.

Forecasts opportunity scores across multiple time windows:
1 day, 3 days, 7 days, 14 days, 30 days.
Each forecast includes expected score, confidence, and uncertainty.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

FORECAST_WINDOWS = [1, 3, 7, 14, 30]


class PredictionHorizon:
    """Multi-window forecast engine for opportunity scores."""

    def forecast_all(self, opportunities: list[dict] | None = None) -> list[dict]:
        """Generate forecasts for all windows across all opportunities.

        Returns list of forecast records covering all topic × window combinations.
        """
        from mindmargin.analytics.memory import (
            get_top_opportunities, save_forecast,
        )

        if opportunities is None:
            opportunities = get_top_opportunities(30)

        if not opportunities:
            logger.warning("Prediction horizon: no opportunities to forecast")
            return []

        forecasts = []
        today = datetime.now().strftime("%Y-%m-%d")

        for opp in opportunities:
            topic = opp.get("topic", "")
            if not topic:
                continue

            base_score = opp.get("opportunity_score", 0) or 0
            base_confidence = opp.get("confidence", 50) or 50
            trend_val = opp.get("trend_score", 0) or 0
            historical = opp.get("historical_performance", 0) or 0
            seasonality = opp.get("seasonality", 0) or 0
            novelty = opp.get("novelty", 0) or 0
            competition = opp.get("competition", 0.5) or 0.5

            for window in FORECAST_WINDOWS:
                forecast = self._forecast_single(
                    topic=topic,
                    window_days=window,
                    base_score=base_score,
                    base_confidence=base_confidence,
                    trend_val=trend_val,
                    historical=historical,
                    seasonality=seasonality,
                    novelty=novelty,
                    competition=competition,
                )
                save_forecast(
                    topic=topic,
                    forecast_date=today,
                    window_days=window,
                    **forecast,
                )
                forecasts.append({
                    "topic": topic,
                    "window_days": window,
                    **forecast,
                })

        logger.info(f"Prediction horizon: {len(forecasts)} forecasts generated "
                    f"for {len(opportunities)} topics")
        return forecasts

    def _forecast_single(self, topic: str, window_days: int,
                          base_score: float, base_confidence: float,
                          trend_val: float, historical: float,
                          seasonality: float, novelty: float,
                          competition: float) -> dict:
        """Generate a single forecast with score, confidence, and uncertainty.

        Uses trend momentum, historical decay, seasonal effects,
        and prediction history to estimate future scores.
        """
        val_max = 100 if max(trend_val, historical, seasonality, novelty) > 1 else 1
        trend_norm = trend_val / val_max if val_max > 0 else 0
        hist_norm = historical / val_max if val_max > 0 else 0
        season_norm = seasonality / val_max if val_max > 0 else 0
        novelty_norm = novelty / val_max if val_max > 0 else 0

        trend_momentum = self._compute_trend_momentum(topic)

        decay_factor = math.exp(-window_days * 0.02)
        trend_decay = max(0.5, decay_factor)

        seasonal_boost = season_norm * math.sin(window_days * math.pi / 14) * 0.1

        novelty_decay = math.exp(-window_days * 0.05)
        freshness_penalty = novelty_norm * (1 - novelty_decay) * base_score * 0.1

        expected_score = (
            base_score * trend_decay
            + base_score * trend_momentum * min(window_days / 30, 1) * 0.3
            + base_score * seasonal_boost
            - freshness_penalty
        )
        expected_score = max(0, min(100, expected_score))

        prediction_consistency = self._prediction_consistency(topic)
        data_volume = self._data_volume_factor()
        confidence = base_confidence * 0.4 + prediction_consistency * 0.3 + data_volume * 0.3
        confidence = max(10, min(100, confidence))

        confidence_decay = math.exp(-window_days * 0.05)
        forecast_confidence = confidence * confidence_decay

        error_variance = self._error_variance()
        uncertainty = min(
            5 + error_variance * math.sqrt(window_days) * 2
            + (1 - trend_norm) * 10 * (window_days / 30),
            50,
        )

        return {
            "expected_score": round(expected_score, 1),
            "confidence": round(forecast_confidence, 1),
            "uncertainty": round(uncertainty, 1),
            "trend_momentum": round(trend_momentum, 3),
            "base_score": round(base_score, 1),
        }

    def _compute_trend_momentum(self, topic: str) -> float:
        """Compute trend momentum (-1 to 1) from historical trend data."""
        from mindmargin.analytics.memory import get_trend_sources
        sources = get_trend_sources(limit=100, min_confidence=0)

        topic_sources = [s for s in sources if s.get("topic", "").lower() == topic.lower()]
        if len(topic_sources) < 2:
            return 0.0

        sorted_sources = sorted(topic_sources, key=lambda s: s.get("collected_at", ""))
        recent = sorted_sources[-1]
        older = sorted_sources[0]

        try:
            recent_score = recent.get("trend_score", 0) or 0
            older_score = older.get("trend_score", 0) or 0
            if older_score > 0:
                return (recent_score - older_score) / older_score
        except (ZeroDivisionError, TypeError):
            pass

        return 0.0

    def _prediction_consistency(self, topic: str) -> float:
        """How consistent past predictions have been for this topic. 0-100."""
        from mindmargin.analytics.memory import get_outcomes
        outcomes = get_outcomes(limit=50)

        topic_outcomes = [o for o in outcomes if o.get("topic", "").lower() == topic.lower()]
        if len(topic_outcomes) < 2:
            return 50.0

        errors = [o.get("prediction_error", 0) or 0 for o in topic_outcomes]
        mae = sum(abs(e) for e in errors) / len(errors)
        return max(10, 100 - mae * 2)

    def _data_volume_factor(self) -> float:
        """How much data is available overall. 0-100."""
        from mindmargin.analytics.memory import get_outcomes, get_pipeline_history
        outcomes = get_outcomes(limit=100)
        history = get_pipeline_history(100)

        count = len(outcomes) + len(history)
        return min(count * 5, 100)

    def _error_variance(self) -> float:
        """Variance of recent prediction errors. Used for uncertainty."""
        from mindmargin.analytics.memory import get_outcomes
        outcomes = get_outcomes(limit=30)

        if len(outcomes) < 3:
            return 1.0

        errors = [o.get("prediction_error", 0) or 0 for o in outcomes]
        mean_err = sum(errors) / len(errors)
        variance = sum((e - mean_err) ** 2 for e in errors) / len(errors)
        return max(0.1, math.sqrt(variance))


def forecast_all(opportunities: list[dict] | None = None) -> list[dict]:
    """Convenience entry point for full forecast generation."""
    horizon = PredictionHorizon()
    return horizon.forecast_all(opportunities)
