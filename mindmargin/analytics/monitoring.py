"""Observability & monitoring layer for the MindMargin evolution system.

Tracks pipeline health, evolution decisions, API failures, and system
reliability metrics.  Generates daily and weekly health reports.
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Metrics Store (in-memory + optional JSON persist)
# ──────────────────────────────────────────────

_METRICS_STORE: dict[str, list[dict]] = defaultdict(list)
_METRICS_FILE = Path(settings.storage.output_root).parent / "data" / "metrics.json"


def _persist_metrics():
    """Write current metrics to disk for dashboard consumption."""
    try:
        _METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(str(_METRICS_FILE), "w") as f:
            json.dump(dict(_METRICS_STORE), f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Metrics persist failed: {e}")


def _load_metrics():
    """Load metrics from disk into memory store."""
    try:
        if _METRICS_FILE.exists():
            with open(str(_METRICS_FILE)) as f:
                data = json.load(f)
                for k, v in data.items():
                    _METRICS_STORE[k] = v
    except Exception as e:
        logger.warning(f"Metrics load failed: {e}")


def record_event(category: str, label: str, value: Any = 1, metadata: Optional[dict] = None):
    """Record a single event in the metrics store.

    category: 'upload', 'generation_failure', 'analytics_failure',
              'youtube_api_failure', 'ab_status', 'selection_status'
    label:    specific event name (e.g. 'upload_success', 'rotation_skipped')
    value:    numeric value (default 1 for counter)
    metadata: optional dict with additional context
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "category": category,
        "label": label,
        "value": value,
        "metadata": metadata or {},
    }
    _METRICS_STORE[category].append(entry)
    _persist_metrics()


def get_metrics(category: Optional[str] = None,
                since: Optional[datetime] = None,
                limit: int = 100) -> list[dict]:
    """Retrieve recorded events, optionally filtered."""
    _load_metrics()
    if category:
        items = _METRICS_STORE.get(category, [])
    else:
        items = []
        for cat_list in _METRICS_STORE.values():
            items.extend(cat_list)
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    if since:
        items = [i for i in items if i.get("timestamp", "") >= since.isoformat()]
    return items[:limit]


# ──────────────────────────────────────────────
# Pipeline Runtime Tracking
# ──────────────────────────────────────────────

_RUNTIME_STORE: dict[str, float] = {}
_RUNTIME_STAGE_STORE: dict[str, list[dict]] = defaultdict(list)


def record_runtime(pipeline_id: str, duration_s: float):
    """Record how long a pipeline execution took."""
    _RUNTIME_STORE[pipeline_id] = duration_s
    record_event("pipeline_runtime", pipeline_id, duration_s)


def record_stage_runtime(pipeline_id: str, stage: str, duration_s: float,
                         metadata: Optional[dict] = None):
    """Record per-stage runtime for detailed performance analysis."""
    entry = {
        "pipeline_id": pipeline_id,
        "stage": stage,
        "duration_s": duration_s,
        "timestamp": datetime.utcnow().isoformat(),
        "metadata": metadata or {},
    }
    _RUNTIME_STAGE_STORE[stage].append(entry)
    record_event(f"stage_runtime_{stage}", pipeline_id, duration_s,
                 metadata={"stage": stage, **entry["metadata"]})


def get_runtime_summary() -> dict:
    """Aggregate per-stage runtime statistics (avg, min, max, p95, count)."""
    categories = {
        "pipeline": "pipeline_runtime_seconds",
        "research": "research_runtime_seconds",
        "script": "script_runtime_seconds",
        "tts": "tts_runtime_seconds",
        "render": "render_runtime_seconds",
        "publish": "publish_runtime_seconds",
    }
    _load_metrics()
    summary = {}
    for label, category in categories.items():
        events = _METRICS_STORE.get(category, [])
        vals = [e["value"] for e in events if isinstance(e.get("value"), (int, float))]
        if vals:
            sorted_vals = sorted(vals)
            n = len(sorted_vals)
            summary[label] = {
                "avg_s": round(sum(vals) / n, 2),
                "min_s": round(min(vals), 2),
                "max_s": round(max(vals), 2),
                "p95_s": round(sorted_vals[int(n * 0.95)], 2),
                "count": n,
            }
        else:
            summary[label] = {"avg_s": 0, "min_s": 0, "max_s": 0, "p95_s": 0, "count": 0}
    return summary


