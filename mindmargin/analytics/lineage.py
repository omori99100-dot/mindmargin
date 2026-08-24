"""Phase B lineage queries for a single published video or pipeline."""

from __future__ import annotations

from typing import Any

from mindmargin.analytics.memory import _get_db
from mindmargin.intelligence.instrumentation import lineage_report


def get_video_lineage_report(video_id: str = "", pipeline_id: str = "") -> dict[str, Any]:
    """Return a complete, JSON-safe lineage report for one video.

    The Phase B ledger is authoritative for decisions/events/experiments; the
    existing SQLite pipeline row supplies compatibility metadata and outcome
    snapshots when available.
    """
    conn = _get_db()
    pipeline = None
    if pipeline_id:
        pipeline = conn.execute("SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)).fetchone()
    elif video_id:
        pipeline = conn.execute("SELECT * FROM pipelines WHERE youtube_video_id = ? ORDER BY created_at DESC LIMIT 1", (video_id,)).fetchone()
        if pipeline:
            pipeline_id = pipeline["id"]
    if not pipeline_id:
        return {"status": "not_found", "video_id": video_id, "pipeline_id": "", "lineage": {}}

    report = lineage_report(pipeline_id)
    pipeline_data = dict(pipeline) if pipeline else {}
    if video_id and not pipeline_data.get("youtube_video_id"):
        pipeline_data["youtube_video_id"] = video_id

    decisions = report.get("decisions", [])
    events = report.get("events", [])
    experiments = report.get("experiments", [])
    has_topic = any(d.get("decision_type") == "topic_selection" for d in decisions)
    has_publish_decision = any(d.get("decision_type") in {"publish", "publish_eligibility"} for d in decisions)
    has_production_events = any(
        e.get("stage") in {"production", "pipeline"} or str(e.get("event_type", "")).startswith("pipeline.") or e.get("event_type") == "pipeline.state_changed"
        for e in events
    )
    has_publish_event = any(str(e.get("event_type", "")).startswith("publish.") for e in events)
    try:
        ab_row = conn.execute("SELECT COUNT(*) AS count FROM ab_tests WHERE pipeline_id = ?", (pipeline_id,)).fetchone()
        experiment_required = bool(ab_row and (ab_row["count"] if isinstance(ab_row, dict) else ab_row[0])) or bool(experiments)
    except Exception:
        experiment_required = bool(experiments)
    has_experiment = bool(experiments) if experiment_required else True
    has_outcome = bool(report.get("outcomes")) or any(e.get("event_type") == "outcome.recorded" for e in events)
    components = {
        "topic_decision": has_topic,
        "production_events": has_production_events,
        "publish_decision": has_publish_decision,
        "publish_event": has_publish_event,
        "experiment": has_experiment,
        "outcome": has_outcome,
    }
    missing = [name for name, present in components.items() if not present]
    if not decisions and not events and not experiments and not pipeline_data:
        status = "not_found"
    else:
        status = "complete" if not missing else "partial"
    report.update({
        "status": status,
        "video_id": video_id or pipeline_data.get("youtube_video_id", ""),
        "pipeline": pipeline_data,
        "components": components,
        "missing": missing,
        "last_decision": decisions[-1] if decisions else None,
        "last_event": events[-1] if events else None,
        "last_experiment": experiments[-1] if experiments else None,
    })
    return report


def format_video_lineage_report(report: dict[str, Any]) -> str:
    if report.get("status") not in {"complete", "partial"}:
        return f"Video lineage unavailable: {report.get('video_id', '')}"
    lines = [
        "Video Lineage Report",
        f"Pipeline: {report.get('pipeline_id', '')}",
        f"Video: {report.get('video_id', '')}",
        f"Decisions: {len(report.get('decisions', []))}",
        f"Events: {len(report.get('events', []))}",
        f"Experiments: {len(report.get('experiments', []))}",
    ]
    for decision in report.get("decisions", []):
        lines.append(f"Decision {decision.get('decision_type')}: {decision.get('selected_option')} ({decision.get('status')})")
    for experiment in report.get("experiments", []):
        lines.append(f"Experiment {experiment.get('experiment_id')}: {experiment.get('status')} winner={experiment.get('winner')}")
    return "\n".join(lines)


__all__ = ["get_video_lineage_report", "format_video_lineage_report"]
