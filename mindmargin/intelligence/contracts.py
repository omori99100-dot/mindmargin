"""Operational intelligence contracts and their append-only source of truth.

Phase B keeps the existing SQLite memory as a compatibility view. The JSONL
ledger owned by :class:`DecisionStore` is the authoritative record for
DecisionRecord, ExperimentResult, and PipelineEvent entries.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_LOCK = threading.RLock()
_SECRET_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization|client[_-]?secret|private[_-]?key|oauth|credential|auth[_-]?url)", re.I)
_SECRET_VALUE = re.compile(r"(?is)(bearer\s+)[A-Za-z0-9._~+/=-]+|(?:access[_-]?token|refresh[_-]?token|api[_-]?key|password|credential|client[_-]?secret)\s*[:=]\s*[^\s,;]+|https?://[^\s]*?(?:oauth|authorize|token|client_secret)[^\s]*|-----BEGIN [A-Z ]+PRIVATE KEY-----|(?:cookie|set-cookie|authorization)\s*[:=]\s*[^\n]+|(?:eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|(?:ya29\.|1//|gh[pousr]_)[A-Za-z0-9._-]{8,})")
_SAFE_NESTED_FIELDS = {
    "options": {"option", "score", "confidence", "source", "rank", "style", "path", "value", "index", "variant_index", "ctr", "watch_time_s", "impressions", "metric", "minimum"},
    "evidence": {"source", "score", "confidence", "stage", "attempt", "max_retries", "error", "status_code", "metric", "value", "minimum", "impressions", "reason"},
    "metadata": {"stage", "status", "attempt", "max_retries", "error_type", "next_run_at", "failed_runs", "selected_option", "variant_type", "status_code", "outcome_type", "metrics", "video_id"},
    "context": {"selection_source", "entry_point", "privacy", "topic", "status", "gate", "variant_type", "auto_publish", "stage", "attempt", "max_retries", "error_type", "schedule_id", "name", "failed_runs", "outcome_type", "parent_decision_id"},
    "result": {"status", "reason", "impressions", "ctr", "watch_time_s", "error", "metric", "value", "minimum", "video_id", "url"},
    "actual_outcome": {"status", "video_id", "url", "error", "outcome_type", "metrics", "experiment_id"},
    "metrics": {"impressions", "views", "ctr", "watch_time_s", "metric", "value", "minimum"},
    "variants": {"index", "variant_index", "value", "option", "score", "confidence", "source", "rank", "style", "path", "ctr", "watch_time_s", "impressions"},
    "provenance": {"source_kind", "source_locator", "collected_at", "collector_version", "validation_version", "freshness_seconds", "unit", "aggregation"},
    "observed_value": {"value", "metric", "count", "rate", "ctr", "views", "impressions", "watch_time_s", "status"},
    "value": {"value", "metric", "count", "rate", "ctr", "views", "impressions", "watch_time_s", "status", "unit", "aggregation"},
    "reference_value": {"value", "metric", "count", "rate", "ctr", "views", "impressions", "status", "unit", "aggregation"},
    "limitations": {"reason", "source", "window", "freshness", "quality"},
    "validation_errors": {"code", "field", "message"},
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, tuple):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(r"\1[REDACTED]", value)
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _redact(payload)


def _allowlist_nested(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        allowed = _SAFE_NESTED_FIELDS.get(field)
        result = {}
        for key, item in value.items():
            key = str(key)
            if allowed is not None and key not in allowed:
                if _SECRET_KEY.search(key):
                    result[key] = "[REDACTED]"
                continue
            result[key] = _allowlist_nested(item, key)
        return result
    if isinstance(value, list):
        return [_allowlist_nested(item, field) for item in value]
    return _redact(value, field)


def sanitize_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only operational fields and safe nested evidence, never raw payloads."""
    record_type = payload.get("record_type", "")
    allowed_top = {
        "decision": {"record_type", "decision_id", "decision_type", "context", "options", "selected_option", "rationale", "confidence", "expected_outcome", "actual_outcome", "evidence", "pipeline_id", "content_id", "story_id", "video_id", "publish_id", "experiment_id", "correlation_id", "source", "status", "failure_reason", "idempotency_key", "created_at", "recorded_at"},
        "event": {"record_type", "event_id", "event_type", "pipeline_id", "stage", "from_state", "to_state", "reason", "metadata", "decision_id", "experiment_id", "content_id", "video_id", "publish_id", "correlation_id", "parent_record_id", "source", "occurred_at", "recorded_at"},
        "experiment": {"record_type", "experiment_id", "hypothesis", "variable", "variants", "success_metric", "minimum_sample", "sample_size", "confidence", "winner", "status", "result", "pipeline_id", "decision_id", "content_id", "video_id", "correlation_id", "created_at", "recorded_at"},
        "diagnosis": {"record_type", "diagnosis_id", "problem", "evidence", "likely_cause", "confidence", "recommended_experiment", "expected_effect", "hypothesis", "action", "result", "pipeline_id", "created_at", "recorded_at"},
        "observation": {"record_type", "schema_version", "record_id", "pipeline_id", "content_id", "story_id", "video_id", "correlation_id", "parent_record_ids", "source_record_ids", "source", "created_at", "recorded_at", "status", "idempotency_key", "observation_type", "subject_type", "subject_id", "metric_name", "observed_value", "baseline_value", "unit", "direction", "observed_at", "window_start", "window_end", "aggregation", "source_kind", "freshness_seconds", "anomaly_rule_id", "quality", "notes"},
        "evidence": {"record_type", "schema_version", "record_id", "pipeline_id", "content_id", "story_id", "video_id", "correlation_id", "parent_record_ids", "source_record_ids", "source", "created_at", "recorded_at", "status", "idempotency_key", "evidence_type", "claim_scope", "observation_ids", "source_artifact_ids", "metric_name", "unit", "aggregation", "value", "comparator", "reference_value", "window_start", "window_end", "provenance", "validation_status", "validation_errors", "reproducibility", "limitations"},
    }.get(record_type)
    if not allowed_top:
        return {"record_type": record_type, "recorded_at": payload.get("recorded_at", utcnow_iso())}
    return {key: _allowlist_nested(value, key) for key, value in payload.items() if key in allowed_top}


