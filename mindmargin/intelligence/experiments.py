"""Phase 3 — Experiment Engine.

Generates content hypotheses (topic angle, Short vs Long, timing, etc.),
tracks their outcomes, and automatically evaluates winners.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

EXPERIMENT_TYPES = [
    "topic_angle",
    "title_style",
    "shorts_vs_long",
    "upload_timing",
    "thumbnail_style",
    "hook_variation",
]


class ExperimentGenerator:
    """Generates content experiment hypotheses from trends + performance history."""

    def generate_all(self) -> list[dict]:
        """Run all hypothesis generators and persist new experiments."""
        from mindmargin.analytics.memory import get_experiments, save_experiment

        experiments = []
        existing = {e["experiment_id"] for e in get_experiments(limit=200)}

        for gen in [self._from_topic_angles, self._from_title_styles,
                     self._from_format_bets, self._from_timing,
                     self._from_thumbnail_styles, self._from_hook_archetypes]:
            try:
                for exp in gen():
                    eid = exp["experiment_id"]
                    if eid not in existing:
                        save_experiment(**exp)
                        experiments.append(exp)
                        existing.add(eid)
            except Exception as e:
                logger.warning(f"Hypothesis generator failed: {e}")

        logger.info(f"Experiment generator: {len(experiments)} new hypotheses")
        return experiments

    def _from_topic_angles(self) -> list[dict]:
        """Suggest alternative angles for high-potential topics."""
        from mindmargin.analytics.memory import get_top_opportunities, get_pipeline_history
        opps = get_top_opportunities(5)
        if not opps:
            return []

        history = get_pipeline_history(20)
        published_topics = {p["topic"] for p in history if p.get("topic")}

        experiments = []
        for opp in opps:
            topic = opp["topic"]
            if topic in published_topics:
                continue
            eid = f"angle_{uuid.uuid4().hex[:8]}"
            experiments.append({
                "experiment_id": eid,
                "hypothesis": f"'{topic}' performs better as a case study format than as an explainer format",
                "experiment_type": "topic_angle",
                "topic": topic,
                "variant_a": f"Explainer: {topic}",
                "variant_b": f"Case Study: {topic}",
                "expected_gain": 15.0,
                "affected_metric": "views",
                "confidence": 0.3,
            })
        return experiments

    def _from_title_styles(self) -> list[dict]:
        """Generate title style experiments from top opportunities."""
        from mindmargin.analytics.memory import get_top_opportunities
        opps = get_top_opportunities(3)
        if not opps:
            return []

        experiments = []
        for opp in opps:
            eid = f"title_{uuid.uuid4().hex[:8]}"
            experiments.append({
                "experiment_id": eid,
                "hypothesis": f"A question-title outperforms a statement-title for '{opp['topic']}'",
                "experiment_type": "title_style",
                "topic": opp["topic"],
                "variant_a": f"How {opp['topic']} Changed Everything",
                "variant_b": f"Is {opp['topic']} the Future?",
                "expected_gain": 10.0,
                "affected_metric": "ctr",
                "confidence": 0.35,
            })
        return experiments

    def _from_format_bets(self) -> list[dict]:
        """Suggest Short vs Long-form experiments."""
        from mindmargin.analytics.memory import get_top_opportunities
        opps = get_top_opportunities(3)
        if not opps:
            return []

        experiments = []
        for opp in opps[:2]:
            eid = f"format_{uuid.uuid4().hex[:8]}"
            experiments.append({
                "experiment_id": eid,
                "hypothesis": f"A Short about '{opp['topic']}' drives more engagement than a Long-form video",
                "experiment_type": "shorts_vs_long",
                "topic": opp["topic"],
                "variant_a": f"Long-form documentary on {opp['topic']}",
                "variant_b": f"60-second Short on {opp['topic']}",
                "expected_gain": 20.0,
                "affected_metric": "engagement",
                "confidence": 0.25,
            })
        return experiments

    def _from_timing(self) -> list[dict]:
        """Suggest upload timing experiments based on past performance."""
        from mindmargin.analytics.memory import get_pipeline_history
        history = get_pipeline_history(20)
        if not history:
            return []

        experiments = []
        eid = f"timing_{uuid.uuid4().hex[:8]}"
        experiments.append({
            "experiment_id": eid,
            "hypothesis": "Publishing at 14:00 UTC drives higher initial views than 21:00 UTC",
            "experiment_type": "upload_timing",
            "topic": "general",
            "variant_a": "Publish at 21:00 UTC (current)",
            "variant_b": "Publish at 14:00 UTC",
            "expected_gain": 12.0,
            "affected_metric": "views",
            "confidence": 0.2,
        })
        return experiments

    def _from_thumbnail_styles(self) -> list[dict]:
        """Suggest thumbnail style experiments."""
        from mindmargin.analytics.memory import get_top_opportunities
        opps = get_top_opportunities(3)
        if not opps:
            return []

        experiments = []
        for opp in opps[:2]:
            eid = f"thumb_{uuid.uuid4().hex[:8]}"
            experiments.append({
                "experiment_id": eid,
                "hypothesis": f"A reaction-face thumbnail outperforms a text-only thumbnail for '{opp['topic']}'",
                "experiment_type": "thumbnail_style",
                "topic": opp["topic"],
                "variant_a": f"Text overlay on dramatic image for {opp['topic']}",
                "variant_b": f"Reaction face + minimal text for {opp['topic']}",
                "expected_gain": 8.0,
                "affected_metric": "ctr",
                "confidence": 0.3,
            })
        return experiments

    def _from_hook_archetypes(self) -> list[dict]:
        """Suggest hook variation experiments."""
        from mindmargin.analytics.memory import get_top_opportunities
        opps = get_top_opportunities(3)
        if not opps:
            return []

        experiments = []
        for opp in opps[:2]:
            eid = f"hook_{uuid.uuid4().hex[:8]}"
            experiments.append({
                "experiment_id": eid,
                "hypothesis": f"A curiosity-gap hook outperforms a bold-statement hook for '{opp['topic']}'",
                "experiment_type": "hook_variation",
                "topic": opp["topic"],
                "variant_a": f"Bold statement: This is why {opp['topic']} matters",
                "variant_b": f"Curiosity gap: What nobody tells you about {opp['topic']}",
                "expected_gain": 10.0,
                "affected_metric": "retention",
                "confidence": 0.35,
            })
        return experiments


class ExperimentEvaluator:
    """Evaluates completed experiments against analytics data."""

    def evaluate_all(self) -> list[dict]:
        """Evaluate all active experiments that have sufficient data."""
        from mindmargin.analytics.memory import (
            get_active_experiments, get_video_analytics_from_db,
            complete_experiment,
        )

        evaluated = []
        active = get_active_experiments()
        for exp in active:
            try:
                result = self._evaluate_single(exp)
                if result:
                    complete_experiment(**result)
                    evaluated.append(result)
            except Exception as e:
                logger.warning(f"Evaluation failed for {exp['experiment_id']}: {e}")

        if evaluated:
            logger.info(f"Experiment evaluator: {len(evaluated)} experiments completed")
        return evaluated

    def _evaluate_single(self, exp: dict) -> dict | None:
        """Evaluate a single experiment if both variants have analytics data."""
        control_id = exp.get("control_pipeline_id", "")
        treatment_id = exp.get("treatment_pipeline_id", "")

        if not control_id or not treatment_id:
            return None

        control_vid = self._find_video_for_pipeline(control_id)
        treatment_vid = self._find_video_for_pipeline(treatment_id)

        if not control_vid or not treatment_vid:
            return None

        control_stats = self._get_latest_analytics(control_vid)
        treatment_stats = self._get_latest_analytics(treatment_vid)

        if not control_stats or not treatment_stats:
            return None

        metric = exp.get("affected_metric", "views")
        control_val = control_stats.get(metric, 0) or 0
        treatment_val = treatment_stats.get(metric, 0) or 0

        if control_val == 0 and treatment_val == 0:
            return None

        total = control_val + treatment_val
        if total == 0:
            return None

        if metric in ("ctr", "retention", "engagement_rate"):
            control_metric = float(control_val)
            treatment_metric = float(treatment_val)
            improvement = ((treatment_metric - control_metric) / max(control_metric, 0.001)) * 100
        else:
            control_metric = float(control_val)
            treatment_metric = float(treatment_val)
            improvement = ((treatment_metric - control_metric) / max(control_metric, 1)) * 100

        if improvement > 10:
            winner = "treatment"
            stat_conf = min(0.5 + abs(improvement) / 200, 0.95)
            recommendation = f"Treatment outperformed control by {improvement:.0f}% on {metric}"
        elif improvement < -10:
            winner = "control"
            stat_conf = min(0.5 + abs(improvement) / 200, 0.95)
            recommendation = f"Control outperformed treatment by {abs(improvement):.0f}% on {metric}"
        else:
            winner = "tie"
            stat_conf = 0.1
            recommendation = f"No significant difference ({improvement:+.0f}% on {metric})"

        return {
            "experiment_id": exp["experiment_id"],
            "winner": winner,
            "statistical_confidence": round(stat_conf, 2),
            "sample_size": max(control_stats.get("views", 0) or 0,
                               treatment_stats.get("views", 0) or 0),
            "recommendation": recommendation,
            "control_metric": round(control_metric, 2),
            "treatment_metric": round(treatment_metric, 2),
        }

    def _find_video_for_pipeline(self, pipeline_id: str) -> str:
        from mindmargin.analytics.memory import get_pipeline_history
        history = get_pipeline_history(200)
        for p in history:
            if str(p.get("id", "")) == pipeline_id:
                return p.get("youtube_video_id", "") or ""
        return ""

    def _get_latest_analytics(self, video_id: str) -> dict | None:
        from mindmargin.analytics.memory import get_video_analytics_from_db
        return get_video_analytics_from_db(video_id)


def run_experiment_cycle() -> dict:
    """Full experiment cycle: generate hypotheses → evaluate active ones."""
    generator = ExperimentGenerator()
    new_experiments = generator.generate_all()

    evaluator = ExperimentEvaluator()
    completed = evaluator.evaluate_all()

    return {
        "new_hypotheses": len(new_experiments),
        "experiments_completed": len(completed),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
