"""C2-P6 isolated Experiment Observation and Outcome boundary.

This module observes only executions owned by the P5 in-memory boundary and
classifies results using the immutable rules carried by the P4 proposal. It
never writes persistence, legacy ExperimentResult, Knowledge, Strategy, or
production systems.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import Any, Mapping, Optional

from mindmargin.intelligence.c2_execution import C2ExperimentExecution, C2ExperimentExecutionBoundary

_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential|bearer)")
_RESULT_STATUSES = {"success", "failure", "inconclusive", "insufficient_sample"}
_ALLOWED_OPERATORS = {"gt", "gte", "lt", "lte", "eq", "neq", "between"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp_required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class C2ExperimentObservation:
    observation_id: str
    execution_id: str
    proposal_id: str
    proposal_version: str
    hypothesis_id: str
    metric_reference: dict[str, Any]
    variant: dict[str, Any]
    population: dict[str, Any]
    eligibility: dict[str, Any]
    observation_timestamp: str
    window_start: str
    window_end: str
    sample_count: int
    metric_value: Any
    provenance: dict[str, Any]
    lineage: dict[str, Any]
    status: str = "valid"

    def __post_init__(self) -> None:
        if not self.observation_id.startswith("obs_c2_"):
            raise ValueError("observation_id must use the C2-P6 prefix")
        if self.status != "valid":
            raise ValueError("only valid observations can be created")
        if not self.execution_id or not self.proposal_id or not self.hypothesis_id:
            raise ValueError("execution/proposal/hypothesis linkage is required")
        if not self.metric_reference.get("name"):
            raise ValueError("metric_reference.name is required")
        if not self.variant.get("variant_id"):
            raise ValueError("variant.variant_id is required")
        if not self.population or not self.eligibility:
            raise ValueError("population and eligibility are required")
        if self.sample_count < 0:
            raise ValueError("sample_count must be non-negative")
        _parse_time(self.observation_timestamp)
        if _parse_time(self.window_start) > _parse_time(self.window_end):
            raise ValueError("observation_window_invalid")
        if not self.provenance:
            raise ValueError("provenance is required")
        if not self.lineage or self.lineage.get("record_type") != "experiment_observation":
            raise ValueError("observation lineage is required")
        if self.lineage.get("record_id") != self.observation_id:
            raise ValueError("lineage record_id must match observation_id")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize({
            "record_type": "experiment_observation",
            "schema_version": "c2-p6-1",
            "observation_id": self.observation_id,
            "execution_id": self.execution_id,
            "proposal_id": self.proposal_id,
            "proposal_version": self.proposal_version,
            "hypothesis_id": self.hypothesis_id,
            "metric_reference": self.metric_reference,
            "variant": self.variant,
            "population": self.population,
            "eligibility": self.eligibility,
            "observation_timestamp": self.observation_timestamp,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "sample_count": self.sample_count,
            "metric_value": self.metric_value,
            "provenance": self.provenance,
            "lineage": self.lineage,
            "status": self.status,
        })


@dataclass(frozen=True)
class C2ExperimentOutcome:
    outcome_id: str
    execution_id: str
    proposal_id: str
    proposal_version: str
    metric_reference: dict[str, Any]
    observation_ids: tuple[str, ...]
    sample_counts: dict[str, int]
    evaluated_rule: dict[str, Any]
    result: str
    result_reason: str
    quality_metadata: dict[str, Any]
    provenance: dict[str, Any]
    lineage: dict[str, Any]
    idempotency_key: str
    created_at: str
    causality_status: str = "not_claimed"

    def __post_init__(self) -> None:
        if not self.outcome_id.startswith("out_c2_"):
            raise ValueError("outcome_id must use the C2-P6 prefix")
        if self.result not in _RESULT_STATUSES:
            raise ValueError("unsupported outcome result")
        if self.causality_status != "not_claimed":
            raise ValueError("P6 outcome must remain non-causal")
        if not self.observation_ids or not self.provenance or not self.lineage:
            raise ValueError("outcome observations/provenance/lineage are required")
        if not self.idempotency_key:
            raise ValueError("outcome idempotency_key is required")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize({
            "record_type": "experiment_outcome",
            "schema_version": "c2-p6-1",
            "outcome_id": self.outcome_id,
            "execution_id": self.execution_id,
            "proposal_id": self.proposal_id,
            "proposal_version": self.proposal_version,
            "metric_reference": self.metric_reference,
            "observation_ids": list(self.observation_ids),
            "sample_counts": self.sample_counts,
            "evaluated_rule": self.evaluated_rule,
            "result": self.result,
            "result_reason": self.result_reason,
            "quality_metadata": self.quality_metadata,
            "provenance": self.provenance,
            "lineage": self.lineage,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
            "causality_status": self.causality_status,
        })


@dataclass(frozen=True)
class ObservationValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class C2ExperimentObservationOutcomeBoundary:
    """In-memory P6 observation and rule-based outcome boundary."""

    def __init__(self, executions: C2ExperimentExecutionBoundary):
        if not isinstance(executions, C2ExperimentExecutionBoundary):
            raise TypeError("executions must be a C2ExperimentExecutionBoundary")
        self.executions = executions
        self._observations: dict[str, C2ExperimentObservation] = {}
        self._observation_keys: dict[str, C2ExperimentObservation] = {}
        self._outcomes: dict[str, C2ExperimentOutcome] = {}
        self._outcome_keys: dict[str, C2ExperimentOutcome] = {}

    def observe(
        self,
        execution: C2ExperimentExecution | str,
        *,
        variant: dict[str, Any],
        observation_timestamp: str,
        window_start: str,
        window_end: str,
        sample_count: int,
        metric_value: Any,
        provenance: dict[str, Any],
        population: Optional[dict[str, Any]] = None,
        eligibility: Optional[dict[str, Any]] = None,
    ) -> C2ExperimentObservation:
        execution_record = self._resolve_execution(execution)
        validation = self.validate_observation(
            execution_record,
            variant=variant,
            observation_timestamp=observation_timestamp,
            window_start=window_start,
            window_end=window_end,
            sample_count=sample_count,
            metric_value=metric_value,
            provenance=provenance,
            population=population,
            eligibility=eligibility,
        )
        if not validation.valid:
            raise ValueError("observation_rejected:" + ";".join(validation.errors))
        population_value = dict(population or execution_record.resolved_population)
        eligibility_value = dict(eligibility or execution_record.eligibility)
        key = self._observation_key(execution_record, variant, observation_timestamp, window_start, window_end, sample_count, metric_value)
        if key in self._observation_keys:
            raise ValueError("duplicate_observation_identity")
        observation_id = f"obs_c2_{uuid.uuid4().hex}"
        observation = C2ExperimentObservation(
            observation_id=observation_id,
            execution_id=execution_record.execution_id,
            proposal_id=execution_record.proposal_id,
            proposal_version=execution_record.proposal_version,
            hypothesis_id=execution_record.hypothesis_id,
            metric_reference=dict(execution_record.metric_reference),
            variant=dict(variant),
            population=population_value,
            eligibility=eligibility_value,
            observation_timestamp=observation_timestamp,
            window_start=window_start,
            window_end=window_end,
            sample_count=sample_count,
            metric_value=metric_value,
            provenance=dict(provenance),
            lineage={
                "record_type": "experiment_observation",
                "record_id": observation_id,
                "parent_record_ids": [execution_record.execution_id, execution_record.proposal_id],
                "source_record_ids": [execution_record.execution_id],
                "resolved_edges": [
                    {"from": execution_record.execution_id, "to": observation_id, "type": "observation"},
                    {"from": execution_record.proposal_id, "to": observation_id, "type": "proposal_observation"},
                ],
            },
        )
        self._observations[observation_id] = observation
        self._observation_keys[key] = observation
        return observation

    def validate_observation(
        self,
        execution: C2ExperimentExecution | str,
        *,
        variant: Mapping[str, Any],
        observation_timestamp: str,
        window_start: str,
        window_end: str,
        sample_count: int,
        metric_value: Any,
        provenance: Mapping[str, Any],
        population: Optional[Mapping[str, Any]],
        eligibility: Optional[Mapping[str, Any]],
    ) -> ObservationValidation:
        errors: list[str] = []
        if not isinstance(execution, C2ExperimentExecution):
            errors.append("execution_unknown")
            return ObservationValidation(False, tuple(errors))
        owned = self.executions.get(execution.execution_id)
        if owned is None:
            errors.append("execution_unknown")
        elif owned.status not in {"running", "completed"}:
            errors.append("execution_not_observable")
        proposal = self.executions.proposals.get(execution.proposal_id)
        if proposal is None or proposal.status != "validated":
            errors.append("validated_proposal_required")
        if str(variant.get("variant_id", "")) not in {str(item.get("variant_id")) for item in execution.selected_variants}:
            errors.append("variant_not_in_execution")
        if variant.get("role") not in {"control", "treatment"}:
            errors.append("variant_role_invalid")
        if proposal is not None and proposal.metric_name != execution.metric_reference.get("name"):
            errors.append("metric_proposal_mismatch")
        if not execution.metric_reference.get("name"):
            errors.append("metric_not_found")
        expected_population = execution.resolved_population
        expected_eligibility = execution.eligibility
        if population is not None and dict(population) != expected_population:
            errors.append("population_mismatch")
        if eligibility is not None and dict(eligibility) != expected_eligibility:
            errors.append("eligibility_mismatch")
        try:
            timestamp = _parse_time(observation_timestamp)
            start = _parse_time(window_start)
            end = _parse_time(window_end)
            if start > end or timestamp < start or timestamp > end:
                errors.append("observation_window_invalid_or_outside")
        except ValueError as exc:
            errors.append(str(exc))
        if sample_count < 0:
            errors.append("sample_count_invalid")
        if not provenance or not provenance.get("source") and not provenance.get("source_kind"):
            errors.append("provenance_missing")
        if _contains_causal_claim({"metric_value": metric_value, "provenance": provenance}):
            errors.append("causal_claim_rejected")
        return ObservationValidation(not errors, tuple(dict.fromkeys(errors)))

    def get_observation(self, observation_id: str) -> Optional[C2ExperimentObservation]:
        return self._observations.get(observation_id)

    def evaluate_outcome(self, execution: C2ExperimentExecution | str, observation_ids: list[str] | tuple[str, ...]) -> C2ExperimentOutcome:
        execution_record = self._resolve_execution(execution)
        observations = [self._observations.get(item) for item in observation_ids]
        if not observation_ids or any(item is None for item in observations):
            raise ValueError("outcome_observation_not_found")
        resolved = [item for item in observations if item is not None]
        if any(item.execution_id != execution_record.execution_id for item in resolved):
            raise ValueError("outcome_observation_execution_mismatch")
        if any(item.metric_reference.get("name") != execution_record.metric_reference.get("name") for item in resolved):
            raise ValueError("outcome_metric_mismatch")
        key = self._outcome_key(execution_record, resolved)
        if key in self._outcome_keys:
            raise ValueError("duplicate_outcome_idempotency_key")
        total_sample = sum(item.sample_count for item in resolved)
        if total_sample < self._minimum_sample(execution_record):
            result = "insufficient_sample"
            reason = "sample_count_below_proposal_minimum"
            rule = {"type": "minimum_sample", "minimum_sample": self._minimum_sample(execution_record)}
        else:
            success_rule = execution_record.metric_reference.get("success_rule") or {}
            inconclusive_rule = execution_record.metric_reference.get("inconclusive_rule") or {}
            success = all(_rule_matches(success_rule, item.metric_value) for item in resolved)
            inconclusive = all(_rule_matches(inconclusive_rule, item.metric_value) for item in resolved)
            if success:
                result, reason, rule = "success", "success_rule_matched", success_rule
            elif inconclusive:
                result, reason, rule = "inconclusive", "inconclusive_rule_matched", inconclusive_rule
            else:
                result, reason, rule = "failure", "success_rule_not_matched", success_rule
        outcome_id = f"out_c2_{uuid.uuid4().hex}"
        outcome = C2ExperimentOutcome(
            outcome_id=outcome_id,
            execution_id=execution_record.execution_id,
            proposal_id=execution_record.proposal_id,
            proposal_version=execution_record.proposal_version,
            metric_reference=dict(execution_record.metric_reference),
            observation_ids=tuple(observation_ids),
            sample_counts={item.observation_id: item.sample_count for item in resolved},
            evaluated_rule=dict(rule),
            result=result,
            result_reason=reason,
            quality_metadata={"total_sample": total_sample, "causality_status": "not_claimed"},
            provenance={"source": "c2.p6.outcome_boundary", "observation_ids": list(observation_ids)},
            lineage={
                "record_type": "experiment_outcome",
                "record_id": outcome_id,
                "parent_record_ids": [execution_record.execution_id, execution_record.proposal_id],
                "source_record_ids": list(observation_ids),
                "resolved_edges": [{"from": item.observation_id, "to": outcome_id, "type": "outcome"} for item in resolved],
            },
            idempotency_key=key,
            created_at=_now(),
        )
        self._outcomes[outcome_id] = outcome
        self._outcome_keys[key] = outcome
        return outcome

    def get_outcome(self, outcome_id: str) -> Optional[C2ExperimentOutcome]:
        return self._outcomes.get(outcome_id)

    def lineage_view(self, outcome_id: str) -> dict[str, Any]:
        outcome = self.get_outcome(outcome_id)
        if outcome is None:
            return {"status": "not_found", "outcome_id": outcome_id, "missing_ids": [outcome_id], "invalid_edges": [], "resolved_edges": []}
        missing = [item for item in outcome.observation_ids if item not in self._observations]
        return {
            "status": "complete" if not missing else "partial",
            "outcome_id": outcome_id,
            "missing_ids": missing,
            "invalid_edges": [],
            "resolved_edges": outcome.lineage.get("resolved_edges", []),
            "records_by_type": {"experiment_outcome": [outcome.to_dict()], "experiment_observation": [self._observations[item].to_dict() for item in outcome.observation_ids if item in self._observations]},
        }

    def _resolve_execution(self, execution: C2ExperimentExecution | str) -> C2ExperimentExecution:
        if isinstance(execution, C2ExperimentExecution):
            owned = self.executions.get(execution.execution_id)
            if owned is None:
                raise ValueError("execution_unknown")
            return owned
        owned = self.executions.get(execution)
        if owned is None:
            raise ValueError("execution_unknown")
        return owned

    def _minimum_sample(self, execution: C2ExperimentExecution) -> int:
        proposal = self.executions.proposals.get(execution.proposal_id)
        return int(proposal.minimum_sample) if proposal is not None else 0

    @staticmethod
    def _observation_key(execution: C2ExperimentExecution, variant: Mapping[str, Any], timestamp: str, start: str, end: str, sample: int, value: Any) -> str:
        raw = json.dumps({"execution": execution.execution_id, "variant": dict(variant), "timestamp": timestamp, "start": start, "end": end, "sample": sample, "value": value}, sort_keys=True, separators=(",", ":"))
        return "observation:" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    @staticmethod
    def _outcome_key(execution: C2ExperimentExecution, observations: list[C2ExperimentObservation]) -> str:
        raw = json.dumps({"execution": execution.execution_id, "version": execution.proposal_version, "metric": execution.metric_reference, "observations": [item.to_dict() for item in observations]}, sort_keys=True, separators=(",", ":"))
        return "outcome:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _rule_matches(rule: Mapping[str, Any], value: Any) -> bool:
    if not rule or rule.get("operator") not in _ALLOWED_OPERATORS:
        return False
    operator = rule["operator"]
    threshold = rule.get("threshold")
    try:
        if operator == "gt": return value > threshold
        if operator == "gte": return value >= threshold
        if operator == "lt": return value < threshold
        if operator == "lte": return value <= threshold
        if operator == "eq": return value == threshold
        if operator == "neq": return value != threshold
        if operator == "between": return threshold[0] <= value <= threshold[1]
    except (TypeError, IndexError, KeyError):
        return False
    return False


def _contains_causal_claim(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_causal_claim(k) or _contains_causal_claim(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_causal_claim(item) for item in value)
    return isinstance(value, str) and bool(re.search(r"(?i)\b(causal|causality|caused|cause|سبب|يثبت أن)\b", value))


def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        allowed = {"record_type", "schema_version", "observation_id", "outcome_id", "execution_id", "proposal_id", "proposal_version", "hypothesis_id", "metric_reference", "variant", "variant_id", "role", "population", "eligibility", "observation_timestamp", "window_start", "window_end", "sample_count", "metric_value", "provenance", "lineage", "status", "observation_ids", "sample_counts", "evaluated_rule", "result", "result_reason", "quality_metadata", "idempotency_key", "created_at", "causality_status", "parent_record_ids", "source_record_ids", "resolved_edges", "name", "success_rule", "inconclusive_rule", "operator", "threshold", "window", "source", "source_kind", "mode", "total_sample", "minimum_sample"}
        return {str(k): _sanitize(v, str(k)) for k, v in value.items() if str(k) in allowed}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str) and _SECRET.search(value):
        return "[REDACTED]"
    return value


__all__ = ["C2ExperimentObservation", "C2ExperimentOutcome", "C2ExperimentObservationOutcomeBoundary", "ObservationValidation"]
