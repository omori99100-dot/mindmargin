"""C2-P8 Decision Governance Boundary tests."""

import pytest

from mindmargin.intelligence.c2_decisions import C2OutcomeDecisionBoundary
from mindmargin.intelligence.c2_governance import C2DecisionGovernanceBoundary, C2GovernancePolicy
from tests.unit.intelligence.test_c2_decisions import make_outcome
from mindmargin.intelligence.contracts import ExperimentResult


def make_decision(tmp_path, *, result_value="production.completed", sample=10):
    store, outcomes, execution, observation, outcome = make_outcome(tmp_path, result_value=result_value, sample=sample)
    decisions = C2OutcomeDecisionBoundary(outcomes)
    decision = decisions.decide(outcome)
    return store, decisions, decision


def test_valid_governed_decision(tmp_path):
    _, decisions, decision = make_decision(tmp_path)
    policy = C2GovernancePolicy(policy_id="default-governance", policy_version="1")
    boundary = C2DecisionGovernanceBoundary(decisions, policy)
    governance = boundary.govern(decision)
    assert governance.governance_status == "approved_for_future_action"
    assert governance.causality_status == "not_claimed"
    assert boundary.lineage_view(governance.governance_id)["status"] == "complete"


def test_missing_invalid_and_fabricated_decision_rejected(tmp_path):
    _, decisions, decision = make_decision(tmp_path)
    boundary = C2DecisionGovernanceBoundary(decisions, C2GovernancePolicy("p", "1"))
    missing = boundary.evaluate("missing")
    assert not missing.valid and missing.status == "rejected"
    with pytest.raises(ValueError, match="decision_not_found"):
        boundary.govern("missing")
    decisions._by_id.pop(decision.decision_id)
    assert not boundary.evaluate(decision).valid


def test_inconclusive_and_insufficient_evidence_are_not_substantive_approval(tmp_path):
    _, decisions, inconclusive = make_decision(tmp_path, result_value="insufficient_data")
    boundary = C2DecisionGovernanceBoundary(decisions, C2GovernancePolicy("p", "1"))
    gov = boundary.govern(inconclusive)
    assert gov.governance_status == "requires_review"

    _, decisions2, insufficient = make_decision(tmp_path / "insufficient", sample=1)
    boundary2 = C2DecisionGovernanceBoundary(decisions2, C2GovernancePolicy("p", "1"))
    gov2 = boundary2.govern(insufficient)
    assert gov2.governance_status == "blocked"


def test_policy_validation_and_classification_protection(tmp_path):
    with pytest.raises(ValueError, match="policy classifications"):
        C2GovernancePolicy("p", "1", allowed_classifications=("unknown",))
    _, decisions, decision = make_decision(tmp_path)
    boundary = C2DecisionGovernanceBoundary(decisions, C2GovernancePolicy("p", "1", allowed_classifications=("inconclusive",), approve_classifications=()))
    validation = boundary.evaluate(decision)
    assert not validation.valid
    assert "classification_not_allowed_by_policy" in validation.errors


def test_duplicate_idempotency_and_deterministic_identity(tmp_path):
    _, decisions, decision = make_decision(tmp_path)
    boundary = C2DecisionGovernanceBoundary(decisions, C2GovernancePolicy("p", "1"))
    first = boundary.govern(decision)
    assert first.idempotency_key.startswith("governance:")
    with pytest.raises(ValueError, match="duplicate_governance_idempotency_key"):
        boundary.govern(decision)


def test_causal_and_lineage_tampering_rejected(tmp_path):
    _, decisions, decision = make_decision(tmp_path)
    with pytest.raises(ValueError, match="non-causal"):
        decision.__class__(**{**decision.__dict__, "causality_status": "claimed"})
    boundary = C2DecisionGovernanceBoundary(decisions, C2GovernancePolicy("p", "1"))
    validation = boundary.evaluate(decision)
    assert validation.valid
    assert validation.status == "approved_for_future_action"


def test_security_no_persistence_no_execution_and_legacy_compatibility(tmp_path):
    store, decisions, decision = make_decision(tmp_path)
    boundary = C2DecisionGovernanceBoundary(decisions, C2GovernancePolicy("p", "1", audit_metadata={"api_key": "secret"}))
    before = store.ledger.read()
    governance = boundary.govern(decision)
    payload = governance.to_dict()
    assert "secret" not in str(payload)
    assert "api_key" not in str(payload)
    assert store.ledger.read() == before
    assert not hasattr(boundary, "execute")
    assert not hasattr(boundary, "publish")
    assert not hasattr(boundary, "schedule")
    assert not hasattr(boundary, "write_knowledge")
    assert not hasattr(boundary, "update_strategy")
    legacy = ExperimentResult.create(hypothesis="legacy", variable="v")
    assert legacy.hypothesis == "legacy"
