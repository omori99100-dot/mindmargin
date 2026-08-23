"""C2-P8 Decision Governance Boundary.

This module evaluates P7 decisions against an explicit, immutable-in-use
policy. It returns governance status only; it never executes, persists,
publishes, schedules, or mutates Knowledge/Strategy/production state.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from mindmargin.intelligence.c2_decisions import C2OutcomeDecision, C2OutcomeDecisionBoundary

_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential|bearer)")
_CAUSAL = re.compile(r"(?i)\b(causal|causality|caused|cause|proven cause|guaranteed effect|causal certainty|سبب|يثبت أن)\b")
_GOVERNANCE_STATUSES = {"eligible", "approved_for_future_action", "blocked", "rejected", "requires_review"}
_ALLOWED_CLASSIFICATIONS = {"supported", "rejected", "inconclusive", "insufficient_evidence"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class C2GovernancePolicy:
    policy_id: str
    policy_version: str
    allowed_classifications: tuple[str, ...] = ("supported", "rejected", "inconclusive", "insufficient_evidence")
    approve_classifications: tuple[str, ...] = ("supported", "rejected")
    inconclusive_status: str = "requires_review"
    insufficient_evidence_status: str = "blocked"
    invalid_status: str = "rejected"
    scope: dict[str, Any] = None  # type: ignore[assignment]
    audit_metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_version:
            raise ValueError("policy_id and policy_version are required")
        if not self.allowed_classifications or not set(self.allowed_classifications).issubset(_ALLOWED_CLASSIFICATIONS):
            raise ValueError("policy classifications are invalid")
        if not set(self.approve_classifications).issubset(set(self.allowed_classifications)):
            raise ValueError("approve classifications must be allowed")
        if self.inconclusive_status not in {"requires_review", "blocked"}:
            raise ValueError("invalid inconclusive governance status")
        if self.insufficient_evidence_status not in {"blocked", "requires_review"}:
            raise ValueError("invalid insufficient evidence governance status")
        if self.invalid_status not in {"rejected", "blocked", "requires_review"}:
            raise ValueError("invalid policy rejection status")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize({
            "record_type": "governance_policy",
            "schema_version": "c2-p8-1",
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "allowed_classifications": list(self.allowed_classifications),
            "approve_classifications": list(self.approve_classifications),
            "inconclusive_status": self.inconclusive_status,
            "insufficient_evidence_status": self.insufficient_evidence_status,
            "invalid_status": self.invalid_status,
            "scope": self.scope or {},
            "audit_metadata": self.audit_metadata or {},
        })


@dataclass(frozen=True)
class C2GovernanceRecord:
    governance_id: str
    governance_version: str
    decision_id: str
    decision_version: str
    outcome_id: str
    decision_classification: str
    governance_status: str
    policy_id: str
    policy_version: str
    policy_snapshot: dict[str, Any]
    rationale: dict[str, Any]
    lineage: dict[str, Any]
    provenance: dict[str, Any]
    safety_context: dict[str, Any]
    idempotency_key: str
    created_at: str
    audit_metadata: dict[str, Any]
    causality_status: str = "not_claimed"

    def __post_init__(self) -> None:
        if not self.governance_id.startswith("gov_c2_"):
            raise ValueError("governance_id must use the C2-P8 prefix")
        if self.governance_status not in _GOVERNANCE_STATUSES:
            raise ValueError("unsupported governance status")
        if self.decision_classification not in _ALLOWED_CLASSIFICATIONS:
            raise ValueError("unsupported decision classification")
        if self.causality_status != "not_claimed":
            raise ValueError("P8 governance must remain non-causal")
        if not self.rationale.get("source_ids") or not self.rationale.get("summary"):
            raise ValueError("auditable rationale is required")
        if _CAUSAL.search(json.dumps(self.rationale, ensure_ascii=False)):
            raise ValueError("causal governance rationale is not allowed")
        if not self.lineage or not self.provenance or not self.safety_context:
            raise ValueError("lineage/provenance/safety context are required")
        if not self.idempotency_key:
            raise ValueError("governance idempotency key is required")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize({
            "record_type": "decision_governance",
            "schema_version": "c2-p8-1",
            "governance_id": self.governance_id,
            "governance_version": self.governance_version,
            "decision_id": self.decision_id,
            "decision_version": self.decision_version,
            "outcome_id": self.outcome_id,
            "decision_classification": self.decision_classification,
            "governance_status": self.governance_status,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_snapshot": self.policy_snapshot,
            "rationale": self.rationale,
            "lineage": self.lineage,
            "provenance": self.provenance,
            "safety_context": self.safety_context,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
            "audit_metadata": self.audit_metadata,
            "causality_status": self.causality_status,
        })


@dataclass(frozen=True)
class GovernanceValidation:
    valid: bool
    status: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    lineage: Optional[dict[str, Any]] = None


class C2DecisionGovernanceBoundary:
    """Evaluate P7 decisions without executing or persisting governance."""

    def __init__(self, decisions: C2OutcomeDecisionBoundary, policy: C2GovernancePolicy):
        if not isinstance(decisions, C2OutcomeDecisionBoundary):
            raise TypeError("decisions must be a C2OutcomeDecisionBoundary")
        if not isinstance(policy, C2GovernancePolicy):
            raise TypeError("policy must be a C2GovernancePolicy")
        self.decisions = decisions
        self.policy = policy
        self._by_id: dict[str, C2GovernanceRecord] = {}
        self._by_key: dict[str, C2GovernanceRecord] = {}

    def get(self, governance_id: str) -> Optional[C2GovernanceRecord]:
        return self._by_id.get(governance_id)

    def evaluate(self, decision: C2OutcomeDecision | str) -> GovernanceValidation:
        record = self._resolve_decision(decision)
        if record is None:
            return GovernanceValidation(False, self.policy.invalid_status, ("decision_not_found",))
        errors: list[str] = []
        lineage = dict(record.lineage)
        if lineage.get("status") != "complete" or lineage.get("missing_ids") or lineage.get("invalid_edges"):
            errors.append("decision_lineage_incomplete_or_invalid")
        if record.decision_classification not in self.policy.allowed_classifications:
            errors.append("classification_not_allowed_by_policy")
        if record.causality_status != "not_claimed":
            errors.append("decision_causality_status_invalid")
        if not record.provenance:
            errors.append("decision_provenance_missing")
        if not record.rationale.get("source_ids"):
            errors.append("decision_rationale_sources_missing")
        if _CAUSAL.search(json.dumps(record.to_dict(), ensure_ascii=False)):
            errors.append("causal_claim_rejected")
        expected_sources = set(record.lineage.get("source_record_ids", ()))
        actual_sources = set(record.rationale.get("source_ids", ()))
        if not actual_sources.issubset(expected_sources):
            errors.append("rationale_source_outside_decision_lineage")
        if errors:
            return GovernanceValidation(False, self.policy.invalid_status, tuple(dict.fromkeys(errors)), lineage=lineage)
        classification = record.decision_classification
        if classification == "inconclusive":
            status = self.policy.inconclusive_status
        elif classification == "insufficient_evidence":
            status = self.policy.insufficient_evidence_status
        elif classification in self.policy.approve_classifications:
            status = "approved_for_future_action"
        else:
            status = "eligible"
        return GovernanceValidation(True, status, lineage=lineage)

    def govern(self, decision: C2OutcomeDecision | str) -> C2GovernanceRecord:
        record = self._resolve_decision(decision)
        if record is None:
            raise ValueError("governance_rejected:decision_not_found")
        validation = self.evaluate(record)
        if not validation.valid:
            raise ValueError("governance_rejected:" + ";".join(validation.errors))
        key = self._idempotency_key(record)
        if key in self._by_key:
            raise ValueError("duplicate_governance_idempotency_key")
        governance = C2GovernanceRecord(
            governance_id=f"gov_c2_{uuid.uuid4().hex}",
            governance_version="c2-p8-1",
            decision_id=record.decision_id,
            decision_version=record.decision_version,
            outcome_id=record.outcome_id,
            decision_classification=record.decision_classification,
            governance_status=validation.status,
            policy_id=self.policy.policy_id,
            policy_version=self.policy.policy_version,
            policy_snapshot=self.policy.to_dict(),
            rationale={"summary": f"Governance evaluated decision classification '{record.decision_classification}'.", "source_ids": [record.decision_id, *record.rationale.get("source_ids", ())], "limitations": ["evaluation_only", "no_execution", "no_production_action"]},
            lineage={**record.lineage, "resolved_edges": [*record.lineage.get("resolved_edges", []), {"from": record.decision_id, "to": "pending_governance", "type": "governance_evaluation"}]},
            provenance={"source": "c2.p8.decision_governance_boundary", "decision_id": record.decision_id},
            safety_context={"execution": False, "production_action": False, "knowledge_mutation": False, "strategy_mutation": False, "causality_status": "not_claimed"},
            idempotency_key=key,
            created_at=_now(),
            audit_metadata={"mode": "isolated_in_memory", "source": "c2.p8"},
        )
        self._by_id[governance.governance_id] = governance
        self._by_key[key] = governance
        return governance

    def lineage_view(self, governance_id: str) -> dict[str, Any]:
        record = self.get(governance_id)
        if record is None:
            return {"status": "not_found", "governance_id": governance_id, "missing_ids": [governance_id], "invalid_edges": [], "resolved_edges": [], "quality_warnings": []}
        return dict(record.lineage) | {"status": "complete", "governance_id": governance_id, "records_by_type": {"decision_governance": [record.to_dict()]}}

    def _resolve_decision(self, decision: C2OutcomeDecision | str) -> Optional[C2OutcomeDecision]:
        if isinstance(decision, C2OutcomeDecision):
            return self.decisions.get(decision.decision_id)
        return self.decisions.get(decision)

    def _idempotency_key(self, decision: C2OutcomeDecision) -> str:
        raw = json.dumps({"decision_id": decision.decision_id, "decision_version": decision.decision_version, "decision_key": decision.idempotency_key, "policy": self.policy.to_dict()}, sort_keys=True, separators=(",", ":"))
        return "governance:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        allowed = {"record_type", "schema_version", "governance_id", "governance_version", "decision_id", "decision_version", "outcome_id", "decision_classification", "governance_status", "policy_id", "policy_version", "policy_snapshot", "allowed_classifications", "approve_classifications", "inconclusive_status", "insufficient_evidence_status", "invalid_status", "rationale", "summary", "source_ids", "limitations", "lineage", "provenance", "safety_context", "idempotency_key", "created_at", "audit_metadata", "causality_status", "resolved_edges", "missing_ids", "invalid_edges", "quality_warnings", "parent_record_ids", "source_record_ids", "source", "execution", "production_action", "knowledge_mutation", "strategy_mutation", "evaluation_only", "no_execution", "no_production_action"}
        return {str(k): _sanitize(v, str(k)) for k, v in value.items() if str(k) in allowed}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str) and _SECRET.search(value):
        return "[REDACTED]"
    return value


__all__ = ["C2GovernancePolicy", "C2GovernanceRecord", "C2DecisionGovernanceBoundary", "GovernanceValidation"]
