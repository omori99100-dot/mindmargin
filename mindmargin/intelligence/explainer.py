"""Phase 5 — Explainable Decisions.

Provides structured explanations for every recommendation:
positive factors, negative factors, alternative candidates,
and why they lost. Outputs Markdown + JSON.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


class DecisionExplainer:
    """Generates structured explanations for opportunity-based decisions."""

    def explain(self, selected: dict, alternatives: list[dict]) -> dict:
        """Build a full structured explanation for why a topic was chosen."""
        score = selected.get("opportunity_score", 0) or 0
        confidence = selected.get("confidence", 0) or 0
        topic = selected.get("topic", "unknown")

        positive_factors = self._positive_factors(selected)
        negative_factors = self._negative_factors(selected)

        alt_explanations = []
        for alt in alternatives:
            alt_topic = alt.get("topic", "unknown")
            alt_score = alt.get("opportunity_score", 0) or 0
            alt_conf = alt.get("confidence", 0) or 0
            reasons = self._why_lost(selected, alt)
            alt_explanations.append({
                "topic": alt_topic,
                "opportunity_score": alt_score,
                "confidence": alt_conf,
                "why_lost": reasons,
            })

        explanation = {
            "selected_topic": topic,
            "opportunity_score": score,
            "confidence": confidence,
            "positive_factors": positive_factors,
            "negative_factors": negative_factors,
            "alternative_candidates": alt_explanations,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        return explanation

    def to_markdown(self, explanation: dict) -> str:
        """Render explanation as Markdown."""
        lines = [
            f"## Decision Explanation: {explanation['selected_topic']}",
            f"",
            f"**Opportunity Score:** {explanation['opportunity_score']}",
            f"**Confidence:** {explanation['confidence']}%",
            f"",
            "### Selected because:",
        ]

        for factor in explanation.get("positive_factors", []):
            lines.append(f"- ✓ {factor}")

        neg = explanation.get("negative_factors", [])
        if neg:
            lines.append("")
            lines.append("### Areas of concern:")
            for factor in neg:
                lines.append(f"- ⚠ {factor}")

        alts = explanation.get("alternative_candidates", [])
        if alts:
            lines.append("")
            lines.append("### Alternatives considered:")
            for alt in alts:
                lines.append(f"")
                lines.append(f"**{alt['topic']}** — Score: {alt['opportunity_score']}, "
                             f"Conf: {alt['confidence']}%")
                for reason in alt.get("why_lost", []):
                    lines.append(f"  - {reason}")

        return "\n".join(lines)

    def _positive_factors(self, opp: dict) -> list[str]:
        factors = []
        trend = opp.get("trend_score", 0) or 0
        novelty = opp.get("novelty", 0) or 0
        audience = opp.get("audience_match", 0) or 0
        evergreen = opp.get("evergreen_score", 0) or 0
        competition = opp.get("competition", 0.5) or 0.5
        historical = opp.get("historical_performance", 0) or 0

        val_max = 100 if max(trend, novelty, audience, evergreen, historical) > 1 else 1

        if trend / val_max > 0.6:
            factors.append(f"Strong trend acceleration ({trend:.0f}/100)")
        if novelty / val_max > 0.6:
            factors.append(f"High novelty score ({novelty:.0f}/100)")
        if audience / val_max > 0.6:
            factors.append(f"High audience similarity ({audience:.0f}/100)")
        if evergreen / val_max > 0.6:
            factors.append(f"Evergreen content potential ({evergreen:.0f}/100)")
        if competition < 0.4:
            factors.append(f"Low competition ({competition:.0%})")
        if historical / val_max > 0.6:
            factors.append(f"Historical success in similar topics ({historical:.0f}/100)")

        if not factors:
            factors.append("Moderate potential across all dimensions")

        return factors

    def _negative_factors(self, opp: dict) -> list[str]:
        factors = []
        trend = opp.get("trend_score", 0) or 0
        novelty = opp.get("novelty", 0) or 0
        audience = opp.get("audience_match", 0) or 0
        evergreen = opp.get("evergreen_score", 0) or 0
        competition = opp.get("competition", 0.5) or 0.5
        seasonality = opp.get("seasonality", 0) or 0

        val_max = 100 if max(trend, novelty, audience, evergreen, seasonality) > 1 else 1

        if trend / val_max < 0.3:
            factors.append(f"Weakening trend signal ({trend:.0f}/100)")
        if novelty / val_max < 0.3:
            factors.append(f"Low novelty — topic may feel stale ({novelty:.0f}/100)")
        if audience / val_max < 0.3:
            factors.append(f"Weak audience match ({audience:.0f}/100)")
        if competition > 0.7:
            factors.append(f"High competition ({competition:.0%})")

        return factors

    def _why_lost(self, winner: dict, loser: dict) -> list[str]:
        reasons = []
        w_score = winner.get("opportunity_score", 0) or 0
        l_score = loser.get("opportunity_score", 0) or 0

        w_components = {
            "trend_score": (winner.get("trend_score", 0) or 0),
            "audience_match": (winner.get("audience_match", 0) or 0),
            "evergreen_score": (winner.get("evergreen_score", 0) or 0),
        }
        l_components = {
            "trend_score": (loser.get("trend_score", 0) or 0),
            "audience_match": (loser.get("audience_match", 0) or 0),
            "evergreen_score": (loser.get("evergreen_score", 0) or 0),
        }

        val_max = 100

        for name, w_val in w_components.items():
            l_val = l_components.get(name, 0)
            w_norm = w_val / val_max if w_val > 1 else w_val
            l_norm = l_val / val_max if l_val > 1 else l_val
            diff = w_norm - l_norm
            if diff > 0.2:
                label = name.replace("_", " ").title()
                reasons.append(f"Lower {label} ({l_val:.0f} vs {w_val:.0f})")

        score_diff = w_score - l_score
        if score_diff > 10:
            reasons.append(f"Total opportunity score {score_diff:.0f} points lower ({l_score:.0f} vs {w_score:.0f})")

        w_conf = winner.get("confidence", 0) or 0
        l_conf = loser.get("confidence", 0) or 0
        if l_conf < w_conf - 10:
            reasons.append(f"Lower confidence ({l_conf:.0f}% vs {w_conf:.0f}%)")

        if not reasons:
            reasons.append("Marginally lower composite score")

        return reasons


def explain_decision(selected: dict, alternatives: list[dict]) -> dict:
    """Convenience entry point."""
    explainer = DecisionExplainer()
    return explainer.explain(selected, alternatives)


def format_explanation_markdown(explanation: dict) -> str:
    """Convenience entry point for Markdown output."""
    explainer = DecisionExplainer()
    return explainer.to_markdown(explanation)
