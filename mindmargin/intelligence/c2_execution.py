"""C2-P5 isolated experiment execution boundary.

This module executes only an in-memory, side-effect-free execution state machine.
It does not call schedulers, publishers, workflows, A/B services, ledgers,
production executors, Knowledge, or Strategy components.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from mindmargin.intelligence.c2_proposals import (
    C2ExperimentProposal,
    C2ExperimentProposalBoundary,
)

_EXECUTION_STATUSES = {"prepared", "authorized", "running", "completed", "failed", "cancelled", "rolled_back"}
_TERMINAL = {"completed", "failed", "cancelled", "rolled_back"}
_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential|bearer)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class C2ExperimentExecution:
    execution_id: str
    proposal_id: str
    proposal_version: str
    hypothesis_id: str
    decision_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    metric_reference: dict[str, Any]
    selected_variants: tuple[dict[str, Any], ...]
    resolved_population: dict[str, Any]
    eligibility: dict[str, Any]
    execution_scope: dict[str, Any]
    safety_constraints: tuple[dict[str, Any], ...]
    rollback_criteria: tuple[dict[str, Any], ...]
    status: str
    created_at: str
    authorized_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    failed_at: str = ""
    cancelled_at: str = ""
    rolled_back_at: str = ""
    failure_reason: str = ""
    rollback_reason: str = ""
    idempotency_key: str = ""
    audit_metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.status not in _EXECUTION_STATUSES:
            raise ValueError(f"invalid execution status: {self.status}")
        if not self.execution_id.startswith("exec_c2_"):
            raise ValueError("execution_id must use the C2-P5 prefix")
        if not self.proposal_id or not self.hypothesis_id:
            raise ValueError("proposal_id and hypothesis_id are required")
        if not self.decision_ids or not self.evidence_ids:
            raise ValueError("decision_ids and evidence_ids are required")
        if not self.metric_reference or not self.metric_reference.get("name"):
            raise ValueError("metric_reference.name is required")
        if not self.selected_variants:
            raise ValueError("selected_variants are required")
        if not self.resolved_population or not self.eligibility:
            raise ValueError("resolved population and eligibility are required")
        if not self.safety_constraints or not self.rollback_criteria:
            raise ValueError("safety and rollback criteria are required")
        if not self.idempotency_key:
            raise ValueError("idempotency_key is required")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "record_type": "experiment_execution",
            "schema_version": "c2-p5-1",
            "execution_id": self.execution_id,
            "proposal_id": self.proposal_id,
            "proposal_version": self.proposal_version,
            "hypothesis_id": self.hypothesis_id,
            "decision_ids": list(self.decision_ids),
            "evidence_ids": list(self.evidence_ids),
            "metric_reference": self.metric_reference,
            "selected_variants": list(self.selected_variants),
            "resolved_population": self.resolved_population,
            "eligibility": self.eligibility,
            "execution_scope": self.execution_scope,
            "safety_constraints": list(self.safety_constraints),
            "rollback_criteria": list(self.rollback_criteria),
            "status": self.status,
            "created_at": self.created_at,
            "authorized_at": self.authorized_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "cancelled_at": self.cancelled_at,
            "rolled_back_at": self.rolled_back_at,
            "failure_reason": self.failure_reason,
            "rollback_reason": self.rollback_reason,
            "idempotency_key": self.idempotency_key,
            "audit_metadata": self.audit_metadata or {},
        }
        return _sanitize(payload)


@dataclass(frozen=True)
class ExecutionValidation:
    valid: bool
    status: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    lineage: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ExecutionOutcome:
    execution: Optional[C2ExperimentExecution]
    validation: ExecutionValidation


class C2ExperimentExecutionBoundary:
    """Side-effect-free P5 execution state machine over validated P4 proposals."""

    def __init__(self, proposals: C2ExperimentProposalBoundary):
        if not isinstance(proposals, C2ExperimentProposalBoundary):
            raise TypeError("proposals must be a C2ExperimentProposalBoundary")
        self.proposals = proposals
        self._by_id: dict[str, C2ExperimentExecution] = {}
        self._by_key: dict[str, C2ExperimentExecution] = {}

    def prepare(
        self,
        proposal: C2ExperimentProposal | str,
        *,
        execution_scope: Optional[dict[str, Any]] = None,
        selected_variants: Optional[tuple[dict[str, Any], ...] | list[dict[str, Any]]] = None,
    ) -> C2ExperimentExecution:
        proposal_record = self._resolve_proposal(proposal)
        validation = self.validate_proposal(proposal_record, execution_scope=execution_scope, selected_variants=selected_variants)
        if not validation.valid:
            raise ValueError("proposal_not_eligible:" + ";".join(validation.errors))
        scope = dict(execution_scope or self._proposal_scope(proposal_record))
        variants = tuple(selected_variants or proposal_record.variants)
        key = self._idempotency_key(proposal_record, scope, variants)
        if key in self._by_key:
            raise ValueError("duplicate_execution_idempotency_key")
        execution = C2ExperimentExecution(
            execution_id=f"exec_c2_{uuid.uuid4().hex}",
            proposal_id=proposal_record.proposal_id,
            proposal_version=str(proposal_record.envelope.get("schema_version", "c2-p4-1")),
            hypothesis_id=proposal_record.hypothesis_id,
            decision_ids=proposal_record.decision_ids,
            evidence_ids=proposal_record.supporting_evidence_ids,
            metric_reference={"name": proposal_record.metric_name, "success_rule": proposal_record.success_rule, "inconclusive_rule": proposal_record.inconclusive_rule},
            selected_variants=variants,
            resolved_population=dict(proposal_record.population),
            eligibility=dict(proposal_record.eligibility),
            execution_scope=scope,
            safety_constraints=proposal_record.safety_constraints,
            rollback_criteria=proposal_record.rollback_criteria,
            status="prepared",
            created_at=_now(),
            idempotency_key=key,
            audit_metadata={"source": "c2.p5.execution_boundary", "mode": "isolated_in_memory"},
        )
        self._by_id[execution.execution_id] = execution
        self._by_key[key] = execution
        return execution

    def get(self, execution_id: str) -> Optional[C2ExperimentExecution]:
        return self._by_id.get(execution_id)

    def validate_proposal(
        self,
        proposal: C2ExperimentProposal,
        *,
        execution_scope: Optional[dict[str, Any]] = None,
        selected_variants: Optional[tuple[dict[str, Any], ...] | list[dict[str, Any]]] = None,
    ) -> ExecutionValidation:
        errors: list[str] = []
        if not isinstance(proposal, C2ExperimentProposal):
            return ExecutionValidation(False, "rejected", ("proposal_type_invalid",))
        if proposal.status != "validated":
            errors.append("proposal_must_be_validated")
        # P4 validation is defined for proposed records. Revalidate the immutable
        # proposal gates through a temporary proposed view without mutating P4.
        proposed_view = replace(proposal, status="proposed", envelope={**proposal.envelope, "status": "proposed"})
        p4_validation = self.proposals.validate(proposed_view)
        if not p4_validation.valid:
            errors.extend(f"proposal_gate:{error}" for error in p4_validation.errors)
        if p4_validation.lineage is None or p4_validation.lineage.get("status") != "complete":
            errors.append("proposal_lineage_not_complete")
        scope = execution_scope or self._proposal_scope(proposal)
        errors.extend(self._scope_errors(proposal, scope))
        variants = tuple(selected_variants or proposal.variants)
        errors.extend(self._variant_selection_errors(proposal, variants))
        if not proposal.minimum_sample or proposal.minimum_sample < 2:
            errors.append("minimum_sample_gate_missing_or_insufficient")
        if not proposal.success_rule:
            errors.append("success_rule_missing")
        if not proposal.inconclusive_rule:
            errors.append("inconclusive_rule_missing")
        if not proposal.safety_constraints:
            errors.append("safety_constraints_missing")
        if not proposal.rollback_criteria:
            errors.append("rollback_criteria_missing")
        lineage = p4_validation.lineage
        if errors:
            return ExecutionValidation(False, "rejected", tuple(dict.fromkeys(errors)), lineage=lineage)
        return ExecutionValidation(True, "eligible", lineage=lineage)

    def authorize(self, execution: C2ExperimentExecution) -> C2ExperimentExecution:
        self._require_owned(execution)
        if execution.status != "prepared":
            raise ValueError("only prepared execution can be authorized")
        refreshed = self._refresh_execution(execution)
        validation = self.validate_proposal(self._resolve_proposal(refreshed.proposal_id), execution_scope=refreshed.execution_scope, selected_variants=refreshed.selected_variants)
        if not validation.valid:
            raise ValueError("execution_safety_gate_failed:" + ";".join(validation.errors))
        authorized = replace(refreshed, status="authorized", authorized_at=_now())
        return self._store(authorized)

    def execute(self, execution: C2ExperimentExecution, *, isolated_result: Optional[dict[str, Any]] = None) -> C2ExperimentExecution:
        """Run only the in-memory state machine; no external executor is accepted."""
        self._require_owned(execution)
        if execution.status != "authorized":
            raise ValueError("execution_requires_authorized_state")
        running = self._store(replace(execution, status="running", started_at=_now()))
        result = dict(isolated_result or {"mode": "isolated_in_memory", "status": "completed"})
        if result.get("status") in {"failed", "error"}:
            return self._store(replace(running, status="failed", failed_at=_now(), failure_reason=str(result.get("reason", "isolated execution failed"))))
        return self._store(replace(running, status="completed", completed_at=_now()))

    def cancel(self, execution: C2ExperimentExecution, reason: str) -> C2ExperimentExecution:
        self._require_owned(execution)
        if execution.status in _TERMINAL:
            raise ValueError("terminal execution cannot be cancelled")
        if not reason.strip():
            raise ValueError("cancel reason is required")
        return self._store(replace(execution, status="cancelled", cancelled_at=_now(), failure_reason=reason))

    def rollback(self, execution: C2ExperimentExecution, reason: str) -> C2ExperimentExecution:
        self._require_owned(execution)
        if execution.status not in {"running", "completed", "failed"}:
            raise ValueError("execution cannot be rolled back from current state")
        if not reason.strip():
            raise ValueError("rollback reason is required")
        return self._store(replace(execution, status="rolled_back", rolled_back_at=_now(), rollback_reason=reason))

    def fail(self, execution: C2ExperimentExecution, reason: str) -> C2ExperimentExecution:
        self._require_owned(execution)
        if execution.status not in {"authorized", "running"}:
            raise ValueError("execution cannot fail from current state")
        if not reason.strip():
            raise ValueError("failure reason is required")
        return self._store(replace(execution, status="failed", failed_at=_now(), failure_reason=reason))

    def lineage_view(self, execution_id: str) -> dict[str, Any]:
        execution = self.get(execution_id)
        if execution is None:
            return {"status": "not_found", "execution_id": execution_id, "missing_ids": [execution_id], "invalid_edges": [], "resolved_edges": [], "records_by_type": {}}
        proposal_lineage = self.proposals.get_lineage(execution.proposal_id)
        records = dict(proposal_lineage.get("records_by_type", {}))
        records.setdefault("experiment_execution", []).append(execution.to_dict())
        missing = list(proposal_lineage.get("missing_ids", []))
        invalid = list(proposal_lineage.get("invalid_edges", []))
        resolved = list(proposal_lineage.get("resolved_edges", []))
        resolved.append({"from": execution.proposal_id, "to": execution.execution_id, "type": "execution"})
        status = "complete" if proposal_lineage.get("status") == "complete" and not missing and not invalid else "partial"
        return {"status": status, "execution_id": execution_id, "missing_ids": missing, "invalid_edges": invalid, "resolved_edges": resolved, "records_by_type": records, "quality_warnings": proposal_lineage.get("quality_warnings", [])}

    def _resolve_proposal(self, proposal: C2ExperimentProposal | str) -> C2ExperimentProposal:
        if isinstance(proposal, C2ExperimentProposal):
            return proposal
        record = self.proposals.get(proposal)
        if record is None:
            raise ValueError("proposal_not_found")
        return record

    @staticmethod
    def _proposal_scope(proposal: C2ExperimentProposal) -> dict[str, Any]:
        return {field: proposal.envelope.get(field, "") for field in ("pipeline_id", "content_id", "story_id", "video_id", "correlation_id")}

    @staticmethod
    def _scope_errors(proposal: C2ExperimentProposal, scope: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        expected = C2ExperimentExecutionBoundary._proposal_scope(proposal)
        for field, expected_value in expected.items():
            actual = scope.get(field, "")
            if expected_value and actual != expected_value:
                errors.append(f"execution_scope_mismatch:{field}")
        return errors

    @staticmethod
    def _variant_selection_errors(proposal: C2ExperimentProposal, variants: tuple[dict[str, Any], ...]) -> list[str]:
        allowed = {str(item.get("variant_id")) for item in proposal.variants}
        selected = {str(item.get("variant_id")) for item in variants}
        errors: list[str] = []
        if not selected or not selected.issubset(allowed):
            errors.append("selected_variants_outside_proposal")
        roles = {str(item.get("role")) for item in variants}
        if roles != {"control", "treatment"}:
            errors.append("selected_control_treatment_required")
        return errors

    def _idempotency_key(self, proposal: C2ExperimentProposal, scope: Mapping[str, Any], variants: tuple[dict[str, Any], ...]) -> str:
        raw = json.dumps({"proposal_id": proposal.proposal_id, "proposal_version": proposal.envelope.get("schema_version", "c2-p4-1"), "scope": dict(scope), "variants": sorted(variants, key=lambda item: str(item.get("variant_id")))}, sort_keys=True, separators=(",", ":"))
        return "execution:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _require_owned(self, execution: C2ExperimentExecution) -> None:
        if not isinstance(execution, C2ExperimentExecution) or execution.execution_id not in self._by_id:
            raise ValueError("execution_not_owned_by_boundary")

    def _refresh_execution(self, execution: C2ExperimentExecution) -> C2ExperimentExecution:
        return self._by_id[execution.execution_id]

    def _store(self, execution: C2ExperimentExecution) -> C2ExperimentExecution:
        self._by_id[execution.execution_id] = execution
        self._by_key[execution.idempotency_key] = execution
        return execution


def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        allowed = {
            "record_type", "schema_version", "execution_id", "proposal_id", "proposal_version", "hypothesis_id", "decision_ids", "evidence_ids", "metric_reference", "selected_variants", "resolved_population", "eligibility", "execution_scope", "safety_constraints", "rollback_criteria", "status", "created_at", "authorized_at", "started_at", "completed_at", "failed_at", "cancelled_at", "rolled_back_at", "failure_reason", "rollback_reason", "idempotency_key", "audit_metadata", "name", "success_rule", "inconclusive_rule", "variant_id", "role", "description", "unit", "scope", "rule", "condition", "criterion", "action", "mode", "source", "status", "reason", "value", "type",
        }
        return {str(k): _sanitize(v, str(k)) for k, v in value.items() if str(k) in allowed}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str) and _SECRET.search(value):
        return "[REDACTED]"
    return value


__all__ = ["C2ExperimentExecution", "C2ExperimentExecutionBoundary", "ExecutionOutcome", "ExecutionValidation"]
