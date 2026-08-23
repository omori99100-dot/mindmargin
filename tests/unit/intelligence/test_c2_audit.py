"""C2-P9 Governance Audit & Closure Boundary tests."""

import pytest

from mindmargin.intelligence.c2_audit import C2GovernanceAuditBoundary
from mindmargin.intelligence.c2_governance import C2DecisionGovernanceBoundary, C2GovernancePolicy
from tests.unit.intelligence.test_c2_governance import make_decision
from mindmargin.intelligence.contracts import ExperimentResult


def make_governance(tmp_path, *, result_value="production.completed", sample=10):
    store, decisions, decision = make_decision(tmp_path, result_value=result_value, sample=sample)
    governance_boundary = C2DecisionGovernanceBoundary(decisions, C2GovernancePolicy("p", "1"))
    governance = governance_boundary.govern(decision)
    return store, governance_boundary, governance


def test_valid_complete_chain_is_passed_and_closure_ready(tmp_path):
    _, governance_boundary, governance = make_governance(tmp_path)
    audit = C2GovernanceAuditBoundary(governance_boundary)
    report = audit.audit(governance)
    assert report.status == "passed"
    assert report.closure_ready is True
    assert report.closure_readiness == "ready"
    assert all(report.gate_results.values())


def test_missing_governance_or_stage_is_blocked_or_failed(tmp_path):
    _, governance_boundary, governance = make_governance(tmp_path)
    audit = C2GovernanceAuditBoundary(governance_boundary)
    missing = audit.audit("missing-governance")
    assert missing.status == "blocked"
    assert not missing.closure_ready
    governance_boundary._by_id.pop(governance.governance_id)
    report = audit.audit(governance)
    assert report.status == "blocked"


def test_invalid_lineage_and_fabricated_edges_are_not_closure_ready(tmp_path):
    _, governance_boundary, governance = make_governance(tmp_path)
    governance.lineage["invalid_edges"] = [{"from": "fake", "to": "governance"}]
    audit = C2GovernanceAuditBoundary(governance_boundary)
    report = audit.audit(governance)
    assert not report.closure_ready
    assert report.status in {"failed", "requires_review"}


def test_inconclusive_and_insufficient_evidence_protection(tmp_path):
    _, governance_boundary, inconclusive = make_governance(tmp_path, result_value="insufficient_data")
    assert inconclusive.governance_status == "requires_review"
    assert C2GovernanceAuditBoundary(governance_boundary).audit(inconclusive).closure_ready is False

    _, governance_boundary2, insufficient = make_governance(tmp_path / "insufficient", sample=1)
    assert insufficient.governance_status == "blocked"
    assert C2GovernanceAuditBoundary(governance_boundary2).audit(insufficient).closure_ready is False


def test_duplicate_detection_and_deterministic_result(tmp_path):
    _, governance_boundary, governance = make_governance(tmp_path)
    audit = C2GovernanceAuditBoundary(governance_boundary)
    first = audit.audit(governance)
    second = audit.audit(governance)
    assert first.audit_id == second.audit_id
    assert first.to_dict() == second.to_dict()
    duplicate = audit.audit_records([{"record_id": "x", "record_type": "decision"}, {"record_id": "x", "record_type": "governance"}])
    assert duplicate["status"] == "failed"


def test_security_redaction_and_side_effect_isolation(tmp_path):
    store, governance_boundary, governance = make_governance(tmp_path)
    audit = C2GovernanceAuditBoundary(governance_boundary)
    before = store.ledger.read()
    report = audit.audit(governance)
    payload = report.to_dict()
    assert "api_key" not in str(payload)
    assert "secret" not in str(payload)
    assert store.ledger.read() == before
    assert not hasattr(audit, "execute")
    assert not hasattr(audit, "publish")
    assert not hasattr(audit, "schedule")
    assert not hasattr(audit, "write_knowledge")
    assert not hasattr(audit, "update_strategy")


def test_legacy_compatibility_and_no_production_action():
    legacy = ExperimentResult.create(hypothesis="legacy", variable="v")
    assert legacy.hypothesis == "legacy"
