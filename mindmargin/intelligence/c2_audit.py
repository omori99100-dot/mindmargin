"""C2-P9 read-only Governance Audit & Closure Boundary.

P9 audits the actual P0-P8 chain and returns a deterministic report. It does
not repair, persist, execute, publish, schedule, or mutate any boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from mindmargin.intelligence.c2_governance import (
    C2DecisionGovernanceBoundary,
    C2GovernanceRecord,
)

_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential|bearer)")
_CAUSAL = re.compile(r"(?i)\b(causal|causality|caused|cause|proven cause|guaranteed effect|causal certainty|سبب|يثبت أن)\b")
_AUDIT_STATUSES = {"passed", "failed", "blocked", "requires_review"}
_EXPECTED_VERSIONS = {
    "p0": ("c2-1", "c2-p0-1", "c2-p0-1"),
    "p3": "c2-p3-1",
    "p4": "c2-p4-1",
    "p5": "c2-p5-1",
    "p6": ("c2-p6-observation-1", "c2-p6-outcome-1"),
    "p7": "c2-p7-1",
    "p8": "c2-p8-1",
}


@dataclass(frozen=True)
class C2AuditReport:
    audit_id: str
    audit_version: str
    status: str
    closure_ready: bool
    closure_readiness: str
    governance_id: str
    stage_statuses: dict[str, str]
    records_by_stage: dict[str, list[dict[str, Any]]]
    resolved_edges: tuple[dict[str, Any], ...]
    missing_ids: tuple[str, ...]
    invalid_edges: tuple[dict[str, Any], ...]
    quality_warnings: tuple[str, ...]
    gate_results: dict[str, bool]
    version_results: dict[str, bool]
    ownership_results: dict[str, bool]
    security_results: dict[str, bool]
    idempotency_results: dict[str, bool]
    causality_results: dict[str, bool]
    governance_results: dict[str, bool]
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.audit_id.startswith("audit_c2_"):
            raise ValueError("audit_id must use the C2-P9 prefix")
        if self.audit_version != "c2-p9-1":
            raise ValueError("unsupported audit version")
        if self.status not in _AUDIT_STATUSES:
            raise ValueError("unsupported audit status")
        if self.closure_readiness not in {"ready", "not_ready"}:
            raise ValueError("unsupported closure readiness")
        if self.closure_ready != (self.closure_readiness == "ready"):
            raise ValueError("closure readiness mismatch")

    def to_dict(self) -> dict[str, Any]:
        return _sanitize({
            "record_type": "c2_audit_report",
            "schema_version": self.audit_version,
            "audit_id": self.audit_id,
            "audit_version": self.audit_version,
            "status": self.status,
            "closure_ready": self.closure_ready,
            "closure_readiness": self.closure_readiness,
            "governance_id": self.governance_id,
            "stage_statuses": self.stage_statuses,
            "records_by_stage": self.records_by_stage,
            "resolved_edges": list(self.resolved_edges),
            "missing_ids": list(self.missing_ids),
            "invalid_edges": list(self.invalid_edges),
            "quality_warnings": list(self.quality_warnings),
            "gate_results": self.gate_results,
            "version_results": self.version_results,
            "ownership_results": self.ownership_results,
            "security_results": self.security_results,
            "idempotency_results": self.idempotency_results,
            "causality_results": self.causality_results,
            "governance_results": self.governance_results,
            "provenance": self.provenance,
        })


class C2GovernanceAuditBoundary:
    """Pure audit evaluator for the real P0-P8 owners."""

    def __init__(self, governance: C2DecisionGovernanceBoundary):
        if not isinstance(governance, C2DecisionGovernanceBoundary):
            raise TypeError("governance must be a C2DecisionGovernanceBoundary")
        self.governance = governance

    def audit(self, governance: C2GovernanceRecord | str) -> C2AuditReport:
        record = self._resolve_governance(governance)
        if record is None:
            return self._report_for_missing(str(governance))
        decision_boundary = self.governance.decisions
        decision = decision_boundary.get(record.decision_id)
        p6 = decision_boundary.outcomes
        outcome = p6.get_outcome(record.outcome_id)
        execution = p6.executions.get(record.decision_id if False else (outcome.execution_id if outcome else ""))
        proposal = p6.executions.proposals.get(outcome.proposal_id if outcome else "")
        hypotheses = p6.executions.proposals.hypotheses if hasattr(p6.executions.proposals, "hypotheses") else None
        if hypotheses is None:
            hypotheses = getattr(p6.executions.proposals, "hypothesis_registry", None)
        if hypotheses is None:
            hypotheses = getattr(p6.executions, "hypotheses", None)
        evidence_access = getattr(getattr(p6.executions, "proposals", None), "hypotheses", None)
        if evidence_access is None:
            evidence_access = getattr(getattr(p6.executions, "proposals", None), "access", None)
        # P4 owns the hypothesis registry; walk through the actual proposal owner.
        proposal_boundary = getattr(p6.executions, "proposals", None)
        hypotheses = getattr(proposal_boundary, "hypotheses", None)
        evidence_access = getattr(hypotheses, "access", None)
        hypothesis = hypotheses.get(proposal.hypothesis_id) if hypotheses and proposal else None
        evidence_rows = []
        observation_rows = []
        if evidence_access and execution:
            for evidence_id in execution.evidence_ids:
                evidence = evidence_access.get_evidence(evidence_id)
                if evidence is not None:
                    evidence_rows.append(evidence)
                    for observation_id in evidence.get("observation_ids") or []:
                        observation = evidence_access.get_observation(observation_id)
                        if observation is not None:
                            observation_rows.append(observation)
        outcome_dict = outcome.to_dict() if outcome else None
        execution_dict = execution.to_dict() if execution and hasattr(execution, "to_dict") else self._object_dict(execution)
        proposal_dict = proposal.to_dict() if proposal and hasattr(proposal, "to_dict") else self._object_dict(proposal)
        hypothesis_dict = hypothesis.to_dict() if hypothesis and hasattr(hypothesis, "to_dict") else self._object_dict(hypothesis)
        records = {
            "evidence": evidence_rows,
            "hypothesis": [hypothesis_dict] if hypothesis_dict else [],
            "proposal": [proposal_dict] if proposal_dict else [],
            "execution": [execution_dict] if execution_dict else [],
            "observation": observation_rows,
            "outcome": [outcome_dict] if outcome_dict else [],
            "decision": [decision.to_dict()] if decision else [],
            "governance": [record.to_dict()],
        }
        missing: list[str] = list(record.lineage.get("missing_ids", ()))
        invalid: list[dict[str, Any]] = list(record.lineage.get("invalid_edges", ()))
        resolved: list[dict[str, Any]] = list(record.lineage.get("resolved_edges", ()))
        stages = list(records)
        for stage in stages:
            if not records[stage]:
                missing.append(stage)
        chain = [
            ("evidence", "hypothesis"), ("hypothesis", "proposal"), ("proposal", "execution"),
            ("execution", "observation"), ("observation", "outcome"), ("outcome", "decision"),
            ("decision", "governance"),
        ]
        for left, right in chain:
            if records[left] and records[right]:
                resolved.append({"from": left, "to": right, "type": "stage_continuity"})
            else:
                invalid.append({"from": left, "to": right, "reason": "missing_stage"})
        version_results = self._version_checks(records)
        ownership_results = self._ownership_checks(record, decision, outcome, execution, proposal, hypothesis, evidence_rows, observation_rows)
        security_results = self._security_checks(records)
        idempotency_results = self._idempotency_checks(records)
        causality_results = self._causality_checks(records)
        governance_results = self._governance_checks(record)
        duplicate_errors = self._duplicate_checks(records)
        invalid.extend(duplicate_errors)
        if not decision:
            missing.append(record.decision_id)
        if not outcome:
            missing.append(record.outcome_id)
        gate_results = {
            "all_stages_present": not missing,
            "lineage_continuity": not invalid,
            "versions_consistent": all(version_results.values()),
            "ownership_consistent": all(ownership_results.values()),
            "security_safe": all(security_results.values()),
            "idempotency_consistent": all(idempotency_results.values()),
            "causality_protected": all(causality_results.values()),
            "governance_protected": all(governance_results.values()),
            "no_persistence_or_production_mutation": True,
            "no_parallel_definitions": not duplicate_errors,
        }
        warnings = []
        if record.governance_status in {"requires_review", "blocked"}:
            warnings.append(f"governance_status:{record.governance_status}")
        hard_failures = (not all(gate_results.values())) or bool(missing) or bool(invalid)
        if hard_failures:
            status = "failed" if any(invalid) or missing else "requires_review"
        elif warnings:
            status = "requires_review"
        else:
            status = "passed"
        ready = status == "passed"
        identity = self._audit_id(records, record)
        return C2AuditReport(
            audit_id=identity,
            audit_version="c2-p9-1",
            status=status,
            closure_ready=ready,
            closure_readiness="ready" if ready else "not_ready",
            governance_id=record.governance_id,
            stage_statuses={stage: "present" if records[stage] else "missing" for stage in stages},
            records_by_stage=records,
            resolved_edges=tuple(resolved),
            missing_ids=tuple(dict.fromkeys(missing)),
            invalid_edges=tuple(invalid),
            quality_warnings=tuple(warnings),
            gate_results=gate_results,
            version_results=version_results,
            ownership_results=ownership_results,
            security_results=security_results,
            idempotency_results=idempotency_results,
            causality_results=causality_results,
            governance_results=governance_results,
            provenance={"source": "c2.p9.audit_boundary", "mode": "read_only_deterministic"},
        )

    def audit_records(self, records: list[Mapping[str, Any]]) -> dict[str, Any]:
        """Audit-only duplicate/parallel record detection for supplied snapshots."""
        by_id: dict[str, set[str]] = {}
        for item in records:
            rid = str(item.get("record_id") or item.get("*_id") or item.get("decision_id") or item.get("governance_id") or "")
            rtype = str(item.get("record_type") or "")
            if rid:
                by_id.setdefault(rid, set()).add(rtype)
        duplicates = [rid for rid, types in by_id.items() if len(types) > 1 or sum(1 for item in records if str(item.get("record_id") or item.get("decision_id") or item.get("governance_id") or "") == rid) > 1]
        return {"status": "failed" if duplicates else "passed", "duplicate_ids": sorted(set(duplicates)), "parallel_definitions": sorted(rid for rid, types in by_id.items() if len(types) > 1)}

    def _resolve_governance(self, record: C2GovernanceRecord | str) -> Optional[C2GovernanceRecord]:
        if isinstance(record, C2GovernanceRecord):
            return self.governance.get(record.governance_id)
        return self.governance.get(record)

    def _report_for_missing(self, value: str) -> C2AuditReport:
        return C2AuditReport(
            audit_id="audit_c2_" + hashlib.sha256(value.encode()).hexdigest()[:24], audit_version="c2-p9-1", status="blocked", closure_ready=False, closure_readiness="not_ready", governance_id=value, stage_statuses={}, records_by_stage={}, resolved_edges=(), missing_ids=(value,), invalid_edges=(), quality_warnings=(), gate_results={"all_stages_present": False}, version_results={}, ownership_results={}, security_results={}, idempotency_results={}, causality_results={}, governance_results={}, provenance={"source": "c2.p9.audit_boundary", "mode": "read_only_deterministic"})

    @staticmethod
    def _object_dict(value: Any) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return None

    @staticmethod
    def _version_checks(records: dict[str, list[dict[str, Any]]]) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for stage, rows in records.items():
            if not rows:
                result[stage] = False
                continue
            versions = {C2GovernanceAuditBoundary._version_of(row) for row in rows}
            result[stage] = len(versions) == 1 and None not in versions and "" not in versions
        return result

    @staticmethod
    def _version_of(row: Mapping[str, Any]) -> Optional[str]:
        envelope = row.get("envelope")
        if isinstance(envelope, Mapping):
            return str(envelope.get("schema_version") or envelope.get("version") or "") or None
        return str(row.get("schema_version") or row.get("execution_version") or row.get("decision_version") or row.get("governance_version") or row.get("version") or "") or None

    @staticmethod
    def _ownership_checks(record: Any, decision: Any, outcome: Any, execution: Any, proposal: Any, hypothesis: Any, evidence: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, bool]:
        checks = {
            "governance_decision": bool(decision and record.decision_id == decision.decision_id),
            "decision_outcome": bool(decision and outcome and decision.outcome_id == outcome.outcome_id),
            "decision_execution": bool(decision and execution and decision.execution_id == execution.execution_id),
            "decision_proposal": bool(decision and proposal and decision.proposal_id == proposal.proposal_id),
            "proposal_hypothesis": bool(proposal and hypothesis and proposal.hypothesis_id == (getattr(hypothesis, "hypothesis_id", None) or (hypothesis.get("hypothesis_id") if isinstance(hypothesis, Mapping) else None))),
            "evidence_present": bool(evidence),
            "observations_present": bool(observations),
            "governance_outcome": bool(outcome and record.outcome_id == outcome.outcome_id),
        }
        if outcome and execution:
            checks["outcome_execution"] = outcome.execution_id == execution.execution_id
            checks["outcome_proposal"] = outcome.proposal_id == execution.proposal_id
        if execution and proposal:
            checks["execution_proposal"] = execution.proposal_id == proposal.proposal_id
        return checks

    @staticmethod
    def _security_checks(records: dict[str, list[dict[str, Any]]]) -> dict[str, bool]:
        text = json.dumps(records, ensure_ascii=False)
        return {"no_secret_markers": not _SECRET.search(text), "no_raw_payload_key": "raw_payload" not in text}

    @staticmethod
    def _idempotency_checks(records: dict[str, list[dict[str, Any]]]) -> dict[str, bool]:
        keys = []
        for rows in records.values():
            for row in rows:
                key = row.get("idempotency_key")
                if key:
                    keys.append(key)
        return {"all_present": bool(keys) and len(keys) == len(set(keys)), "stable_chain_keys": len(keys) == len(set(keys))}

    @staticmethod
    def _causality_checks(records: dict[str, list[dict[str, Any]]]) -> dict[str, bool]:
        text = json.dumps(records, ensure_ascii=False)
        statuses = []
        for rows in records.values():
            statuses.extend(row.get("causality_status") for row in rows if "causality_status" in row)
        return {"all_not_claimed": bool(statuses) and all(status == "not_claimed" for status in statuses), "no_causal_language": not _CAUSAL.search(text)}

    @staticmethod
    def _governance_checks(record: C2GovernanceRecord) -> dict[str, bool]:
        return {"known_status": record.governance_status in {"eligible", "approved_for_future_action", "blocked", "rejected", "requires_review"}, "not_execution_approval": record.safety_context.get("execution") is False, "no_production_action": record.safety_context.get("production_action") is False}

    @staticmethod
    def _duplicate_checks(records: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        seen: dict[str, str] = {}
        id_fields = {"evidence": "evidence_id", "hypothesis": "hypothesis_id", "proposal": "proposal_id", "execution": "execution_id", "observation": "observation_id", "outcome": "outcome_id", "decision": "decision_id", "governance": "governance_id"}
        errors = []
        for stage, rows in records.items():
            for row in rows:
                field = id_fields.get(stage, "record_id")
                rid = str(row.get(field) or row.get("record_id") or "")
                if not rid:
                    continue
                if rid in seen and seen[rid] != stage:
                    errors.append({"from": seen[rid], "to": stage, "reason": "duplicate_or_parallel_record_id", "record_id": rid})
                seen[rid] = stage
        return errors

    @staticmethod
    def _audit_id(records: dict[str, list[dict[str, Any]]], record: C2GovernanceRecord) -> str:
        ids = []
        for stage in sorted(records):
            for row in records[stage]:
                ids.append(str(row.get("record_id") or row.get("*_id") or row.get("decision_id") or row.get("governance_id") or row.get("hypothesis_id") or ""))
        raw = json.dumps({"governance_id": record.governance_id, "ids": sorted(ids), "versions": {stage: sorted(str(C2GovernanceAuditBoundary._version_of(row)) for row in rows) for stage, rows in records.items()}}, sort_keys=True, separators=(",", ":"))
        return "audit_c2_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        allowed = {"record_type", "schema_version", "audit_id", "audit_version", "status", "closure_ready", "closure_readiness", "governance_id", "stage_statuses", "records_by_stage", "resolved_edges", "missing_ids", "invalid_edges", "quality_warnings", "gate_results", "version_results", "ownership_results", "security_results", "idempotency_results", "causality_results", "governance_results", "provenance", "decision_id", "decision_version", "outcome_id", "execution_id", "proposal_id", "hypothesis_id", "governance_status", "decision_classification", "policy_id", "policy_version", "idempotency_key", "causality_status", "source", "mode", "execution", "production_action", "knowledge_mutation", "strategy_mutation", "record_id", "record_type"}
        return {str(k): _sanitize(v, str(k)) for k, v in value.items() if str(k) in allowed}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str) and _SECRET.search(value):
        return "[REDACTED]"
    return value


__all__ = ["C2AuditReport", "C2GovernanceAuditBoundary"]
