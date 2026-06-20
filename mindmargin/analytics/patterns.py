"""Pattern analysis: mine stored performance data for retention, pacing, and hook insights."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from mindmargin.analytics.memory import (
    get_best_practices, get_pipeline_history, get_top_performers,
    get_best_hooks, get_best_titles, save_best_practice,
    get_analytics_by_week, save_drift_snapshot, get_drift_history,
)

logger = logging.getLogger(__name__)


def analyze_retention_patterns() -> dict:
    """Analyze which video durations and section structures retain viewers best."""
    tops = get_top_performers("avg_view_duration_s", 10)
    if not tops:
        return {"status": "insufficient_data", "patterns": []}

    patterns = []
    for t in tops:
        patterns.append({
            "topic": t["topic"],
            "avg_view_duration_s": t.get("avg_view_duration_s", 0),
            "views": t.get("views", 0),
            "video_id": t.get("youtube_url", ""),
        })

    # Derive pacing insight
    if patterns:
        avg_retention = sum(p["avg_view_duration_s"] for p in patterns) / len(patterns)
        insight = (
            f"Top videos average {avg_retention:.0f}s view duration "
            f"across {len(patterns)} videos"
        )
        save_best_practice("retention", "avg_view_duration",
                           insight, avg_retention)
        logger.info(f"Retention pattern: {insight}")

    return {
        "status": "completed",
        "patterns": patterns,
        "avg_retention_s": round(avg_retention, 1) if patterns else 0,
    }


def analyze_hook_performance() -> dict:
    """Identify which hook archetypes and emotional triggers drive CTR."""
    hooks = get_best_hooks(20)
    if not hooks:
        return {"status": "insufficient_data", "archetype_rankings": []}

    archetype_scores = {}
    for h in hooks:
        arch = h.get("archetype", "unknown")
        score = h.get("actual_ctr") or h.get("ctr_score", 0)
        if arch not in archetype_scores:
            archetype_scores[arch] = []
        archetype_scores[arch].append(score)

    rankings = []
    for arch, scores in archetype_scores.items():
        avg = sum(scores) / len(scores) if scores else 0
        rankings.append({"archetype": arch, "avg_score": round(avg, 1), "count": len(scores)})
        save_best_practice("hook_archetype", arch,
                           f"Hook archetype '{arch}' averages {avg:.1f} score",
                           avg)

    rankings.sort(key=lambda r: r["avg_score"], reverse=True)
    logger.info(f"Hook analysis: {len(rankings)} archetypes ranked")

    return {
        "status": "completed",
        "archetype_rankings": rankings,
        "top_archetype": rankings[0]["archetype"] if rankings else "",
    }


def analyze_pacing_patterns() -> dict:
    """Analyze relationship between word count, duration, and engagement."""
    tops = get_top_performers("avg_view_duration_s", 10)
    history = get_pipeline_history(50)

    if not tops or len(history) < 3:
        return {"status": "insufficient_data", "insights": []}

    pacing_data = []
    for h in history:
        wc = h.get("word_count", 0)
        dur = h.get("video_duration_s", 0)
        if wc > 0 and dur > 0:
            wpm = (wc / dur) * 60
            pacing_data.append({"wpm": round(wpm, 1), "word_count": wc, "duration_s": dur})

    insights = []
    if pacing_data:
        avg_wpm = sum(p["wpm"] for p in pacing_data) / len(pacing_data)
        insight = f"Average pacing: {avg_wpm:.0f} words/min across {len(pacing_data)} videos"
        save_best_practice("pacing", "avg_words_per_min", insight, 100 - abs(avg_wpm - 150))
        insights.append(insight)

    return {
        "status": "completed",
        "pacing_data": pacing_data[:20],
        "insights": insights,
    }


def analyze_topic_performance() -> dict:
    """Analyze which topics and categories perform best."""
    tops = get_top_performers("views", 20)
    if not tops:
        return {"status": "insufficient_data", "top_topics": []}

    topics = []
    for t in tops:
        topics.append({
            "topic": t["topic"],
            "views": t.get("views", 0),
            "likes": t.get("likes", 0),
            "url": t.get("youtube_url", ""),
        })

    if topics:
        best_topic = topics[0]["topic"]
        best_views = topics[0]["views"]
        save_best_practice("topic", "best_performing",
                           f"Best topic: '{best_topic}' with {best_views} views",
                           min(best_views, 100))
        logger.info(f"Top topic: {best_topic} ({best_views} views)")

    return {
        "status": "completed",
        "top_topics": topics,
    }


def full_pattern_analysis() -> dict:
    """Run all pattern analyses and return consolidated report."""
    retention = analyze_retention_patterns()
    hooks = analyze_hook_performance()
    pacing = analyze_pacing_patterns()
    topics = analyze_topic_performance()

    best_practices = get_best_practices()

    return {
        "status": "completed",
        "retention": retention,
        "hooks": hooks,
        "pacing": pacing,
        "topics": topics,
        "best_practices_count": len(best_practices),
        "analyzed_at": datetime.utcnow().isoformat(),
    }


def generate_script_guidance() -> dict:
    """Generate actionable guidance for script generation from learned patterns."""
    hooks = analyze_hook_performance()
    pacing = analyze_pacing_patterns()
    retention = analyze_retention_patterns()

    guidance = {
        "recommended_hook_archetype": hooks.get("top_archetype", "curiosity_gap"),
        "archetype_rankings": hooks.get("archetype_rankings", []),
        "pacing_insights": pacing.get("insights", []),
        "retention_benchmark_s": retention.get("avg_retention_s", 0),
    }
    return guidance


# ──────────────────────────────────────────────
# Performance Drift Tracking
# ──────────────────────────────────────────────

DRIFT_THRESHOLD_PCT = 5.0   # minimum % change to classify as positive/negative
MIN_CONFIDENCE_SAMPLES = 3  # minimum videos per period for reliable comparison


def _compute_metric_averages() -> list[dict]:
    """Aggregate analytics by week with derived engagement metrics."""
    weeks = get_analytics_by_week()
    for w in weeks:
        v = w.get("avg_views", 0) or 0
        l = w.get("avg_likes", 0) or 0
        c = w.get("avg_comments", 0) or 0
        r = w.get("avg_retention_s", 0) or 0
        w["estimated_ctr_pct"] = round((l / max(v, 1)) * 100, 2) if v > 0 else 0.0
        w["engagement_per_view"] = round((l + c) / max(v, 1), 4) if v > 0 else 0.0
        w["retention_rate_pct"] = 0.0  # requires video duration from pipelines table
    return weeks


def compute_weekly_trends() -> dict:
    """Compute weekly performance trends from stored analytics."""
    weeks = _compute_metric_averages()
    if not weeks:
        return {
            "status": "insufficient_data",
            "periods": 0,
            "metrics": {},
        }

    metrics = {
        "estimated_ctr": {
            "label": "Estimated CTR (likes/views)",
            "values": [],
            "unit": "%",
        },
        "avg_retention_s": {
            "label": "Average View Duration",
            "values": [],
            "unit": "s",
        },
        "avg_views": {
            "label": "Average Views",
            "values": [],
            "unit": "",
        },
        "engagement_per_view": {
            "label": "Engagement Rate (likes+comments/view)",
            "values": [],
            "unit": "",
        },
    }

    for w in weeks:
        week_label = w["week"]
        metrics["estimated_ctr"]["values"].append({
            "week": week_label, "value": w["estimated_ctr_pct"],
            "videos": w["video_count"],
        })
        metrics["avg_retention_s"]["values"].append({
            "week": week_label, "value": round(w["avg_retention_s"], 1),
            "videos": w["video_count"],
        })
        metrics["avg_views"]["values"].append({
            "week": week_label, "value": round(w["avg_views"], 0),
            "videos": w["video_count"],
        })
        metrics["engagement_per_view"]["values"].append({
            "week": week_label, "value": w["engagement_per_view"],
            "videos": w["video_count"],
        })

    return {
        "status": "completed",
        "periods": len(weeks),
        "metrics": metrics,
    }


def compute_drift() -> dict:
    """Compare current vs previous period performance. Classify drift."""
    weeks = _compute_metric_averages()
    if len(weeks) < 2:
        return {
            "status": "insufficient_data",
            "reason": f"Need >=2 weeks of data, have {len(weeks)}",
            "drifts": [],
        }

    current = weeks[-1]
    previous = weeks[-2]

    drifts = []
    snapshot_date = datetime.utcnow().strftime("%Y-%m-%d")

    comparisons = [
        ("estimated_ctr", "Estimated CTR",
         current["estimated_ctr_pct"], previous["estimated_ctr_pct"],
         current["video_count"], previous["video_count"]),
        ("avg_retention_s", "Avg View Duration",
         current["avg_retention_s"], previous["avg_retention_s"],
         current["video_count"], previous["video_count"]),
        ("avg_views", "Avg Views",
         current["avg_views"], previous["avg_views"],
         current["video_count"], previous["video_count"]),
        ("engagement_per_view", "Engagement Rate",
         current["engagement_per_view"], previous["engagement_per_view"],
         current["video_count"], previous["video_count"]),
    ]

    for metric_key, metric_label, cur, prev, n_cur, n_prev in comparisons:
        # Skip if no data in either period
        if cur == 0 and prev == 0:
            continue
        # Compute percentage change (handle division by zero)
        if prev != 0:
            pct_change = ((cur - prev) / abs(prev)) * 100
        elif cur != 0:
            pct_change = 100.0  # from zero to something is infinite, cap at 100
        else:
            pct_change = 0.0

        # Confidence: based on sample sizes
        total_samples = n_cur + n_prev
        confidence = min(total_samples / (MIN_CONFIDENCE_SAMPLES * 2), 1.0)

        # Classify drift
        if total_samples < MIN_CONFIDENCE_SAMPLES:
            classification = "neutral"
            confidence = min(confidence, 0.3)
        elif pct_change >= DRIFT_THRESHOLD_PCT:
            classification = "positive"
        elif pct_change <= -DRIFT_THRESHOLD_PCT:
            classification = "negative"
        else:
            classification = "neutral"

        drift_entry = {
            "metric": metric_key,
            "label": metric_label,
            "current_value": round(cur, 2),
            "previous_value": round(prev, 2),
            "pct_change": round(pct_change, 1),
            "drift_classification": classification,
            "confidence": round(confidence, 2),
            "samples_current": n_cur,
            "samples_previous": n_prev,
        }
        drifts.append(drift_entry)

        # Persist to memory
        save_drift_snapshot(
            snapshot_date=snapshot_date,
            metric=metric_key,
            current_value=cur,
            previous_value=prev,
            pct_change=pct_change,
            drift_classification=classification,
            confidence=confidence,
            sample_size_current=n_cur,
            sample_size_previous=n_prev,
        )

    # Overall drift classification
    positive_count = sum(1 for d in drifts if d["drift_classification"] == "positive")
    negative_count = sum(1 for d in drifts if d["drift_classification"] == "negative")
    high_conf = [d for d in drifts if d["confidence"] >= 0.5]

    if high_conf:
        pos_high = sum(1 for d in high_conf if d["drift_classification"] == "positive")
        neg_high = sum(1 for d in high_conf if d["drift_classification"] == "negative")
        if pos_high > neg_high:
            overall = "positive"
        elif neg_high > pos_high:
            overall = "negative"
        else:
            overall = "neutral"
    else:
        overall = "neutral"

    # Learning validation
    if overall == "positive":
        learning_status = "OPTIMIZATION_VERIFIED — performance improving"
    elif overall == "negative":
        learning_status = "OPTIMIZATION_FAILING — performance degrading"
    else:
        learning_status = "OPTIMIZATION_NEUTRAL — no significant change detected"

    return {
        "status": "completed",
        "snapshot_date": snapshot_date,
        "periods_compared": f"{previous['week']} vs {current['week']}",
        "overall_drift": overall,
        "learning_status": learning_status,
        "drifts": drifts,
    }


def generate_drift_report() -> dict:
    """Generate full structured drift report with trends + classification."""
    trends = compute_weekly_trends()
    drift = compute_drift()
    history = get_drift_history(limit=30)

    return {
        "status": drift["status"],
        "trends": trends,
        "drift": drift,
        "historical_drifts": history,
        "generated_at": datetime.utcnow().isoformat(),
    }