def get_runtime_trends(days: int = 7) -> dict:
    """Show runtime trends over time for each stage."""
    _load_metrics()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    stage_categories = {
        "research": "research_runtime_seconds",
        "script": "script_runtime_seconds",
        "tts": "tts_runtime_seconds",
        "render": "render_runtime_seconds",
        "pipeline": "pipeline_runtime_seconds",
        "publish": "publish_runtime_seconds",
    }
    trends = {}
    for stage, category in stage_categories.items():
        events = [
            e for e in _METRICS_STORE.get(category, [])
            if e.get("timestamp", "") >= since
        ]
        events.sort(key=lambda x: x["timestamp"])
        trends[stage] = [
            {"timestamp": e["timestamp"], "duration_s": e["value"]}
            for e in events
        ]
    return trends


def performance_report() -> dict:
    """Generate a comprehensive performance report with bottleneck ranking."""
    summary = get_runtime_summary()
    trends = get_runtime_trends()

    # Bottleneck ranking: sort stages by average runtime descending
    stages_with_data = [
        {"stage": k, **v}
        for k, v in summary.items()
        if v["count"] > 0 and k != "pipeline"
    ]
    bottleneck_ranking = sorted(stages_with_data, key=lambda x: x["avg_s"], reverse=True)

    # Identify top bottleneck
    top_bottleneck = bottleneck_ranking[0] if bottleneck_ranking else None

    return {
        "report_type": "performance",
        "generated_at": datetime.utcnow().isoformat(),
        "runtime_summary": summary,
        "bottleneck_ranking": bottleneck_ranking,
        "top_bottleneck": top_bottleneck,
        "total_cycles": summary.get("pipeline", {}).get("count", 0),
        "average_total_runtime_s": summary.get("pipeline", {}).get("avg_s", 0),
        "trends_available": len(trends.get("pipeline", [])) > 1,
    }


def get_runtime_stats() -> dict:
    """Average, min, max pipeline runtime."""
    if not _RUNTIME_STORE:
        return {"avg_s": 0, "min_s": 0, "max_s": 0, "count": 0}
    vals = list(_RUNTIME_STORE.values())
    return {
        "avg_s": round(sum(vals) / len(vals), 1),
        "min_s": round(min(vals), 1),
        "max_s": round(max(vals), 1),
        "count": len(vals),
    }


# ──────────────────────────────────────────────
# Health Summaries
# ──────────────────────────────────────────────


@dataclass
class SystemHealth:
    pipeline_status: str = "unknown"
    total_uploads: int = 0
    total_failures: int = 0
    last_upload: Optional[str] = None
    last_failure: Optional[str] = None
    active_ab_tests: int = 0
    videos_classified: int = 0
    api_quota_remaining: Optional[int] = None
    retry_count_24h: int = 0
    summary: str = ""


def get_system_health() -> SystemHealth:
    """Produce a snapshot of overall system health."""
    _load_metrics()
    health = SystemHealth()

    uploads = _METRICS_STORE.get("upload", [])
    health.total_uploads = sum(e["value"] for e in uploads if e["label"] == "upload_success")
    health.last_upload = next(
        (e["timestamp"] for e in reversed(uploads) if e["label"] == "upload_success"),
        None,
    )

    failures = (
        _METRICS_STORE.get("generation_failure", [])
        + _METRICS_STORE.get("analytics_failure", [])
        + _METRICS_STORE.get("youtube_api_failure", [])
    )
    health.total_failures = len(failures)
    health.last_failure = failures[-1]["timestamp"] if failures else None

    since_24h = datetime.utcnow() - timedelta(hours=24)
    retries = [e for e in _METRICS_STORE.get("pipeline_runtime", [])
               if e.get("timestamp", "") >= since_24h.isoformat()
               and e.get("metadata", {}).get("retry", False)]
    health.retry_count_24h = len(retries)

    ab_active = _METRICS_STORE.get("ab_status", [])
    health.active_ab_tests = sum(e["value"] for e in ab_active if e["label"] == "active_tests")

    classifications = _METRICS_STORE.get("selection_status", [])
    health.videos_classified = sum(
        e["value"] for e in classifications if e["label"] == "videos_classified"
    )

    # Determine overall status
    recent_failures = [f for f in failures
                       if f.get("timestamp", "") >= since_24h.isoformat()]
    if len(recent_failures) > 5:
        health.pipeline_status = "degraded"
        health.summary = f"{len(recent_failures)} failures in last 24h — investigate"
    elif len(recent_failures) > 0:
        health.pipeline_status = "stable_with_errors"
        health.summary = f"{len(recent_failures)} errors in last 24h, system operational"
    else:
        health.pipeline_status = "healthy"
        health.summary = "All systems operational"

    return health


