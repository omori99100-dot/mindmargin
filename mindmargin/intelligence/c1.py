"""Opt-in Phase C1 observation and evidence components.

This module is deliberately additive: it reads Phase B records and never runs in
publish or A/B production paths unless explicitly called by a caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Optional

from mindmargin.intelligence.contracts import EvidenceRecord, ObservationRecord, DecisionStore, PipelineEvent
from mindmargin.intelligence.metric_registry import MetricDefinition, MetricRegistry


@dataclass(frozen=True)
class Freshness:
    state: str
    seconds: Optional[int]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assess_freshness(metric: MetricDefinition, observed_at: str, now: Optional[datetime] = None) -> Freshness:
    try:
        age = max(0, int(((now or datetime.now(timezone.utc)) - _parse_time(observed_at)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return Freshness("unknown", None)
    threshold = metric.freshness_policy_seconds
    if threshold is None:
        return Freshness("unknown", age)
    return Freshness("fresh" if age <= threshold else "stale", age)


def _emit(store: DecisionStore, event_type: str, pipeline_id: str, *, reason: str, parent_record_id: str, source: str, correlation_id: str) -> dict[str, Any]:
    return store.save_event(PipelineEvent.create(event_type, pipeline_id, stage="observation_evidence", reason=reason, parent_record_id=parent_record_id, source=source, correlation_id=correlation_id or pipeline_id))


def _direction(value: Any, baseline: Any) -> str:
    if not isinstance(value, (int, float)) or not isinstance(baseline, (int, float)):
        return "unavailable"
    if value > baseline:
        return "increased"
    if value < baseline:
        return "decreased"
    return "unchanged"


class ObservationCollector:
    """Deterministic, opt-in collector from already available Phase B/analytics data."""

    def __init__(self, store: DecisionStore, registry: Optional[MetricRegistry] = None):
        self.store = store
        self.registry = registry or MetricRegistry()

    def collect_from_event(self, event_id: str, *, metric_name: str = "lifecycle_status", observed_value: Any = None, window_start: str = "", window_end: str = "", observation_type: str = "lifecycle_signal", **kwargs: Any) -> dict[str, Any]:
        event = next((row for row in self.store.ledger.read("event") if row.get("event_id") == event_id), None)
        if event is None:
            raise ValueError(f"Unknown Phase B event: {event_id}")
        occurred_at = event.get("occurred_at") or event.get("recorded_at")
        value = observed_value if observed_value is not None else event.get("to_state") or event.get("event_type")
        return self.collect(
            metric_name=metric_name,
            observed_value=value,
            subject_id=event.get("video_id") or event.get("pipeline_id") or event_id,
            source_kind="phase_b_event",
            source=event.get("source") or "phase_b.event",
            window_start=window_start or occurred_at,
            window_end=window_end or occurred_at,
            observed_at=occurred_at,
            pipeline_id=event.get("pipeline_id", ""),
            video_id=event.get("video_id", ""),
            correlation_id=event.get("correlation_id", ""),
            parent_record_ids=[event.get("decision_id")] if event.get("decision_id") else [],
            source_record_ids=[event_id],
            observation_type=observation_type,
            **kwargs,
        )

    def collect_from_failure(self, event_id: str, **kwargs: Any) -> dict[str, Any]:
        event = next((row for row in self.store.ledger.read("event") if row.get("event_id") == event_id), None)
        if event is None:
            raise ValueError(f"Unknown Phase B event: {event_id}")
        event_type = str(event.get("event_type", "")).lower()
        if not any(token in event_type for token in ("fail", "error", "retry", "blocked")):
            raise ValueError(f"Event is not an operational failure: {event_id}")
        return self.collect_from_event(event_id, metric_name="lifecycle_status", observation_type="operational_failure", **kwargs)

    def collect_from_experiment(self, experiment_id: str, **kwargs: Any) -> dict[str, Any]:
        result = next((row for row in self.store.ledger.read("experiment") if row.get("experiment_id") == experiment_id), None)
        if result is None:
            raise ValueError(f"Unknown experiment: {experiment_id}")
        metric_name = result.get("success_metric") or "impressions"
        metrics = result.get("result") if isinstance(result.get("result"), dict) else {}
        value = metrics.get(metric_name, result.get("sample_size"))
        return self.collect(
            metric_name=metric_name,
            observed_value=value,
            subject_id=result.get("video_id") or result.get("pipeline_id") or experiment_id,
            source_kind="ab_result",
            source="phase_b.ab_result",
            window_start=result.get("created_at", ""),
            window_end=result.get("recorded_at", result.get("created_at", "")),
            observed_at=result.get("recorded_at", result.get("created_at", "")),
            pipeline_id=result.get("pipeline_id", ""),
            video_id=result.get("video_id", ""),
            correlation_id=result.get("correlation_id", ""),
            parent_record_ids=[result.get("decision_id")] if result.get("decision_id") else [],
            source_record_ids=[experiment_id],
            observation_type="experiment_signal",
            **kwargs,
        )

    def collect(
        self,
        *,
        metric_name: str,
        observed_value: Any,
        subject_id: str,
        source_kind: str,
        source: str,
        window_start: str,
        window_end: str,
        observed_at: str,
        pipeline_id: str = "",
        content_id: str = "",
        story_id: str = "",
        video_id: str = "",
        correlation_id: str = "",
        parent_record_ids: Optional[list[str]] = None,
        source_record_ids: Optional[list[str]] = None,
        baseline_value: Any = None,
        anomaly_rule_id: str = "",
        anomaly_rule: Optional[Callable[[Any, Any], bool]] = None,
        aggregation: Optional[str] = None,
        observation_type: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        definition = self.registry.get(metric_name)
        invalid_reason = ""
        if definition is None:
            invalid_reason = f"unknown_metric:{metric_name}"
        elif source_kind not in definition.supported_source:
            invalid_reason = f"unsupported_source:{source_kind}"
        elif observed_value is None:
            invalid_reason = "missing_measurement"
        if invalid_reason:
            record = ObservationRecord.create(
                pipeline_id=pipeline_id, content_id=content_id, story_id=story_id, video_id=video_id,
                correlation_id=correlation_id or pipeline_id, parent_record_ids=list(parent_record_ids or []),
                source_record_ids=list(source_record_ids or []), source=source, status="invalid",
                metric_name=metric_name, window_start=window_start, window_end=window_end,
                observed_value=observed_value, observation_type=observation_type or "operational_failure",
                subject_type="video" if video_id else "pipeline" if pipeline_id else "system", subject_id=subject_id,
                unit=definition.unit if definition else "", aggregation=aggregation or (definition.aggregation if definition else ""),
                observed_at=observed_at, source_kind=source_kind, quality="invalid", notes=invalid_reason,
            )
            saved = self.store.save_observation(record)
            _emit(self.store, "observation.invalid", pipeline_id, reason=invalid_reason, parent_record_id=saved.get("record_id", ""), source=source, correlation_id=correlation_id or pipeline_id)
            return saved
        freshness = assess_freshness(definition, observed_at)
        quality = {"fresh": "valid", "stale": "stale", "unknown": "partial"}[freshness.state]
        is_anomaly = bool(anomaly_rule and anomaly_rule(observed_value, baseline_value))
        record = ObservationRecord.create(
            pipeline_id=pipeline_id,
            content_id=content_id,
            story_id=story_id,
            video_id=video_id,
            correlation_id=correlation_id or pipeline_id,
            parent_record_ids=list(parent_record_ids or []),
            source_record_ids=list(source_record_ids or []),
            source=source,
            status="recorded",
            metric_name=metric_name,
            window_start=window_start,
            window_end=window_end,
            observed_value=observed_value,
            observation_type=observation_type or ("anomaly" if is_anomaly and anomaly_rule_id else "metric_snapshot"),
            subject_type="video" if video_id else "pipeline" if pipeline_id else "system",
            subject_id=subject_id,
            baseline_value=baseline_value,
            unit=definition.unit,
            direction=_direction(observed_value, baseline_value),
            observed_at=observed_at,
            aggregation=aggregation or definition.aggregation,
            source_kind=source_kind,
            freshness_seconds=freshness.seconds,
            anomaly_rule_id=anomaly_rule_id if is_anomaly else "",
            quality=quality,
            notes=notes,
        )
        saved = self.store.save_observation(record)
        event_type = "observation.stale" if quality == "stale" else "observation.invalid" if quality == "invalid" else "observation.recorded"
        _emit(self.store, event_type, pipeline_id, reason=quality, parent_record_id=saved.get("record_id", ""), source=source, correlation_id=correlation_id or pipeline_id)
        return saved


class EvidenceValidator:
    def __init__(self, store: DecisionStore, registry: Optional[MetricRegistry] = None):
        self.store = store
        self.registry = registry or MetricRegistry()

    def validate(self, record: EvidenceRecord, source_artifacts: Optional[dict[str, Any]] = None) -> tuple[str, list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        artifacts = source_artifacts or {}
        if not record.source_artifact_ids:
            errors.append({"code": "missing_source_artifact", "field": "source_artifact_ids", "message": "Evidence requires a concrete source artifact."})
        for artifact_id in record.source_artifact_ids:
            if artifact_id not in artifacts:
                errors.append({"code": "missing_source", "field": "source_artifact_ids", "message": artifact_id})
            else:
                try:
                    json.dumps(artifacts[artifact_id], default=None)
                    if isinstance(artifacts[artifact_id], object) and not isinstance(artifacts[artifact_id], (dict, list, str, int, float, bool, type(None))):
                        raise TypeError("artifact is not a supported serialized value")
                except (TypeError, ValueError):
                    errors.append({"code": "unparseable_source", "field": "source_artifact_ids", "message": artifact_id})
        if not record.observation_ids:
            errors.append({"code": "missing_observation", "field": "observation_ids", "message": "Evidence must reference an observation."})
        observations = [self.store.get_observation(item) for item in record.observation_ids]
        if any(item is None for item in observations):
            errors.append({"code": "unresolved_observation", "field": "observation_ids", "message": "One or more observations cannot be resolved."})
        resolved = [item for item in observations if item is not None]
        if any(item.get("quality") != "valid" or item.get("freshness_seconds") is None for item in resolved):
            errors.append({"code": "insufficient_freshness_or_quality", "field": "observation_ids", "message": "Evidence requires valid, fresh observations."})
        if record.pipeline_id and any(item.get("pipeline_id") and item.get("pipeline_id") != record.pipeline_id for item in resolved):
            errors.append({"code": "pipeline_scope_mismatch", "field": "pipeline_id", "message": "Evidence and observation pipeline IDs differ."})
        if record.correlation_id and any(item.get("correlation_id") and item.get("correlation_id") != record.correlation_id for item in resolved):
            errors.append({"code": "correlation_scope_mismatch", "field": "correlation_id", "message": "Evidence and observation correlation IDs differ."})
        rows = self.store.ledger.read()
        by_id = {key: row for row in rows for key in (row.get("record_id"), row.get("decision_id"), row.get("event_id"), row.get("experiment_id")) if key}
        known_ids = set(by_id)
        for field_name, ids in (("parent_record_ids", record.parent_record_ids), ("source_record_ids", record.source_record_ids)):
            for item_id in ids:
                related = by_id.get(item_id)
                if related is None:
                    errors.append({"code": "unresolved_parent" if field_name == "parent_record_ids" else "unresolved_source_record", "field": field_name, "message": item_id})
                    continue
                if record.pipeline_id and related.get("pipeline_id") and related.get("pipeline_id") != record.pipeline_id:
                    errors.append({"code": "pipeline_scope_mismatch", "field": field_name, "message": item_id})
                if record.correlation_id and related.get("correlation_id") and related.get("correlation_id") != record.correlation_id:
                    errors.append({"code": "correlation_scope_mismatch", "field": field_name, "message": item_id})
        definition = self.registry.get(record.metric_name)
        if definition is None:
            errors.append({"code": "unknown_metric", "field": "metric_name", "message": record.metric_name})
        else:
            if record.unit != definition.unit:
                errors.append({"code": "unit_mismatch", "field": "unit", "message": f"expected {definition.unit}"})
            if record.aggregation != definition.aggregation:
                errors.append({"code": "aggregation_mismatch", "field": "aggregation", "message": f"expected {definition.aggregation}"})
            if record.provenance.get("unit") != definition.unit or record.provenance.get("aggregation") != definition.aggregation:
                errors.append({"code": "provenance_metric_mismatch", "field": "provenance", "message": "Metric provenance does not match registry."})
        if not record.window_start or not record.window_end:
            errors.append({"code": "missing_window", "field": "window", "message": "Evidence requires a measurement window."})
        if not record.provenance:
            errors.append({"code": "missing_provenance", "field": "provenance", "message": "Evidence requires provenance."})
        if any(item and item.get("quality") in {"stale", "partial", "invalid"} for item in observations):
            if any(item and item.get("quality") == "invalid" for item in observations):
                return "invalid", errors + [{"code": "source_quality", "field": "observation_ids", "message": "Source observation is invalid."}]
            if any(item and item.get("quality") == "stale" for item in observations):
                return "stale", errors + [{"code": "source_quality", "field": "observation_ids", "message": "Source observation is stale."}]
            return "partial", errors + [{"code": "source_quality", "field": "observation_ids", "message": "Source observation is partial or insufficient."}]
        return ("valid" if not errors else "rejected"), errors


class EvidenceBuilder:
    def __init__(self, store: DecisionStore, registry: Optional[MetricRegistry] = None):
        self.store = store
        self.registry = registry or MetricRegistry()
        self.validator = EvidenceValidator(store, self.registry)

    def build(
        self,
        *,
        observation_ids: list[str],
        source_artifacts: dict[str, Any],
        metric_name: str,
        value: Any,
        source: str,
        claim_scope: str,
        pipeline_id: str = "",
        content_id: str = "",
        story_id: str = "",
        video_id: str = "",
        correlation_id: str = "",
        parent_record_ids: Optional[list[str]] = None,
        comparator: str = "",
        reference_value: Any = None,
        unit: str = "",
        aggregation: str = "",
        source_record_ids: Optional[list[str]] = None,
        window_start: str = "",
        window_end: str = "",
        source_kind: str = "",
        collector_version: str = "c1-1",
        validation_version: str = "c1-1",
        limitations: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        definition = self.registry.get(metric_name)
        resolved_unit = unit or (definition.unit if definition else "")
        resolved_aggregation = aggregation or (definition.aggregation if definition else "")
        record = EvidenceRecord.create(
            observation_ids=observation_ids,
            source_artifact_ids=list(source_artifacts.keys()),
            pipeline_id=pipeline_id,
            content_id=content_id,
            story_id=story_id,
            video_id=video_id,
            correlation_id=correlation_id or pipeline_id,
            parent_record_ids=list(parent_record_ids or observation_ids),
            source_record_ids=list(source_record_ids or []),
            source=source,
            status="collected",
            evidence_type="aggregated_metric" if comparator else "direct_observation",
            claim_scope=claim_scope,
            metric_name=metric_name,
            unit=resolved_unit,
            aggregation=resolved_aggregation,
            value=value,
            comparator=comparator,
            reference_value=reference_value,
            window_start=window_start,
            window_end=window_end,
            provenance={"source_kind": source_kind, "source_locator": source, "collected_at": datetime.now(timezone.utc).isoformat(), "collector_version": collector_version, "validation_version": validation_version, "unit": resolved_unit, "aggregation": resolved_aggregation},
            validation_status="partial",
            limitations=list(limitations or []),
        )
        validation_status, errors = self.validator.validate(record, source_artifacts)
        validated = EvidenceRecord(**{**record.__dict__, "validation_status": validation_status, "status": "validated" if validation_status == "valid" else "rejected", "validation_errors": errors})
        saved = self.store.save_evidence(validated)
        _emit(self.store, "evidence.collected", pipeline_id, reason="collected", parent_record_id=saved.get("record_id", ""), source=source, correlation_id=correlation_id or pipeline_id)
        event_type = "evidence.validated" if validation_status == "valid" else "evidence.rejected"
        _emit(self.store, event_type, pipeline_id, reason=validation_status, parent_record_id=saved.get("record_id", ""), source=source, correlation_id=correlation_id or pipeline_id)
        return saved


__all__ = ["Freshness", "assess_freshness", "ObservationCollector", "EvidenceBuilder", "EvidenceValidator"]
