"""Feedback loop: analyze performance, update best practices, improve generation."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


def collect_analytics(pipeline_id: str, video_id: str) -> dict:
    """Collect analytics for a published video and store in memory.

    Gathers both public stats (views, likes, comments) from the Data API
    and advanced metrics (impressions, avgViewDuration, shares, subscribersGained)
    from the Analytics API when available.
    """
    from mindmargin.integrations.youtube import get_video_stats, get_analytics
    from mindmargin.analytics.memory import save_analytics, save_classification

    stats = get_video_stats(video_id)
    if stats.get("status") == "completed":
        advanced = get_analytics(video_id)
        if advanced.get("status") == "completed" and advanced.get("data"):
            stats.update({k: v for k, v in advanced["data"].items()
                          if k not in ("status", "video_id", "error")})
        save_analytics(pipeline_id, video_id, stats)
        logger.info(f"Analytics collected for {video_id}: {stats.get('views', 0)} views, "
                    f"{stats.get('impressions', 0)} impressions")
    return stats


def analyze_performance(pipeline_id: str, video_id: str) -> dict:
    """Analyze video performance and update best practices."""
    from mindmargin.analytics.memory import (
        get_best_practices, save_best_practice,
    )

    stats = collect_analytics(pipeline_id, video_id)
    views = stats.get("views", 0)
    likes = stats.get("likes", 0)
    comments = stats.get("comments", 0)

    analysis = {
        "video_id": video_id,
        "views": views,
        "likes": likes,
        "comments": comments,
        "engagement_rate": round((likes + comments) / max(views, 1) * 100, 2),
        "best_practices_updated": [],
    }

    # Infer performance patterns and store as best practices
    if views > 0:
        like_rate = likes / views
        if like_rate > 0.05:
            save_best_practice("engagement", "high_like_rate",
                               f"Videos with high like rate ({like_rate:.1%})", like_rate * 100)
            analysis["best_practices_updated"].append("high_like_rate")

        comment_rate = comments / views
        if comment_rate > 0.01:
            save_best_practice("engagement", "high_comment_rate",
                               f"Videos with high comment rate ({comment_rate:.1%})", comment_rate * 100)
            analysis["best_practices_updated"].append("high_comment_rate")

    return analysis


def generate_optimization_hints(topic: str) -> dict:
    """Generate optimization hints based on past performance data."""
    from mindmargin.analytics.memory import get_best_practices, get_best_hooks, get_best_titles

    best_hooks = get_best_hooks(3)
    best_titles = get_best_titles(3)
    practices = get_best_practices()

    hints = {
        "topic": topic,
        "suggested_hook_archetypes": [h["archetype"] for h in best_hooks if h.get("archetype")],
        "top_performing_titles": [t["title"] for t in best_titles],
        "engagement_tips": [p["value"] for p in practices if p["category"] == "engagement"],
        "best_practices_count": len(practices),
    }
    return hints


def format_feedback_report(pipeline_id: str) -> str:
    """Generate a human-readable feedback report."""
    from mindmargin.analytics.memory import (
        get_pipeline_history, get_best_practices, get_best_hooks, get_best_titles,
    )

    hooks = get_best_hooks(3)
    titles = get_best_titles(3)
    practices = get_best_practices()

    lines = ["=== FEEDBACK REPORT ===", f"Pipeline: {pipeline_id}", ""]

    if hooks:
        lines.append("Best Hooks:")
        for h in hooks:
            lines.append(f"  - [{h.get('archetype', '?')}] {h.get('hook_text', '')[:80]} "
                         f"(score: {h.get('ctr_score', 0):.0f})")
        lines.append("")

    if titles:
        lines.append("Best Titles:")
        for t in titles:
            lines.append(f"  - {t.get('title', '')[:80]} "
                         f"(CTR: {t.get('ctr', 0)}, used {t.get('used_count', 0)}x)")
        lines.append("")

    if practices:
        lines.append("Best Practices:")
        for p in practices:
            lines.append(f"  - [{p['category']}] {p.get('value', '')[:100]} "
                         f"(score: {p['score']:.1f}, n={p.get('sample_size', 1)})")
        lines.append("")

    return "\n".join(lines)
