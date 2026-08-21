"""Operational Phase B instrumentation helpers.

The lineage JSONL ledger is the source of truth. SQLite and existing logs remain
compatibility/operational views and are not replaced in Phase B.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from mindmargin.config import settings
from mindmargin.intelligence.contracts import (
    DecisionRecord,
    DecisionStore,
    ExperimentResult,
    PipelineEvent,
)


_STORE: Optional[DecisionStore] = None


def lineage_path() -> Path:
    return Path(settings.storage.output_root).parent / "events" / "lineage.jsonl"


def get_decision_store() -> DecisionStore:
    global _STORE
    path = lineage_path()
    if _STORE is None:
        _STORE = DecisionStore(path)
    return _STORE


def record_decision(decision_type: str, *, pipeline_id: str = "", context: Optional[dict[str, Any]] = None,
                    options: Optional[list[dict[str, Any]]] = None, selected_option: Optional[str] = None,
                    rationale: str = "", confidence: float = 0.0,
                    expected_outcome: Optional[dict[str, Any]] = None,
                    actual_outcome: Optional[dict[str, Any]] = None,
                    evidence: Optional[list[dict[str, Any]]] = None,
                    content_id: str = "", story_id: str = "", video_id: str = "", publish_id: str = "",
                    experiment_id: str = "", source: str = "", status: str = "completed",
                    failure_reason: str = "", idempotency_key: str = "", correlation_id: str = "") -> dict[str, Any]:
    record = DecisionRecord.create(
        decision_type,
        pipeline_id=pipeline_id,
        context=context or {},
        options=options or [],
        selected_option=selected_option,
        rationale=rationale,
        confidence=confidence,
        expected_outcome=expected_outcome,
        actual_outcome=actual_outcome or {},
        evidence=evidence or [],
        content_id=content_id,
        story_id=story_id,
        video_id=video_id,
        publish_id=publish_id,
        experiment_id=experiment_id,
        source=source,
        status=status,
        failure_reason=failure_reason,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return get_decision_store().save_decision(record)


def record_event(event_type: str, pipeline_id: str, *, stage: str = "", reason: str = "",
                 decision_id: str = "", experiment_id: str = "", content_id: str = "",
                 video_id: str = "", publish_id: str = "", metadata: Optional[dict[str, Any]] = None,
                 correlation_id: str = "", parent_record_id: str = "", source: str = "") -> dict[str, Any]:
    return get_decision_store().save_event(PipelineEvent.create(
        event_type=event_type,
        pipeline_id=pipeline_id,
        stage=stage,
        reason=reason,
        decision_id=decision_id,
        experiment_id=experiment_id,
        content_id=content_id,
        video_id=video_id,
        publish_id=publish_id,
        metadata=metadata or {},
        correlation_id=correlation_id,
        parent_record_id=parent_record_id,
        source=source,
    ))


def record_experiment(result: ExperimentResult) -> dict[str, Any]:
    return get_decision_store().save_experiment(result)


def record_outcome(pipeline_id: str, *, decision_id: str = "", experiment_id: str = "", video_id: str = "", outcome_type: str = "performance", metrics: Optional[dict[str, Any]] = None, correlation_id: str = "") -> dict[str, Any]:
    """Append a later outcome without mutating the original decision record."""
    outcome = metrics or {}
    decision = record_decision(
        "performance_outcome",
        pipeline_id=pipeline_id,
        context={"outcome_type": outcome_type, "parent_decision_id": decision_id},
        selected_option="recorded",
        rationale="later performance outcome attached to the original decision lineage",
        confidence=1.0,
        actual_outcome={"outcome_type": outcome_type, "metrics": outcome, "experiment_id": experiment_id, "video_id": video_id},
        evidence=[{"metric": key, "value": value} for key, value in outcome.items()],
        video_id=video_id,
        experiment_id=experiment_id,
        source="intelligence.instrumentation.record_outcome",
        idempotency_key=f"{pipeline_id}:outcome:{outcome_type}:{experiment_id}:{video_id}:{hashlib.sha256(json.dumps(outcome, sort_keys=True, default=str).encode()).hexdigest()[:16]}",
        correlation_id=correlation_id or pipeline_id,
    )
    record_event("outcome.recorded", pipeline_id, stage="outcome", reason=outcome_type, decision_id=decision_id or decision.get("decision_id", ""), experiment_id=experiment_id, video_id=video_id, metadata={"outcome_type": outcome_type, "metrics": outcome}, correlation_id=correlation_id or pipeline_id)
    return decision


def lineage_report(pipeline_id: str) -> dict[str, Any]:
    return get_decision_store().lineage_for_pipeline(pipeline_id)


__all__ = ["get_decision_store", "record_decision", "record_event", "record_experiment", "record_outcome", "lineage_report", "lineage_path"]
