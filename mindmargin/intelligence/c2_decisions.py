"""C2-P7 Outcome -> Decision boundary.

The boundary is deliberately in-memory and side-effect-free. It consumes
completed P6 outcomes, validates their upstream lineage, and produces an
 auditable companion decision. It never executes decisions, writes ledgers,
updates Knowledge/Strategy, or touches production paths.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from mindmargin.intelligence.c2_observation_outcome import (
    C2ExperimentObservationOutcomeBoundary,
    C2ExperimentOutcome,
)

_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential|bearer)")
_CAUSAL = re.compile(r"(?i)\b(causal|causality|caused|cause|proven cause|guaranteed effect|causal certainty|سبب|يثبت أن)\b")
_ALLOWED_CLASSIFICATIONS = {"supported", "rejected", "inconclusive", "insufficient_evidence"}
_RESULT_TO_CLASSIFICATION = {
    "success": "supported",
    "failure": "rejected",
    "inconclusive": "inconclusive",
    "insufficient_sample": "insufficient_evidence",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class C2OutcomeDecision:
    decision_id: str
    decision_version: str
    outcome_id: str
    execution_id: str
    proposal_id: str
    proposal_version: str
    hypothesis_id: str
    metric_reference: dict[str, Any]
    evaluated_outcome: dict[str, Any]
    decision_classification: str
    rationale: dict[str, Any]
    evidence_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    lineage: dict[str, Any]
    provenance: dict[str, Any]
    safety_context: dict[str, Any]
    idempotency_key: str
    created_at: str
    audit_metadata: dict[str, Any]
    causality_status: str = "not_claimed"

    def __post_init__(self) -> None:
        if not self.decision_id.startswith("dec_c2_"):
            raise ValueError("decision_id must use the C2-P7 prefix")
        if not self.decision_version:
            raise ValueError("decision_version is required")
        if not self.outcome_id or not self.execution_id or not self.proposal_id or not self.hypothesis_id:
            raise ValueError("decision lineage identifiers are required")
        if self.decision_classification not in _ALLOWED_CLASSIFICATIONS:
            raise ValueError("unsupported decision classification")
        if self.causality_status != "not_claimed":
            raise ValueError("P7 decisions must remain non-causal")
        if not self.metric_reference.get("name"):
            raise ValueError("metric_reference.name is required")
        if not self.evidence_ids or not self.observation_ids:
            raise ValueError("evidence and observation references are required")
        if not self.rationale.get("summary") or not self.rationale.get("source_ids"):
            raise ValueError("auditable rationale is required")
        if _CAUSAL.search(json.dumps(self.rationale, ensure_ascii=False)):
            raise ValueError("causal rationale is not allowed")
        if not self.provenance or not self.lineage or not self.safety_context:
            raise ValueError("provenance, lineage, and safety context are required")
        if not self.idempotency_key:
            raise ValueError("idempotency_key is required")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize({
            "record_type": "outcome_decision",
            "schema_version": "c2-p7-1",
            "decision_id": self.decision_id,
            "decision_version": self.decision_version,
            "outcome_id": self.outcome_id,
            "execution_id": self.execution_id,
            "proposal_id": self.proposal_id,
            "proposal_version": self.proposal_version,
            "hypothesis_id": self.hypothesis_id,
            "metric_reference": self.metric_reference,
            "evaluated_outcome": self.evaluated_outcome,
            "decision_classification": self.decision_classification,
            "rationale": self.rationale,
            "evidence_ids": list(self.evidence_ids),
            "observation_ids": list(self.observation_ids),
            "lineage": self.lineage,
            "provenance": self.provenance,
            "safety_context": self.safety_context,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
            "audit_metadata": self.audit_metadata,
            "causality_status": self.causality_status,
        })


@dataclass(frozen=True)
class DecisionValidation:
    valid: bool
    status: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    lineage: Optional[dict[str, Any]] = None


class C2OutcomeDecisionBoundary:
    """Create auditable in-memory decisions from real P6 outcomes only."""

    def __init__(self, outcomes: C2ExperimentObservationOutcomeBoundary):
        if not isinstance(outcomes, C2ExperimentObservationOutcomeBoundary):
            raise TypeError("outcomes must be a C2ExperimentObservationOutcomeBoundary")
        self.outcomes = outcomes
        self._by_id: dict[str, C2OutcomeDecision] = {}
        self._by_key: dict[str, C2OutcomeDecision] = {}

    def get(self, decision_id: str) -> Optional[C2OutcomeDecision]:
        return self._by_id.get(decision_id)

    def decide(self, outcome: C2ExperimentOutcome | str, *, rationale: Optional[dict[str, Any]] = None) -> C2OutcomeDecision:
        outcome_record = self._resolve_outcome(outcome)
        validation = self.validate(outcome_record, rationale=rationale)
        if not validation.valid:
            raise ValueError("decision_rejected:" + ";".join(validation.errors))
        execution = self.outcomes.executions.get(outcome_record.execution_id)
        assert execution is not None
        proposal = self.outcomes.executions.proposals.get(outcome_record.proposal_id)
        assert proposal is not None
        observations = [self.outcomes.get_observation(item) for item in outcome_record.observation_ids]
        resolved_observations = [item for item in observations if item is not None]
        evidence_ids = tuple(execution.evidence_ids)
        classification = _RESULT_TO_CLASSIFICATION[outcome_record.result]
        sources = tuple(dict.fromkeys((outcome_record.outcome_id, *outcome_record.observation_ids, *evidence_ids, execution.execution_id, proposal.proposal_id, proposal.hypothesis_id)))
        rationale_value = rationale or self._default_rationale(outcome_record, sources)
        key = self._idempotency_key(outcome_record, proposal, rationale_value)
        if key in self._by_key:
            raise ValueError("duplicate_decision_idempotency_key")
        lineage = self._build_lineage(outcome_record, execution.execution_id, proposal.proposal_id, sources)
        decision = C2OutcomeDecision(
            decision_id=f"dec_c2_{uuid.uuid4().hex}",
            decision_version="c2-p7-1",
            outcome_id=outcome_record.outcome_id,
            execution_id=execution.execution_id,
            proposal_id=proposal.proposal_id,
            proposal_version=outcome_record.proposal_version,
            hypothesis_id=proposal.hypothesis_id,
            metric_reference=dict(outcome_record.metric_reference),
            evaluated_outcome=outcome_record.to_dict(),
            decision_classification=classification,
            rationale=dict(rationale_value),
            evidence_ids=evidence_ids,
            observation_ids=tuple(item.observation_id for item in resolved_observations),
            lineage=lineage,
            provenance={"source": "c2.p7.outcome_decision_boundary", "outcome_id": outcome_record.outcome_id},
            safety_context={"causality_status": "not_claimed", "substantive": outcome_record.result not in {"insufficient_sample", "inconclusive"}},
            idempotency_key=key,
            created_at=_now(),
            audit_metadata={"mode": "isolated_in_memory", "source": "c2.p7"},
        )
        self._by_id[decision.decision_id] = decision
        self._by_key[key] = decision
        return decision

    def validate(self, outcome: C2ExperimentOutcome | str, *, rationale: Optional[dict[str, Any]] = None) -> DecisionValidation:
        errors: list[str] = []
        outcome_record = self._try_resolve_outcome(outcome)
        if outcome_record is None:
            return DecisionValidation(False, "rejected", ("outcome_not_found",))
        outcome_lineage = self.outcomes.lineage_view(outcome_record.outcome_id)
        if outcome_lineage.get("status") != "complete":
            errors.append("outcome_lineage_not_complete")
        if outcome_lineage.get("missing_ids") or outcome_lineage.get("invalid_edges"):
            errors.append("outcome_lineage_invalid")
        if outcome_record.result not in _RESULT_STATUSES:
            errors.append("outcome_result_unsupported")
        if outcome_record.causality_status != "not_claimed":
            errors.append("outcome_causality_status_invalid")
        if not outcome_record.provenance:
            errors.append("outcome_provenance_missing")
        execution = self.outcomes.executions.get(outcome_record.execution_id)
        if execution is None or execution.status not in {"completed", "failed", "rolled_back"}:
            errors.append("execution_invalid_or_not_completed")
        proposal = self.outcomes.executions.proposals.get(outcome_record.proposal_id) if execution else None
        if proposal is None:
            errors.append("proposal_not_found")
        else:
            if str(outcome_record.proposal_version) != str(execution.proposal_version):
                errors.append("proposal_version_mismatch")
            if proposal.metric_name != outcome_record.metric_reference.get("name"):
                errors.append("metric_mismatch")
            if proposal.status != "validated":
                errors.append("proposal_not_validated")
        observations = []
        for observation_id in outcome_record.observation_ids:
            observation = self.outcomes.get_observation(observation_id)
            if observation is None:
                errors.append(f"observation_not_found:{observation_id}")
                continue
            observations.append(observation)
            if not observation.provenance:
                errors.append(f"observation_provenance_missing:{observation_id}")
            if observation.execution_id != outcome_record.execution_id or observation.proposal_id != outcome_record.proposal_id:
                errors.append(f"observation_lineage_mismatch:{observation_id}")
        if not observations:
            errors.append("observations_required")
        if execution is not None and set(outcome_record.metric_reference) and outcome_record.metric_reference.get("name") != execution.metric_reference.get("name"):
            errors.append("execution_metric_mismatch")
        if rationale is not None:
            errors.extend(self._validate_rationale(rationale, outcome_record, execution, proposal, observations))
        classification = _RESULT_TO_CLASSIFICATION.get(outcome_record.result)
        if classification is None:
            errors.append("classification_not_defined")
        if outcome_record.result == "insufficient_sample" and classification in {"supported", "rejected"}:
            errors.append("insufficient_sample_substantive_decision_forbidden")
        lineage = self._build_lineage(outcome_record, execution.execution_id if execution else "", proposal.proposal_id if proposal else "", (outcome_record.outcome_id, *outcome_record.observation_ids))
        if lineage.get("missing_ids") or lineage.get("invalid_edges"):
            errors.append("decision_lineage_not_resolved")
        return DecisionValidation(not errors, "eligible" if not errors else "rejected", tuple(dict.fromkeys(errors)), lineage=lineage)

    def lineage_view(self, decision_id: str) -> dict[str, Any]:
        decision = self.get(decision_id)
        if decision is None:
            return {"status": "not_found", "decision_id": decision_id, "missing_ids": [decision_id], "invalid_edges": [], "resolved_edges": [], "quality_warnings": []}
        return dict(decision.lineage) | {"status": "complete", "decision_id": decision_id, "records_by_type": {"outcome_decision": [decision.to_dict()]}}

    def _resolve_outcome(self, outcome: C2ExperimentOutcome | str) -> C2ExperimentOutcome:
        resolved = self._try_resolve_outcome(outcome)
        if resolved is None:
            raise ValueError("outcome_not_found")
        return resolved

    def _try_resolve_outcome(self, outcome: C2ExperimentOutcome | str) -> Optional[C2ExperimentOutcome]:
        if isinstance(outcome, C2ExperimentOutcome):
            owned = self.outcomes.get_outcome(outcome.outcome_id)
            return owned if owned is not None else None
        return self.outcomes.get_outcome(outcome)

    @staticmethod
    def _default_rationale(outcome: C2ExperimentOutcome, sources: tuple[str, ...]) -> dict[str, Any]:
        return {"summary": f"Rule-based outcome '{outcome.result}' evaluated for metric '{outcome.metric_reference.get('name')}'. Interpretation is observational only.", "source_ids": list(sources), "limitations": ["observational", "rule_based", "no_causal_inference"]}

    @staticmethod
    def _validate_rationale(rationale: Mapping[str, Any], outcome: C2ExperimentOutcome, execution: Any, proposal: Any, observations: list[Any]) -> list[str]:
        errors: list[str] = []
        summary = rationale.get("summary", "")
        source_ids = set(rationale.get("source_ids", ()))
        allowed = {outcome.outcome_id, *(item.observation_id for item in observations)}
        if execution is not None:
            allowed.add(execution.execution_id)
            allowed.update(execution.evidence_ids)
        if proposal is not None:
            allowed.update({proposal.proposal_id, proposal.hypothesis_id})
        if not isinstance(summary, str) or not summary.strip():
            errors.append("rationale_summary_missing")
        if _CAUSAL.search(str(summary)):
            errors.append("rationale_causal_claim_rejected")
        if not source_ids:
            errors.append("rationale_sources_missing")
        elif not source_ids.issubset(allowed):
            errors.append("rationale_source_not_in_lineage")
        return errors

    @staticmethod
    def _build_lineage(outcome: C2ExperimentOutcome, execution_id: str, proposal_id: str, source_ids: tuple[str, ...]) -> dict[str, Any]:
        missing = [item for item in source_ids if not item]
        resolved = [{"from": item, "to": outcome.outcome_id, "type": "decision_source"} for item in source_ids if item]
        resolved.append({"from": outcome.outcome_id, "to": "pending_decision", "type": "decision"})
        return {"status": "complete" if not missing else "partial", "missing_ids": missing, "invalid_edges": [], "resolved_edges": resolved, "quality_warnings": [], "parent_record_ids": [outcome.outcome_id, execution_id, proposal_id], "source_record_ids": list(source_ids)}

    @staticmethod
    def _idempotency_key(outcome: C2ExperimentOutcome, proposal: Any, rationale: Mapping[str, Any]) -> str:
        raw = json.dumps({"outcome_id": outcome.outcome_id, "outcome_key": outcome.idempotency_key, "proposal_version": outcome.proposal_version, "policy": rationale.get("policy", "default"), "classification": _RESULT_TO_CLASSIFICATION.get(outcome.result)}, sort_keys=True, separators=(",", ":"))
        return "decision:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


_RESULT_STATUSES = {"success", "failure", "inconclusive", "insufficient_sample"}


def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        allowed = {"record_type", "schema_version", "decision_id", "decision_version", "outcome_id", "execution_id", "proposal_id", "proposal_version", "hypothesis_id", "metric_reference", "evaluated_outcome", "decision_classification", "rationale", "summary", "source_ids", "limitations", "evidence_ids", "observation_ids", "lineage", "provenance", "safety_context", "idempotency_key", "created_at", "audit_metadata", "causality_status", "result", "result_reason", "name", "success_rule", "inconclusive_rule", "parent_record_ids", "source_record_ids", "resolved_edges", "quality_warnings", "causality_status", "substantive", "source", "mode", "policy"}
        return {str(k): _sanitize(v, str(k)) for k, v in value.items() if str(k) in allowed}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str) and _SECRET.search(value):
        return "[REDACTED]"
    return value


__all__ = ["C2OutcomeDecision", "C2OutcomeDecisionBoundary", "DecisionValidation"]