def _context_fingerprint(context: dict[str, Any]) -> str:
    safe = json.dumps(redact_payload(context), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(safe.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    decision_type: str
    context: dict[str, Any] = field(default_factory=dict)
    options: list[dict[str, Any]] = field(default_factory=list)
    selected_option: Optional[str] = None
    rationale: str = ""
    confidence: float = 0.0
    expected_outcome: Optional[dict[str, Any]] = None
    actual_outcome: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    pipeline_id: str = ""
    content_id: str = ""
    story_id: str = ""
    video_id: str = ""
    publish_id: str = ""
    experiment_id: str = ""
    correlation_id: str = ""
    source: str = ""
    status: str = "completed"
    failure_reason: str = ""
    idempotency_key: str = ""
    created_at: str = field(default_factory=utcnow_iso)

    @classmethod
    def create(cls, decision_type: str, **kwargs: Any) -> "DecisionRecord":
        context = kwargs.get("context") or {}
        pipeline_id = kwargs.get("pipeline_id", "")
        key = kwargs.pop("idempotency_key", "") or f"{pipeline_id}:{decision_type}:{_context_fingerprint(context)}"
        return cls(
            decision_id=f"dec_{uuid.uuid4().hex}",
            decision_type=decision_type,
            idempotency_key=key,
            correlation_id=kwargs.pop("correlation_id", "") or pipeline_id,
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return redact_payload({"record_type": "decision", **asdict(self)})


@dataclass(frozen=True)
class DiagnosisRecord:
    diagnosis_id: str
    problem: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    likely_cause: str = ""
    confidence: float = 0.0
    recommended_experiment: str = ""
    expected_effect: str = ""
    hypothesis: str = ""
    action: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    pipeline_id: str = ""
    created_at: str = field(default_factory=utcnow_iso)

    @classmethod
    def create(cls, problem: str, **kwargs: Any) -> "DiagnosisRecord":
        return cls(diagnosis_id=f"diag_{uuid.uuid4().hex}", problem=problem, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return redact_payload({"record_type": "diagnosis", **asdict(self)})


@dataclass(frozen=True)
class LineageEnvelope:
    record_type: str
    schema_version: str
    record_id: str
    pipeline_id: str = ""
    content_id: str = ""
    story_id: str = ""
    video_id: str = ""
    correlation_id: str = ""
    parent_record_ids: list[str] = field(default_factory=list)
    source_record_ids: list[str] = field(default_factory=list)
    source: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    status: str = "recorded"
    idempotency_key: str = ""


@dataclass(frozen=True)
class ObservationRecord:
    schema_version: str
    record_id: str
    pipeline_id: str = ""
    content_id: str = ""
    story_id: str = ""
    video_id: str = ""
    correlation_id: str = ""
    parent_record_ids: list[str] = field(default_factory=list)
    source_record_ids: list[str] = field(default_factory=list)
    source: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    status: str = "recorded"
    idempotency_key: str = ""
    observation_type: str = "metric_snapshot"
    subject_type: str = "system"
    subject_id: str = ""
    metric_name: str = ""
    observed_value: Any = None
    baseline_value: Any = None
    unit: str = ""
    direction: str = "unavailable"
    observed_at: str = field(default_factory=utcnow_iso)
    window_start: str = ""
    window_end: str = ""
    aggregation: str = "point"
    source_kind: str = ""
    freshness_seconds: Optional[int] = None
    anomaly_rule_id: str = ""
    quality: str = "valid"
    notes: str = ""

    @classmethod
    def create(cls, *, metric_name: str, subject_id: str, window_start: str, window_end: str, observed_value: Any, **kwargs: Any) -> "ObservationRecord":
        fingerprint = hashlib.sha256(json.dumps(observed_value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
        rule_id = kwargs.get("anomaly_rule_id", "") or "none"
        key = kwargs.pop("idempotency_key", "") or f"observation:{rule_id}:{subject_id}:{window_start}:{window_end}:{metric_name}:{fingerprint}"
        pipeline_id = kwargs.get("pipeline_id", "")
        return cls(schema_version=kwargs.pop("schema_version", "c1-1"), record_id=f"obs_{uuid.uuid4().hex}", metric_name=metric_name, subject_id=subject_id, window_start=window_start, window_end=window_end, observed_value=observed_value, idempotency_key=key, correlation_id=kwargs.pop("correlation_id", "") or pipeline_id, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {"record_type": "observation", **asdict(self)}


@dataclass(frozen=True)
class EvidenceRecord:
    schema_version: str
    record_id: str
    pipeline_id: str = ""
    content_id: str = ""
    story_id: str = ""
    video_id: str = ""
    correlation_id: str = ""
    parent_record_ids: list[str] = field(default_factory=list)
    source_record_ids: list[str] = field(default_factory=list)
    source: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    status: str = "collected"
    idempotency_key: str = ""
    evidence_type: str = "direct_observation"
    claim_scope: str = ""
    observation_ids: list[str] = field(default_factory=list)
    source_artifact_ids: list[str] = field(default_factory=list)
    metric_name: str = ""
    unit: str = ""
    aggregation: str = ""
    value: Any = None
    comparator: str = ""
    reference_value: Any = None
    window_start: str = ""
    window_end: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    validation_status: str = "partial"
    validation_errors: list[dict[str, Any]] = field(default_factory=list)
    reproducibility: str = "bounded"
    limitations: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, *, observation_ids: list[str], source_artifact_ids: list[str], metric_name: str, value: Any, validation_version: str = "c1-1", **kwargs: Any) -> "EvidenceRecord":
        artifact_fingerprint = hashlib.sha256(json.dumps(source_artifact_ids, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        key = kwargs.pop("idempotency_key", "") or f"evidence:{','.join(observation_ids)}:{artifact_fingerprint}:{validation_version}"
        pipeline_id = kwargs.get("pipeline_id", "")
        return cls(schema_version=kwargs.pop("schema_version", "c1-1"), record_id=f"ev_{uuid.uuid4().hex}", observation_ids=observation_ids, source_artifact_ids=source_artifact_ids, metric_name=metric_name, value=value, idempotency_key=key, correlation_id=kwargs.pop("correlation_id", "") or pipeline_id, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {"record_type": "evidence", **asdict(self)}


@dataclass(frozen=True)
class PipelineEvent:
    event_id: str
    event_type: str
    pipeline_id: str
    stage: str = ""
    from_state: str = ""
    to_state: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    decision_id: str = ""
    experiment_id: str = ""
    content_id: str = ""
    video_id: str = ""
    publish_id: str = ""
    correlation_id: str = ""
    parent_record_id: str = ""
    source: str = ""
    occurred_at: str = field(default_factory=utcnow_iso)

    @classmethod
    def create(cls, event_type: str, pipeline_id: str, **kwargs: Any) -> "PipelineEvent":
        return cls(
            event_id=f"evt_{uuid.uuid4().hex}",
            event_type=event_type,
            pipeline_id=pipeline_id,
            correlation_id=kwargs.pop("correlation_id", "") or pipeline_id,
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return redact_payload({"record_type": "event", **asdict(self)})


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    hypothesis: str
    variable: str
    variants: list[dict[str, Any]] = field(default_factory=list)
    success_metric: str = ""
    minimum_sample: int = 0
    sample_size: int = 0
    confidence: float = 0.0
    winner: Optional[str] = None
    status: str = "planned"
    result: dict[str, Any] = field(default_factory=dict)
    pipeline_id: str = ""
    decision_id: str = ""
    content_id: str = ""
    video_id: str = ""
    correlation_id: str = ""
    created_at: str = field(default_factory=utcnow_iso)

    def __post_init__(self):
        if self.status == "completed" and self.winner is not None and self.sample_size < self.minimum_sample:
            raise ValueError("completed experiment winner requires minimum_sample")
        if self.status == "inconclusive" and self.winner is not None:
            raise ValueError("inconclusive experiment cannot have a winner")

    @property
    def is_sample_sufficient(self) -> bool:
        return self.sample_size >= self.minimum_sample

    @classmethod
    def create(cls, hypothesis: str, variable: str, **kwargs: Any) -> "ExperimentResult":
        pipeline_id = kwargs.get("pipeline_id", "")
        return cls(
            experiment_id=f"exp_{uuid.uuid4().hex}",
            hypothesis=hypothesis,
            variable=variable,
            correlation_id=kwargs.pop("correlation_id", "") or pipeline_id,
            **kwargs,
        )

    def declare_inconclusive(self, result: Optional[dict[str, Any]] = None) -> "ExperimentResult":
        return ExperimentResult(**{**asdict(self), "status": "inconclusive", "winner": None, "result": result or self.result})

    def declare_winner(self, winner: str, confidence: float, result: Optional[dict[str, Any]] = None) -> "ExperimentResult":
        if not self.is_sample_sufficient:
            raise ValueError("Cannot declare an experiment winner before minimum sample is reached")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return ExperimentResult(**{**asdict(self), "winner": winner, "confidence": confidence, "status": "completed", "result": result or self.result})

    def to_dict(self) -> dict[str, Any]:
        return redact_payload({"record_type": "experiment", **asdict(self)})


class EventLedger:
    """Low-level append-only JSONL ledger with redaction."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any] | PipelineEvent | DecisionRecord | DiagnosisRecord | ExperimentResult) -> dict[str, Any]:
        payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        payload = redact_payload(payload)
        payload.setdefault("recorded_at", utcnow_iso())
        payload = sanitize_record(payload)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with _LOCK:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return payload

    def read(self, record_type: Optional[str] = None, pipeline_id: Optional[str] = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with _LOCK:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record_type is not None and record.get("record_type") != record_type and record.get("event_type") != record_type:
                    continue
                if pipeline_id is not None and record.get("pipeline_id") != pipeline_id:
                    continue
                records.append(record)
        return records

    def compact(self, keep: Iterable[dict[str, Any]]) -> None:
        rows = list(keep)
        with _LOCK:
            fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(redact_payload(row), ensure_ascii=False, sort_keys=True, default=str) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)


class DecisionStore:
    """Phase B adapter; the ledger is the source of truth for decision records."""

    def __init__(self, path: str | Path):
        self.ledger = EventLedger(path)

    def save_decision(self, record: DecisionRecord) -> dict[str, Any]:
        existing = self.find_by_idempotency(record.idempotency_key)
        if existing:
            return existing
        return self.ledger.append(record)

    def save_experiment(self, result: ExperimentResult) -> dict[str, Any]:
        existing = [r for r in self.ledger.read("experiment", result.pipeline_id) if r.get("experiment_id") == result.experiment_id]
        if existing:
            latest = existing[-1]
            if latest.get("status") == result.status and latest.get("winner") == result.winner and latest.get("sample_size") == result.sample_size:
                return latest
        return self.ledger.append(result)

    def save_event(self, event: PipelineEvent) -> dict[str, Any]:
        return self.ledger.append(event)

    def save_observation(self, record: ObservationRecord) -> dict[str, Any]:
        existing = [row for row in self.ledger.read("observation") if row.get("idempotency_key") == record.idempotency_key]
        if existing:
            latest = existing[-1]
            if latest.get("status") == record.status and latest.get("quality") == record.quality:
                return latest
        return self.ledger.append(record)

    def get_observation(self, record_id: str) -> Optional[dict[str, Any]]:
        return next((row for row in self.ledger.read("observation") if row.get("record_id") == record_id), None)

    def observations_for_pipeline(self, pipeline_id: str) -> list[dict[str, Any]]:
        return self.ledger.read("observation", pipeline_id)

    def save_evidence(self, record: EvidenceRecord) -> dict[str, Any]:
        existing = [row for row in self.ledger.read("evidence") if row.get("idempotency_key") == record.idempotency_key]
        if existing:
            latest = existing[-1]
            if latest.get("status") == record.status and latest.get("validation_status") == record.validation_status:
                return latest
        return self.ledger.append(record)

    def get_evidence(self, record_id: str) -> Optional[dict[str, Any]]:
        return next((row for row in self.ledger.read("evidence") if row.get("record_id") == record_id), None)

    def evidence_for_pipeline(self, pipeline_id: str) -> list[dict[str, Any]]:
        return self.ledger.read("evidence", pipeline_id)

    def find_by_idempotency(self, key: str) -> Optional[dict[str, Any]]:
        if not key:
            return None
        for record in self.ledger.read():
            if record.get("idempotency_key") == key:
                return record
        return None

    def decisions_for_pipeline(self, pipeline_id: str) -> list[dict[str, Any]]:
        return self.ledger.read("decision", pipeline_id)

    def lineage_for_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        rows = self.ledger.read(pipeline_id=pipeline_id)
        decisions = [r for r in rows if r.get("record_type") == "decision"]
        events = [r for r in rows if r.get("record_type") == "event"]
        experiments = [r for r in rows if r.get("record_type") == "experiment"]
        outcomes = [r for r in rows if r.get("actual_outcome") or r.get("result")]
        observations = [r for r in rows if r.get("record_type") == "observation"]
        evidence = [r for r in rows if r.get("record_type") == "evidence"]
        resolved_edges: list[dict[str, Any]] = []
        missing_ids: list[str] = []
        invalid_edges: list[dict[str, Any]] = []
        global_rows = self.ledger.read()
        global_by_id = {key: row for row in global_rows for key in (row.get("decision_id"), row.get("event_id"), row.get("experiment_id"), row.get("record_id")) if key}
        for child in observations + evidence:
            child_id = child.get("record_id")
            child_pipeline = child.get("pipeline_id", "")
            child_correlation = child.get("correlation_id", "")
            if not child_correlation:
                invalid_edges.append({"from": child_id, "to": child_id, "type": "missing_correlation"})
            for edge_type, ids in (("parent", child.get("parent_record_ids", [])), ("source", child.get("source_record_ids", []))):
                for related_id in ids:
                    edge = {"from": related_id, "to": child_id, "type": edge_type}
                    related = global_by_id.get(related_id)
                    if related is None:
                        missing_ids.append(related_id)
                        invalid_edges.append(edge)
                        continue
                    if related.get("pipeline_id", "") and child_pipeline and related.get("pipeline_id") != child_pipeline:
                        edge["reason"] = "wrong_pipeline"
                        invalid_edges.append(edge)
                        continue
                    if related.get("correlation_id", "") and child_correlation and related.get("correlation_id") != child_correlation:
                        edge["reason"] = "wrong_correlation"
                        invalid_edges.append(edge)
                        continue
                    resolved_edges.append(edge)
        missing = []
        if not observations:
            missing.append("observation")
        if observations and not evidence:
            missing.append("evidence")
        if any(not item.get("correlation_id") for item in observations + evidence):
            missing.append("correlation")
        if any(item.get("source_record_ids") and any(edge.get("to") == item.get("record_id") and edge.get("type") == "source" for edge in invalid_edges) for item in observations + evidence):
            missing.append("source")
        status = "not_found" if not rows else ("complete" if observations and evidence and not invalid_edges and not missing else "partial")
        return {
            "pipeline_id": pipeline_id,
            "status": status,
            "decisions": decisions,
            "events": events,
            "experiments": experiments,
            "outcomes": outcomes,
            "observations": observations,
            "evidence": evidence,
            "records_by_type": {"decision": decisions, "event": events, "experiment": experiments, "outcome": outcomes, "observation": observations, "evidence": evidence},
            "resolved_edges": resolved_edges,
            "missing_ids": missing_ids,
            "invalid_edges": invalid_edges,
            "warnings": missing,
        }


__all__ = ["LineageEnvelope", "ObservationRecord", "EvidenceRecord", "DecisionRecord", "DiagnosisRecord", "PipelineEvent", "ExperimentResult", "EventLedger", "DecisionStore", "redact_payload"]