def generate_daily_health_report() -> dict:
    """Daily markdown-formatted health report."""
    health = get_system_health()
    runtime = get_runtime_stats()

    return {
        "report_type": "daily",
        "generated_at": datetime.utcnow().isoformat(),
        "system_status": health.pipeline_status,
        "summary": health.summary,
        "uploads": {
            "total": health.total_uploads,
            "last": health.last_upload or "none",
        },
        "failures": {
            "total_24h": sum(
                1 for e in _METRICS_STORE.get("generation_failure", [])
                + _METRICS_STORE.get("analytics_failure", [])
                + _METRICS_STORE.get("youtube_api_failure", [])
                if e.get("timestamp", "") >= (datetime.utcnow() - timedelta(hours=24)).isoformat()
            ),
            "last": health.last_failure or "none",
            "retries_24h": health.retry_count_24h,
        },
        "pipeline_runtime_s": runtime,
        "evolution": {
            "active_ab_tests": health.active_ab_tests,
            "videos_classified": health.videos_classified,
        },
    }


def generate_weekly_system_report() -> dict:
    """Weekly comprehensive system report."""
    _load_metrics()
    since_7d = datetime.utcnow() - timedelta(days=7)

    all_events = []
    for cat_list in _METRICS_STORE.values():
        all_events.extend(cat_list)

    recent = [e for e in all_events if e.get("timestamp", "") >= since_7d.isoformat()]

    # Group by category
    by_category: dict[str, list[dict]] = defaultdict(list)
    for e in recent:
        by_category[e["category"]].append(e)

    uploads_7d = [e for e in by_category.get("upload", []) if e["label"] == "upload_success"]
    failures_7d = (
        by_category.get("generation_failure", [])
        + by_category.get("analytics_failure", [])
        + by_category.get("youtube_api_failure", [])
    )

    return {
        "report_type": "weekly",
        "generated_at": datetime.utcnow().isoformat(),
        "period": "7d",
        "uploads": {
            "count": len(uploads_7d),
            "total_views": sum(
                e.get("metadata", {}).get("views", 0) for e in uploads_7d
            ),
        },
        "failures": {
            "total": len(failures_7d),
            "by_type": dict(
                (k, len([e for e in failures_7d if e.get("category") == k]))
                for k in ["generation_failure", "analytics_failure", "youtube_api_failure"]
            ),
        },
        "evolution": {
            "ab_decisions": len(by_category.get("ab_status", [])),
            "selection_cycles": len(by_category.get("selection_status", [])),
        },
        "runtime": get_runtime_stats(),
    }


# ──────────────────────────────────────────────
# Alert Generation
# ──────────────────────────────────────────────

ALERT_THRESHOLDS = {
    "max_failures_per_hour": 3,
    "max_retries_per_hour": 5,
    "min_uploads_per_week": 1,
    "max_consecutive_failures": 3,
}


def check_alerts() -> list[dict]:
    """Check system metrics against alert thresholds."""
    _load_metrics()
    alerts = []
    now = datetime.utcnow()
    since_1h = now - timedelta(hours=1)

    # Check failure rate
    recent_failures = [
        e for cat in ["generation_failure", "analytics_failure", "youtube_api_failure"]
        for e in _METRICS_STORE.get(cat, [])
        if e.get("timestamp", "") >= since_1h.isoformat()
    ]
    if len(recent_failures) > ALERT_THRESHOLDS["max_failures_per_hour"]:
        alerts.append({
            "severity": "warning",
            "metric": "failure_rate",
            "message": f"{len(recent_failures)} failures in last hour "
                       f"(threshold: {ALERT_THRESHOLDS['max_failures_per_hour']})",
            "triggered_at": now.isoformat(),
        })

    # Check consecutive failures
    for cat in ["generation_failure", "analytics_failure"]:
        entries = _METRICS_STORE.get(cat, [])
        consec = 0
        for e in reversed(entries):
            if e.get("timestamp", "") >= since_1h.isoformat():
                consec += 1
            else:
                break
        if consec >= ALERT_THRESHOLDS["max_consecutive_failures"]:
            alerts.append({
                "severity": "critical",
                "metric": f"consecutive_{cat}",
                "message": f"{consec} consecutive {cat} failures",
                "triggered_at": now.isoformat(),
            })

    return alerts
