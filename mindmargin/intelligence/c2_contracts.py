"""Versioned, companion contracts for C2-P0.

This module is intentionally isolated from the frozen C1 and legacy contracts.
It defines structural C2 contracts only; it does not persist records, resolve
lineage, coordinate diagnosis, register hypotheses, run experiments, or mutate
strategy.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping, Optional

C2_SCHEMA_VERSION = "c2-1"

DIAGNOSIS_TYPES = frozenset(
    {
        "operational_failure",
        "performance_anomaly",
        "data_quality",
        "experiment_issue",
        "eligibility_issue",
        "unknown_condition",
    }
)
DIAGNOSIS_STATUSES = frozenset({"planned", "validated", "rejected", "superseded", "invalid"})
DIAGNOSIS_TRANSITIONS = {
    "planned": frozenset({"validated", "rejected", "invalid"}),
    "validated": frozenset({"superseded", "invalid"}),
    "rejected": frozenset(),
    "superseded": frozenset(),
    "invalid": frozenset(),
}

HYPOTHESIS_TYPES = frozenset({"predictive", "operational", "comparative", "mechanism_candidate"})
HYPOTHESIS_STATUSES = frozenset(
    {"proposed", "testable", "tested", "supported", "rejected", "inconclusive", "superseded"}
)
HYPOTHESIS_TRANSITIONS = {
    "proposed": frozenset({"testable", "rejected"}),
    "testable": frozenset({"tested", "inconclusive", "rejected"}),
    "tested": frozenset({"supported", "rejected", "inconclusive"}),
    "supported": frozenset({"superseded"}),
    "rejected": frozenset({"superseded"}),
    "inconclusive": frozenset({"testable", "superseded"}),
    "superseded": frozenset(),
}

EXPECTED_DIRECTIONS = frozenset({"increase", "decrease", "no_change", "categorical", "unknown"})
CONFIDENCE_DIMENSIONS = frozenset({"data_quality", "evidence_support", "prediction", "result_quality"})
CONFIDENCE_BASES = frozenset({"rule_based", "sample_based", "provenance_based", "human_reviewed"})
CAUSALITY_STATUSES = frozenset({"not_claimed"})

_SECRET_KEY = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|client[_-]?secret|"
    r"private[_-]?key|oauth|credential|auth[_-]?url)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?is)(bearer\s+)[A-Za-z0-9._~+/=-]+|"
    r"(?:access[_-]?token|refresh[_-]?token|api[_-]?key|password|credential|"
    r"client[_-]?secret)\s*[:=]\s*[^\s,;]+|"
    r"https?://[^\s]*?(?:oauth|authorize|token|client_secret)[^\s]*|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----|"
    r"(?:cookie|set-cookie|authorization)\s*[:=]\s*[^\n]+|"
    r"(?:eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"(?:ya29\.|1//|gh[pousr]_)[A-Za-z0-9._-]{8,})"
)

_ALLOWED_NESTED = {
    "candidate_explanations": {"id", "label", "text", "basis", "evidence_ids"},
    "ruled_out_explanations": {"id", "label", "text", "basis", "evidence_ids"},
    "alternative_hypotheses": {"id", "label", "text", "basis", "evidence_ids"},
    "limitations": {"reason", "source", "window", "freshness", "quality", "scope"},
    "confidence": {"score", "dimension", "basis", "limitations"},
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _redact_value(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, key) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, key) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(r"\1[REDACTED]", value)
    return value


def _sanitize_nested(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        allowed = _ALLOWED_NESTED.get(field_name, set())
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key not in allowed:
                if _SECRET_KEY.search(key):
                    result[key] = "[REDACTED]"
                continue
            result[key] = _sanitize_nested(item, key)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize_nested(item, field_name) for item in value]
    return _redact_value(value, field_name)


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_ids(values: list[str], field_name: str) -> None:
    if not values or any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{field_name} must contain at least one non-empty ID")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicate IDs")


@dataclass(frozen=True)
class C2ConfidenceValue:
    """Bounded confidence about data/support/prediction quality, never causality."""

    score: float
    dimension: str
    basis: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.score, (int, float)) or not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("confidence.score must be between 0.0 and 1.0")
        if self.dimension not in CONFIDENCE_DIMENSIONS:
            raise ValueError(f"unsupported confidence dimension: {self.dimension}")
        if self.basis not in CONFIDENCE_BASES:
            raise ValueError(f"unsupported confidence basis: {self.basis}")
        if any(not isinstance(item, str) or not item.strip() for item in self.limitations):
            raise ValueError("confidence limitations must be non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize_nested(asdict(self), "confidence")


@dataclass(frozen=True)
class C2LineageEnvelope:
    """Shared immutable envelope for the two C2-P0 record contracts."""

    record_type: str
    record_id: str
    pipeline_id: str = ""
    content_id: str = ""
    story_id: str = ""
    video_id: str = ""
    correlation_id: str = ""
    parent_record_ids: tuple[str, ...] = ()
    source_record_ids: tuple[str, ...] = ()
    source: str = ""
    created_at: str = field(default_factory=_utcnow_iso)
    status: str = "planned"
    idempotency_key: str = ""
    schema_version: str = C2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.record_type not in {"diagnosis", "hypothesis"}:
            raise ValueError("C2 record_type must be diagnosis or hypothesis")
        _require_nonempty(self.record_id, "record_id")
        _require_nonempty(self.schema_version, "schema_version")
        if self.parent_record_ids and len(self.parent_record_ids) != len(set(self.parent_record_ids)):
            raise ValueError("parent_record_ids must not contain duplicates")
        if self.source_record_ids and len(self.source_record_ids) != len(set(self.source_record_ids)):
            raise ValueError("source_record_ids must not contain duplicates")
        _require_nonempty(self.idempotency_key, "idempotency_key")
        if not self.correlation_id and self.pipeline_id:
            raise ValueError("correlation_id is required when pipeline_id is present")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize_nested(asdict(self), "envelope")


@dataclass(frozen=True)
class C2DiagnosisRecord:
    """Versioned C2 diagnosis contract; does not replace legacy DiagnosisRecord."""

    diagnosis_id: str
    problem_statement: str
    evidence_ids: tuple[str, ...]
    envelope: C2LineageEnvelope
    diagnosis_type: str = "unknown_condition"
    observation_ids: tuple[str, ...] = ()
    candidate_explanations: tuple[dict[str, Any], ...] = ()
    ruled_out_explanations: tuple[dict[str, Any], ...] = ()
    causal_claim: None = None
    confidence: Optional[C2ConfidenceValue] = None
    severity: str = "informational"
    reproducibility: str = "unknown"
    recommended_next_step: str = "none"
    limitations: tuple[dict[str, Any], ...] = ()
    status: str = "planned"

    _SEVERITIES: ClassVar[frozenset[str]] = frozenset({"informational", "low", "medium", "high", "critical"})
    _REPRODUCIBILITY: ClassVar[frozenset[str]] = frozenset({"reproducible", "intermittent", "unknown"})
    _NEXT_STEPS: ClassVar[frozenset[str]] = frozenset({"observe_more", "collect_evidence", "none"})

    def __post_init__(self) -> None:
        _require_nonempty(self.diagnosis_id, "diagnosis_id")
        _require_nonempty(self.problem_statement, "problem_statement")
        _require_ids(list(self.evidence_ids), "evidence_ids")
        if self.envelope.record_type != "diagnosis":
            raise ValueError("diagnosis envelope record_type must be diagnosis")
        if self.envelope.record_id != self.diagnosis_id:
            raise ValueError("diagnosis_id must match envelope.record_id")
        if self.diagnosis_type not in DIAGNOSIS_TYPES:
            raise ValueError(f"unsupported diagnosis_type: {self.diagnosis_type}")
        if self.status not in DIAGNOSIS_STATUSES:
            raise ValueError(f"unsupported diagnosis status: {self.status}")
        if self.severity not in self._SEVERITIES:
            raise ValueError(f"unsupported diagnosis severity: {self.severity}")
        if self.reproducibility not in self._REPRODUCIBILITY:
            raise ValueError(f"unsupported reproducibility: {self.reproducibility}")
        if self.recommended_next_step not in self._NEXT_STEPS:
            raise ValueError(f"unsupported recommended next step: {self.recommended_next_step}")
        if self.causal_claim is not None:
            raise ValueError("C2 diagnosis causal_claim must remain null")

    @classmethod
    def create(
        cls,
        *,
        problem_statement: str,
        evidence_ids: list[str] | tuple[str, ...],
        pipeline_id: str = "",
        correlation_id: str = "",
        idempotency_key: str = "",
        **kwargs: Any,
    ) -> "C2DiagnosisRecord":
        diagnosis_id = f"diag_c2_{uuid.uuid4().hex}"
        evidence = tuple(evidence_ids)
        key = idempotency_key or f"diagnosis:{','.join(sorted(evidence))}:{kwargs.get('diagnosis_type', 'unknown_condition')}:{_fingerprint(problem_statement)}"
        envelope = C2LineageEnvelope(
            record_type="diagnosis",
            record_id=diagnosis_id,
            pipeline_id=pipeline_id,
            correlation_id=correlation_id or pipeline_id,
            parent_record_ids=tuple(kwargs.pop("parent_record_ids", ())),
            source_record_ids=tuple(kwargs.pop("source_record_ids", evidence)),
            source=kwargs.pop("source", "c2.p0.contract"),
            status=kwargs.get("status", "planned"),
            idempotency_key=key,
        )
        return cls(
            diagnosis_id=diagnosis_id,
            problem_statement=problem_statement,
            evidence_ids=evidence,
            envelope=envelope,
            **kwargs,
        )

    def transition_to(self, status: str) -> "C2DiagnosisRecord":
        if status not in DIAGNOSIS_STATUSES:
            raise ValueError(f"unsupported diagnosis status: {status}")
        if status not in DIAGNOSIS_TRANSITIONS[self.status]:
            raise ValueError(f"invalid diagnosis transition: {self.status} -> {status}")
        return self._replace_status(status)

    def _replace_status(self, status: str) -> "C2DiagnosisRecord":
        envelope = C2LineageEnvelope(**{**asdict(self.envelope), "status": status})
        return replace(self, envelope=envelope, status=status)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["envelope"] = asdict(self.envelope)
        payload["confidence"] = self.confidence.to_dict() if self.confidence else None
        return _sanitize_c2_payload({"record_type": "diagnosis", **payload})


@dataclass(frozen=True)
class C2HypothesisRecord:
    """Versioned C2 hypothesis contract; it is not a legacy experiment string."""

    hypothesis_id: str
    statement: str
    supporting_evidence_ids: tuple[str, ...]
    envelope: C2LineageEnvelope
    hypothesis_type: str = "predictive"
    diagnosis_ids: tuple[str, ...] = ()
    target_observation_ids: tuple[str, ...] = ()
    alternative_hypotheses: tuple[dict[str, Any], ...] = ()
    expected_direction: str = "unknown"
    measurable_prediction: str = ""
    falsification_condition: str = ""
    inconclusive_condition: str = ""
    confidence: Optional[C2ConfidenceValue] = None
    causality_status: str = "not_claimed"
    limitations: tuple[dict[str, Any], ...] = ()
    status: str = "proposed"

    def __post_init__(self) -> None:
        _require_nonempty(self.hypothesis_id, "hypothesis_id")
        _require_nonempty(self.statement, "statement")
        _require_ids(list(self.supporting_evidence_ids), "supporting_evidence_ids")
        _require_nonempty(self.measurable_prediction, "measurable_prediction")
        _require_nonempty(self.falsification_condition, "falsification_condition")
        _require_nonempty(self.inconclusive_condition, "inconclusive_condition")
        if self.envelope.record_type != "hypothesis":
            raise ValueError("hypothesis envelope record_type must be hypothesis")
        if self.envelope.record_id != self.hypothesis_id:
            raise ValueError("hypothesis_id must match envelope.record_id")
        if self.hypothesis_type not in HYPOTHESIS_TYPES:
            raise ValueError(f"unsupported hypothesis_type: {self.hypothesis_type}")
        if self.expected_direction not in EXPECTED_DIRECTIONS:
            raise ValueError(f"unsupported expected_direction: {self.expected_direction}")
        if self.causality_status not in CAUSALITY_STATUSES:
            raise ValueError("C2 hypothesis causality_status must be not_claimed")
        if self.status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"unsupported hypothesis status: {self.status}")

    @classmethod
    def create(
        cls,
        *,
        statement: str,
        supporting_evidence_ids: list[str] | tuple[str, ...],
        measurable_prediction: str,
        falsification_condition: str,
        inconclusive_condition: str,
        pipeline_id: str = "",
        correlation_id: str = "",
        idempotency_key: str = "",
        **kwargs: Any,
    ) -> "C2HypothesisRecord":
        hypothesis_id = f"hyp_c2_{uuid.uuid4().hex}"
        evidence = tuple(supporting_evidence_ids)
        key = idempotency_key or f"hypothesis:{','.join(sorted(evidence))}:{_fingerprint(statement)}:{_fingerprint(measurable_prediction)}"
        envelope = C2LineageEnvelope(
            record_type="hypothesis",
            record_id=hypothesis_id,
            pipeline_id=pipeline_id,
            correlation_id=correlation_id or pipeline_id,
            parent_record_ids=tuple(kwargs.pop("parent_record_ids", ())),
            source_record_ids=tuple(kwargs.pop("source_record_ids", evidence)),
            source=kwargs.pop("source", "c2.p0.contract"),
            status=kwargs.get("status", "proposed"),
            idempotency_key=key,
        )
        return cls(
            hypothesis_id=hypothesis_id,
            statement=statement,
            supporting_evidence_ids=evidence,
            measurable_prediction=measurable_prediction,
            falsification_condition=falsification_condition,
            inconclusive_condition=inconclusive_condition,
            envelope=envelope,
            **kwargs,
        )

    def transition_to(self, status: str) -> "C2HypothesisRecord":
        if status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"unsupported hypothesis status: {status}")
        if status not in HYPOTHESIS_TRANSITIONS[self.status]:
            raise ValueError(f"invalid hypothesis transition: {self.status} -> {status}")
        return self._replace_status(status)

    def _replace_status(self, status: str) -> "C2HypothesisRecord":
        envelope = C2LineageEnvelope(**{**asdict(self.envelope), "status": status})
        return replace(self, envelope=envelope, status=status)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["envelope"] = asdict(self.envelope)
        payload["confidence"] = self.confidence.to_dict() if self.confidence else None
        return _sanitize_c2_payload({"record_type": "hypothesis", **payload})


def _sanitize_c2_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a strict top-level and nested allow-list at the contract boundary."""
    allowed_top = {
        "record_type",
        "diagnosis_id",
        "hypothesis_id",
        "problem_statement",
        "statement",
        "evidence_ids",
        "supporting_evidence_ids",
        "envelope",
        "diagnosis_type",
        "observation_ids",
        "candidate_explanations",
        "ruled_out_explanations",
        "causal_claim",
        "confidence",
        "severity",
        "reproducibility",
        "recommended_next_step",
        "limitations",
        "status",
        "hypothesis_type",
        "diagnosis_ids",
        "target_observation_ids",
        "alternative_hypotheses",
        "expected_direction",
        "measurable_prediction",
        "falsification_condition",
        "inconclusive_condition",
        "causality_status",
    }
    result = {}
    for key, value in payload.items():
        if key not in allowed_top:
            if _SECRET_KEY.search(key):
                result[key] = "[REDACTED]"
            continue
        if key == "envelope":
            result[key] = _sanitize_envelope(value)
        elif key in {"candidate_explanations", "ruled_out_explanations", "alternative_hypotheses", "limitations", "confidence"}:
            result[key] = _sanitize_nested(value, key)
        else:
            result[key] = _redact_value(value, key)
    return result


def _sanitize_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "record_type",
        "record_id",
        "pipeline_id",
        "content_id",
        "story_id",
        "video_id",
        "correlation_id",
        "parent_record_ids",
        "source_record_ids",
        "source",
        "created_at",
        "status",
        "idempotency_key",
        "schema_version",
    }
    return {str(key): _redact_value(item, str(key)) for key, item in value.items() if str(key) in allowed}


__all__ = [
    "C2_SCHEMA_VERSION",
    "C2ConfidenceValue",
    "C2LineageEnvelope",
    "C2DiagnosisRecord",
    "C2HypothesisRecord",
    "DIAGNOSIS_TYPES",
    "DIAGNOSIS_STATUSES",
    "DIAGNOSIS_TRANSITIONS",
    "HYPOTHESIS_TYPES",
    "HYPOTHESIS_STATUSES",
    "HYPOTHESIS_TRANSITIONS",
    "EXPECTED_DIRECTIONS",
    "CONFIDENCE_DIMENSIONS",
    "CONFIDENCE_BASES",
]
