"""C2-P7 Outcome -> Decision Boundary tests."""

import pytest

from mindmargin.intelligence.c2_decisions import C2OutcomeDecisionBoundary
from mindmargin.intelligence.contracts import ExperimentResult
from tests.unit.intelligence.test_c2_observation_outcome import make_execution, observe
from mindmargin.intelligence.c2_observation_outcome import C2ExperimentObservationOutcomeBoundary


def make_outcome(tmp_path, *, result_value="production.completed", sample=10):
    store, executions, execution = make_execution(tmp_path)
    outcomes = C2ExperimentObservationOutcomeBoundary(executions)
    observation = observe(outcomes, execution, value=result_value, sample=sample)
    outcome = outcomes.evaluate_outcome(execution, [observation.observation_id])
    return store, outcomes, execution, observation, outcome


def test_valid_decision_over_real_p6_outcome(tmp_path):
    _, outcomes, execution, observation, outcome = make_outcome(tmp_path)
    boundary = C2OutcomeDecisionBoundary(outcomes)
    decision = boundary.decide(outcome)
    assert decision.decision_classification == "supported"
    assert decision.causality_status == "not_claimed"
    assert decision.outcome_id == outcome.outcome_id
    assert observation.observation_id in decision.observation_ids
    assert boundary.lineage_view(decision.decision_id)["status"] == "complete"


def test_missing_or_incomplete_outcome_rejected(tmp_path):
    _, outcomes, _, _, outcome = make_outcome(tmp_path)
    boundary = C2OutcomeDecisionBoundary(outcomes)
    with pytest.raises(ValueError, match="outcome_not_found"):
        boundary.decide("missing-outcome")
    outcomes._outcomes.pop(outcome.outcome_id)
    with pytest.raises(ValueError, match="outcome_not_found"):
        boundary.decide(outcome)


def test_classification_protection_for_failure_inconclusive_and_insufficient(tmp_path):
    _, outcomes, _, _, failure = make_outcome(tmp_path, result_value="other")
    boundary = C2OutcomeDecisionBoundary(outcomes)
    assert boundary.decide(failure).decision_classification == "rejected"

    _, outcomes2, _, _, inconclusive = make_outcome(tmp_path / "inconclusive", result_value="insufficient_data")
    boundary2 = C2OutcomeDecisionBoundary(outcomes2)
    assert boundary2.decide(inconclusive).decision_classification == "inconclusive"

    _, outcomes3, _, _, insufficient = make_outcome(tmp_path / "insufficient", sample=1)
    boundary3 = C2OutcomeDecisionBoundary(outcomes3)
    assert boundary3.decide(insufficient).decision_classification == "insufficient_evidence"


def test_rationale_must_be_lineage_backed_and_non_causal(tmp_path):
    _, outcomes, _, observation, outcome = make_outcome(tmp_path)
    boundary = C2OutcomeDecisionBoundary(outcomes)
    with pytest.raises(ValueError, match="rationale_source_not_in_lineage"):
        boundary.decide(outcome, rationale={"summary": "supported by facts", "source_ids": ["fabricated"]})
    with pytest.raises(ValueError, match="rationale_causal_claim_rejected"):
        boundary.decide(outcome, rationale={"summary": "This proves causality", "source_ids": [observation.observation_id]})


def test_deterministic_identity_and_duplicate_prevention(tmp_path):
    _, outcomes, _, _, outcome = make_outcome(tmp_path)
    boundary = C2OutcomeDecisionBoundary(outcomes)
    first = boundary.decide(outcome)
    assert first.idempotency_key.startswith("decision:")
    with pytest.raises(ValueError, match="duplicate_decision_idempotency_key"):
        boundary.decide(outcome)


def test_invalid_lineage_and_provenance_rejected(tmp_path):
    _, outcomes, _, observation, outcome = make_outcome(tmp_path)
    boundary = C2OutcomeDecisionBoundary(outcomes)
    outcomes._observations.pop(observation.observation_id)
    with pytest.raises(ValueError, match="outcome_lineage"):
        boundary.decide(outcome)


def test_security_redaction_and_no_mutation_or_production_hooks(tmp_path):
    store, outcomes, _, _, outcome = make_outcome(tmp_path)
    boundary = C2OutcomeDecisionBoundary(outcomes)
    before = store.ledger.read()
    decision = boundary.decide(outcome, rationale={"summary": "Rule-based result from measured outcome", "source_ids": [outcome.outcome_id], "metadata": {"api_key": "secret"}})
    payload = decision.to_dict()
    assert "secret" not in str(payload)
    assert "api_key" not in str(payload)
    assert store.ledger.read() == before
    assert not hasattr(boundary, "publish")
    assert not hasattr(boundary, "schedule")
    assert not hasattr(boundary, "execute")
    assert not hasattr(boundary, "write_knowledge")
    assert not hasattr(boundary, "update_strategy")


def test_legacy_experiment_result_unchanged():
    legacy = ExperimentResult.create(hypothesis="legacy", variable="v")
    assert legacy.hypothesis == "legacy"
