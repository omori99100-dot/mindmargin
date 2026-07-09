"""Phase 1+2 — Outcome Tracking + Dynamic Weight Learning.

Closes the self-improvement loop:
  1. Match predicted opportunities → actual published outcomes
  2. Compute prediction error per scoring component
  3. Adjust scoring weights to minimize future error
"""

import logging
import math
from datetime import datetime
from typing import Optional

from mindmargin.config import settings
from mindmargin.intelligence.scoring import WEIGHTS

logger = logging.getLogger(__name__)

# How much of the error gets applied as a weight correction
LEARNING_RATE = 0.1
MIN_WEIGHT = 0.02
MAX_WEIGHT = 0.50


class FeedbackEngine:
    """Closes the learning loop: predicted → actual → error → update."""

    def __init__(self, learning_rate: float = LEARNING_RATE):
        self.learning_rate = learning_rate

    # ── Outcome Collection ──

    def collect_outcomes(self, days_back: int = 90) -> list[dict]:
        """Match published pipelines to their predicted opportunities.

        For each completed pipeline with analytics, find the corresponding
        opportunity_score record (by topic), compute the actual success
        metric, and persist the paired outcome + per-component errors.
        Returns newly created outcomes.
        """
        from mindmargin.analytics.memory import (
            get_pipeline_history,
            get_opportunities,
            save_outcome,
            save_prediction_error,
        )

        pipelines = get_pipeline_history(limit=200)
        opportunities = get_opportunities(min_score=0, limit=500)
        opp_by_topic: dict[str, dict] = {o["topic"]: o for o in opportunities}

        outcomes = []
        for p in pipelines:
            topic = p.get("topic", "")
            pid = p.get("id", "")
            if not topic or not pid:
                continue

            opp = opp_by_topic.get(topic)
            if opp is None:
                continue

            predicted = opp.get("opportunity_score", 0) or 0
            if predicted <= 0:
                continue

            actual = self._compute_actual_score(p)
            error = actual - predicted

            outcome_id = save_outcome(
                topic=topic,
                pipeline_id=str(pid),
                opportunity_score=predicted,
                actual_score=actual,
                prediction_error=error,
                views=p.get("views", 0) or 0,
                ctr=p.get("ctr", 0) or 0,
                watch_time_s=p.get("avg_view_duration_s", 0) or 0,
                retention=(p.get("average_view_percentage", 0) or 0) / 100,
                engagement_rate=self._engagement_rate(p),
                source=opp.get("source", ""),
                scored_at=opp.get("scored_at", ""),
                outcome_at=datetime.now().isoformat(timespec="seconds"),
            )

            if outcome_id:
                self._save_component_errors(outcome_id, opp, actual, predicted)
                outcomes.append({
                    "outcome_id": outcome_id,
                    "topic": topic,
                    "predicted": predicted,
                    "actual": actual,
                    "error": error,
                })

        if outcomes:
            avg_error = sum(o["error"] for o in outcomes) / len(outcomes)
            logger.info(f"Outcome collection: {len(outcomes)} matches, "
                        f"avg error={avg_error:+.1f} pts")

        return outcomes

    def _compute_actual_score(self, pipeline: dict) -> float:
        """Compute a normalized 0-100 actual-success score from pipeline+analytics data."""
        views = pipeline.get("views", 0) or 0
        raw_ctr = pipeline.get("ctr", 0) or 0
        ctr_val = raw_ctr / 100
        retention = (pipeline.get("average_view_percentage", 0) or 0) / 100
        watch_mins = pipeline.get("watch_time_minutes", 0) or 0
        likes = pipeline.get("likes", 0) or 0
        comments = pipeline.get("comments", 0) or 0

        _views = max(views, 1)
        engagement = (likes + comments) / _views

        views_score = min(math.log10(max(views, 1) + 1) * 25, 100)
        ctr_score = min(ctr_val / 0.10 * 100, 100)
        retention_score = min(retention / 0.70 * 100, 100)
        engagement_score = min(engagement * 500, 100)
        watch_score = min(watch_mins / max(views, 1) * 10, 100)

        score = (
            0.25 * views_score
            + 0.25 * ctr_score
            + 0.20 * retention_score
            + 0.15 * engagement_score
            + 0.15 * watch_score
        )
        return round(score, 1)

    def _engagement_rate(self, pipeline: dict) -> float:
        likes = pipeline.get("likes", 0) or 0
        comments = pipeline.get("comments", 0) or 0
        views = pipeline.get("views", 0) or 0
        if views > 0:
            return round((likes + comments) / views, 4)
        return 0.0

    # ── Per-Component Error Tracking ──

    COMPONENTS = [
        "trend_score", "novelty", "audience_match",
        "evergreen_score", "competition", "historical_performance",
        "seasonality",
    ]

    def _save_component_errors(self, outcome_id: int, opp: dict,
                                actual: float, predicted: float) -> None:
        from mindmargin.analytics.memory import save_prediction_error, get_scoring_weights

        db_weights = get_scoring_weights()
        predicted = max(predicted, 0.01)

        # Map opportunity_scores columns → component names in WEIGHTS
        col_map = {
            "trend_score": "trend_score",
            "novelty": "novelty",
            "audience_match": "audience_match",
            "evergreen_score": "evergreen_score",
            "competition": "competition_inverse",   # raw stored; invert below
            "historical_performance": "historical_performance",
            "seasonality": "seasonality",
        }

        total_score = 0.0
        component_scores: dict[str, float] = {}
        for comp, col in col_map.items():
            raw = opp.get(col.replace("_inverse", ""), 0) or 0
            if comp == "competition":
                s = (1.0 - raw) * 100
            else:
                s = raw * 100 if raw <= 1 else raw
            component_scores[comp] = s
            total_score += max(s, 0.01)

        error_ratio = (actual - predicted) / predicted

        for comp in self.COMPONENTS:
            w = db_weights.get(comp, WEIGHTS.get(comp, 0.10))
            s = component_scores.get(comp, 50)
            share = s / total_score
            contribution = w * s
            actual_contrib = share * actual
            comp_error = actual_contrib - contribution

            save_prediction_error(
                outcome_id=outcome_id,
                component=comp,
                weight=w,
                component_score=round(s, 1),
                actual_contribution=round(actual_contrib, 1),
                error=round(comp_error, 1),
            )

    # ── Dynamic Weight Learning ──

    def update_weights(self, min_samples: int = 3) -> dict[str, float]:
        """Adjust scoring weights based on recent prediction errors (gradient descent).

        For each component, computes the average signed error. If a component
        consistently under-predicts (actual > predicted), its weight increases.
        If it over-predicts, its weight decreases. Weights are clamped and
        re-normalized.
        Returns the updated weight dict.
        """
        from mindmargin.analytics.memory import (
            get_prediction_errors,
            get_scoring_weights,
            set_scoring_weight,
            reset_scoring_weights,
        )

        db_weights = get_scoring_weights()
        weights = dict(WEIGHTS)
        weights.update(db_weights)

        updated = False
        for comp in self.COMPONENTS:
            errors = get_prediction_errors(component=comp, limit=100)
            if len(errors) < min_samples:
                continue

            avg_error = sum(e["error"] for e in errors) / len(errors)
            if abs(avg_error) < 0.5:
                continue

            gradient = avg_error / 100
            delta = self.learning_rate * gradient
            new_weight = weights[comp] + delta
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            weights[comp] = round(new_weight, 4)
            updated = True

            logger.info(f"Weight update: {comp} {weights[comp]:.3f} → {new_weight:.3f} "
                        f"(avg_error={avg_error:+.1f}, gradient={gradient:+.4f})")

        if updated:
            total = sum(weights.values())
            if total > 0:
                for comp in weights:
                    weights[comp] = round(weights[comp] / total, 4)
            reset_scoring_weights(weights)

        return weights

    # ── Full Cycle ──

    def run_feedback_cycle(self) -> dict:
        """Full feedback cycle: collect outcomes → update weights.

        Returns summary dict with collection stats and new weights.
        """
        outcomes = self.collect_outcomes()
        old_weights = dict(WEIGHTS)
        new_weights = self.update_weights()

        changed = {
            k: {"old": old_weights.get(k, 0), "new": v}
            for k, v in new_weights.items()
            if abs(v - old_weights.get(k, 0)) > 0.001
        }

        logger.info(f"Feedback cycle complete: {len(outcomes)} outcomes, "
                    f"{len(changed)} weights changed")
        return {
            "outcomes_collected": len(outcomes),
            "weights_changed": len(changed),
            "weight_deltas": changed,
            "weights": new_weights,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }


def run_feedback_cycle() -> dict:
    """Convenience entry point (matches pattern of other intelligence modules)."""
    engine = FeedbackEngine()
    return engine.run_feedback_cycle()
