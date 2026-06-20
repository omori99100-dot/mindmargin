"""Channel Brain — executive orchestration layer for the autonomous growth engine.

Evaluates overall channel health, determines publishing frequency, prioritizes
topics, allocates experiments, schedules A/B tests, adjusts selection pressure,
and manages growth strategy — all through existing analytics and memory systems.

No new AI models, no external APIs. Pure deterministic decision-making from
stored performance data.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from mindmargin.analytics.memory import (
    get_all_classifications, get_pipeline_history, get_pipeline_stats,
    get_top_performers, get_classification_counts,
    get_best_practices, get_best_hooks, get_best_titles,
)
from mindmargin.analytics.monitoring import get_system_health, generate_daily_health_report
from mindmargin.analytics.comparison import run_comparison_cycle
from mindmargin.analytics.growth_engine import (
    expand_topic_tree, identify_growth_opportunities,
    run_growth_analysis, analyze_portfolio_balance,
)

logger = logging.getLogger(__name__)


@dataclass
class BrainDecision:
    """A single decision or recommendation from the Channel Brain."""
    domain: str          # 'publishing', 'topic', 'experiment', 'selection', 'growth'
    action: str          # short action label
    rationale: str       # why this decision was made
    confidence: float    # 0-1
    priority: int        # 1 (highest) to 5 (lowest)
    parameters: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# Publishing Frequency
# ──────────────────────────────────────────────

def _recommend_publishing_frequency() -> BrainDecision:
    """Determine optimal publishing cadence based on channel maturity.

    Rules:
    - <10 videos: 2/week (build catalog)
    - 10-30 videos: 1/week (sustain)
    - >30 videos with winners: 1/2weeks (quality focus)
    - >50 videos: experiment with 1/week + A/B rotation
    """
    stats = get_pipeline_stats()
    total = stats.get("total_pipelines", 0)
    published = stats.get("published_videos", 0)

    if published < 10:
        return BrainDecision(
            domain="publishing",
            action="increase_frequency",
            rationale=f"Only {published} videos published — need catalog depth",
            confidence=0.9,
            priority=1,
            parameters={"recommended_per_week": 2, "reason": "catalog_build"},
        )
    elif published < 30:
        return BrainDecision(
            domain="publishing",
            action="maintain_frequency",
            rationale=f"{published} videos published — sustaining cadence",
            confidence=0.85,
            priority=2,
            parameters={"recommended_per_week": 1, "reason": "sustain"},
        )
    elif published < 50:
        return BrainDecision(
            domain="publishing",
            action="reduce_frequency",
            rationale=f"{published} videos — prioritize quality and winner replication",
            confidence=0.75,
            priority=2,
            parameters={"recommended_per_week": 0.5, "reason": "quality_focus"},
        )
    else:
        return BrainDecision(
            domain="publishing",
            action="optimize_frequency",
            rationale=f"Mature channel ({published} videos) — optimize cadence with A/B",
            confidence=0.7,
            priority=3,
            parameters={"recommended_per_week": 1, "reason": "optimize"},
        )


# ──────────────────────────────────────────────
# Topic Prioritization
# ──────────────────────────────────────────────

def _prioritize_topics() -> BrainDecision:
    """Select the highest-impact next topic."""
    opportunities = identify_growth_opportunities()
    if not opportunities:
        return BrainDecision(
            domain="topic",
            action="use_existing_map",
            rationale="No growth opportunities identified — fall back to expansion map",
            confidence=0.5,
            priority=3,
            parameters={"topic": "", "source": "static_map"},
        )

    top = opportunities[0]
    return BrainDecision(
        domain="topic",
        action=top.get("type", "generic"),
        rationale=top.get("rationale", "Highest-scored opportunity"),
        confidence=min(top["score"] + 0.2, 1.0),
        priority=1,
        parameters={
            "topic": top["topic"],
            "source": top.get("type", "opportunity"),
            "score": top["score"],
        },
    )


# ──────────────────────────────────────────────
# Experiment Allocation
# ──────────────────────────────────────────────

def _allocate_experiments() -> BrainDecision:
    """Determine how many A/B experiments to run concurrently."""
    counts = get_classification_counts()
    winners = counts.get("winner_candidate", 0)
    testing = counts.get("keep_testing", 0)
    total = sum(counts.values())

    if total < 5:
        return BrainDecision(
            domain="experiment",
            action="no_experiments",
            rationale=f"Insufficient data ({total} classifications) for meaningful A/B",
            confidence=0.9,
            priority=5,
            parameters={"max_active_tests": 0},
        )

    # More winners → more experiments (validation-driven)
    max_tests = min(winners * 2 + 3, 10)
    return BrainDecision(
        domain="experiment",
        action="allocate_experiments",
        rationale=f"{winners} winners, {testing} testing — allocating {max_tests} slots",
        confidence=min(0.5 + winners * 0.1, 0.95),
        priority=2,
        parameters={"max_active_tests": max_tests, "winner_count": winners},
    )


# ──────────────────────────────────────────────
# Selection Pressure Adjustment
# ──────────────────────────────────────────────

def _adjust_selection_pressure() -> BrainDecision:
    """Adjust how aggressively the selection system suppresses patterns.

    Low classification volume → conservative (high bar for suppression)
    High classification volume → normal
    Many weak signals → aggressive
    """
    counts = get_classification_counts()
    total = sum(counts.values())
    weak = counts.get("weak_signal", 0)
    insufficient = counts.get("insufficient_signal", 0)

    if total < 10:
        return BrainDecision(
            domain="selection",
            action="conservative",
            rationale=f"Only {total} classifications — high suppression bar",
            confidence=0.85,
            priority=4,
            parameters={"suppression_threshold": 5, "decay_base": 0.8},
        )

    weak_ratio = weak / max(total, 1)
    if weak_ratio > 0.3:
        return BrainDecision(
            domain="selection",
            action="aggressive",
            rationale=f"{weak_ratio:.0%} weak signals — increase suppression pressure",
            confidence=0.7,
            priority=3,
            parameters={"suppression_threshold": 2, "decay_base": 0.6},
        )

    return BrainDecision(
        domain="selection",
        action="normal",
        rationale=f"{weak_ratio:.0%} weak signals — standard pressure",
        confidence=0.8,
        priority=4,
        parameters={"suppression_threshold": 3, "decay_base": 0.7},
    )


# ──────────────────────────────────────────────
# Growth Strategy
# ──────────────────────────────────────────────

def _evaluate_growth_strategy() -> BrainDecision:
    """Evaluate whether to explore new domains or double down on existing ones."""
    balance = analyze_portfolio_balance()
    hhi = balance.get("concentration_index", 0)

    if hhi > 50:
        return BrainDecision(
            domain="growth",
            action="diversify",
            rationale=f"High concentration (HHI={hhi}) — explore new topic domains",
            confidence=0.8,
            priority=2,
            parameters={"hhi": hhi, "direction": "explore"},
        )
    elif hhi < 20:
        return BrainDecision(
            domain="growth",
            action="deepen_strong_clusters",
            rationale=f"Low concentration (HHI={hhi}) — double down on winners",
            confidence=0.75,
            priority=3,
            parameters={"hhi": hhi, "direction": "deepen"},
        )
    else:
        return BrainDecision(
            domain="growth",
            action="balanced",
            rationale=f"Moderate concentration (HHI={hhi}) — maintain balanced approach",
            confidence=0.7,
            priority=3,
            parameters={"hhi": hhi, "direction": "balanced"},
        )


# ──────────────────────────────────────────────
# Channel Health Assessment
# ──────────────────────────────────────────────

def assess_channel_health() -> dict:
    """Evaluate overall channel health across all dimensions.

    Returns a structured health assessment with scores 0-10 per dimension.
    """
    stats = get_pipeline_stats()
    counts = get_classification_counts()
    total_classified = sum(counts.values())
    winners = counts.get("winner_candidate", 0)
    health = get_system_health()

    dimensions = {}

    # Content Volume (0-10)
    published = stats.get("published_videos", 0)
    dimensions["content_volume"] = {
        "score": min(published * 2, 10),
        "label": "high" if published > 20 else "medium" if published > 10 else "low",
        "value": published,
    }

    # Performance Quality (0-10)
    if total_classified > 0:
        win_ratio = winners / total_classified
        dimensions["performance_quality"] = {
            "score": round(win_ratio * 10, 1),
            "label": "strong" if win_ratio > 0.2 else "developing" if win_ratio > 0.1 else "emerging",
            "value": round(win_ratio * 100, 1),
        }
    else:
        dimensions["performance_quality"] = {"score": 0, "label": "no_data", "value": 0}

    # System Reliability (0-10)
    if health.pipeline_status == "healthy":
        dimensions["system_reliability"] = {"score": 9, "label": "healthy", "value": 0}
    elif health.pipeline_status == "stable_with_errors":
        dimensions["system_reliability"] = {"score": 6, "label": "stable_with_errors", "value": health.total_failures}
    else:
        dimensions["system_reliability"] = {"score": 3, "label": "degraded", "value": health.total_failures}

    # Evolution Maturity (0-10)
    ab_active = health.active_ab_tests
    dimensions["evolution_maturity"] = {
        "score": min(ab_active * 2 + (1 if winners > 0 else 0) * 3, 10),
        "label": "mature" if ab_active > 3 else "developing" if ab_active > 0 else "initial",
        "value": ab_active,
    }

    # Overall score
    overall = round(
        sum(d["score"] for d in dimensions.values()) / len(dimensions), 1
    )

    return {
        "status": "completed",
        "assessed_at": datetime.utcnow().isoformat(),
        "overall_score": overall,
        "overall_label": (
            "excellent" if overall >= 8
            else "good" if overall >= 6
            else "fair" if overall >= 4
            else "needs_attention"
        ),
        "dimensions": dimensions,
        "total_videos": published,
        "winners": winners,
        "conclusion": (
            "Channel is healthy and growing" if overall >= 6
            else "Channel needs more content volume to reach autonomous operation"
        ),
    }


# ──────────────────────────────────────────────
# Executive Decision Cycle
# ──────────────────────────────────────────────

def run_brain_cycle() -> dict:
    """Run the full Channel Brain decision cycle.

    Produces a prioritized list of decisions/recommendations for the
    autonomous growth system to execute.
    """
    logger.info("Channel Brain cycle started")

    decisions = [
        _recommend_publishing_frequency(),
        _prioritize_topics(),
        _allocate_experiments(),
        _adjust_selection_pressure(),
        _evaluate_growth_strategy(),
    ]

    health = assess_channel_health()

    # Sort by priority (1 = highest)
    decisions.sort(key=lambda d: d.priority)

    report = {
        "status": "completed",
        "timestamp": datetime.utcnow().isoformat(),
        "channel_health": health,
        "decisions": [
            {
                "domain": d.domain,
                "action": d.action,
                "rationale": d.rationale,
                "confidence": d.confidence,
                "priority": d.priority,
                "parameters": d.parameters,
            }
            for d in decisions
        ],
        "top_action": decisions[0].action if decisions else "",
        "top_topic": decisions[1].parameters.get("topic", "") if len(decisions) > 1 else "",
    }

    logger.info(f"Channel Brain cycle complete: {len(decisions)} decisions, "
                f"health={health['overall_score']}/10")
    return report
