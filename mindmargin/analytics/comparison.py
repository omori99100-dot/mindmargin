"""Decision Comparison Engine — compares Phase 2 intelligence with the production scoring system.

Shadow-mode only: no production decisions, no suppression, no winner selection.
Stores comparison results for dashboard/report consumption.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from mindmargin.analytics.memory import (
    get_all_classifications, save_classification,
)
from mindmargin.analytics.selection import (
    normalize_ctr, compute_score, map_score_to_label,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Phase 2 Intelligence (shadow) functions
# ──────────────────────────────────────────────

def normalize(ctr: float, retention: float, velocity: float) -> tuple[float, float, float]:
    """Normalize metrics to 0-1 range for scoring."""
    ctr_norm = normalize_ctr(ctr)
    retention_norm = min(max(retention, 0.0), 1.0)
    velocity_norm = min(velocity / 10.0, 1.0)
    return ctr_norm, retention_norm, velocity_norm


def phase2_decision(ctr: float, retention: float, velocity: float) -> dict:
    """Phase 2 intelligence decision (shadow). Returns score + label + confidence."""
    ctr_n, ret_n, vel_n = normalize(ctr, retention, velocity)
    score = compute_score(ctr_n, ret_n, vel_n)
    label = map_score_to_label(score)
    return {
        "phase2_score": round(score, 4),
        "phase2_label": label,
        "phase2_confidence": round(min(score + 0.2, 1.0), 4),
        "phase2_ctr_norm": round(ctr_n, 4),
        "phase2_retention_norm": round(ret_n, 4),
        "phase2_velocity_norm": round(vel_n, 4),
    }


# ──────────────────────────────────────────────
# Comparison Engine
# ──────────────────────────────────────────────

def compare_decision(production: dict, phase2: dict) -> dict:
    """Compare a production classification against the Phase 2 shadow decision.

    Returns a dict with:
    - agreement: whether both systems agree on the label
    - production_label: current production label
    - phase2_label: shadow intelligence label
    - score_delta: difference in underlying score (positive = phase2 higher)
    """
    prod_label = production.get("classification", "unknown")
    p2_label = phase2.get("phase2_label", "unknown")
    agree = prod_label == p2_label

    return {
        "agreement": agree,
        "production_label": prod_label,
        "phase2_label": p2_label,
        "production_confidence": production.get("confidence", 0),
        "phase2_confidence": phase2.get("phase2_confidence", 0),
        "score_delta": round(
            phase2.get("phase2_score", 0) - production.get("confidence", 0),
            4,
        ),
    }


def run_comparison_cycle() -> dict:
    """Run comparison across all classified videos.

    Shadow mode: reads existing classifications, computes Phase 2 scores,
    compares results, and persists comparison data.
    """
    classifications = get_all_classifications(limit=500)
    if not classifications:
        return {"status": "skipped", "total": 0}

    comparisons = []
    results = {"agreed": 0, "disagreed": 0, "total": 0}

    for cls in classifications:
        ctr = cls.get("ctr", 0) or 0
        retention = cls.get("retention", 0) or 0
        velocity = cls.get("velocity", 0) or 0

        p2 = phase2_decision(ctr, retention, velocity)
        comp = compare_decision(cls, p2)

        comparisons.append(comp)
        results["total"] += 1
        if comp["agreement"]:
            results["agreed"] += 1
        else:
            results["disagreed"] += 1

    # Compute agreement rate
    agreement_rate = (results["agreed"] / max(results["total"], 1)) * 100
    disagreement_rate = (results["disagreed"] / max(results["total"], 1)) * 100

    # False positive/negative analysis: where Phase 2 is more/less optimistic
    false_positives = [
        c for c in comparisons
        if c["production_label"] in ("weak_signal", "insufficient_signal")
        and c["phase2_label"] in ("winner_candidate", "keep_testing")
    ]
    false_negatives = [
        c for c in comparisons
        if c["production_label"] in ("winner_candidate", "keep_testing")
        and c["phase2_label"] in ("weak_signal", "insufficient_signal")
    ]

    report = {
        "status": "completed",
        "timestamp": datetime.utcnow().isoformat(),
        "total_videos": results["total"],
        "agreement_rate": round(agreement_rate, 1),
        "disagreement_rate": round(disagreement_rate, 1),
        "agreed": results["agreed"],
        "disagreed": results["disagreed"],
        "false_positives": {
            "count": len(false_positives),
            "examples": false_positives[:5],
        },
        "false_negatives": {
            "count": len(false_negatives),
            "examples": false_negatives[:5],
        },
        "recommendation": (
            "Systems aligned" if agreement_rate >= 80
            else "Calibrate Phase 2 thresholds" if disagreement_rate > 20
            else "Monitor for drift"
        ),
    }

    logger.info(
        f"Comparison cycle: {results['total']} videos, "
        f"{agreement_rate:.0f}% agreement, "
        f"{len(false_positives)} false positives, "
        f"{len(false_negatives)} false negatives"
    )
    return report
