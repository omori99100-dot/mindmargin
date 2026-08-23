"""C2-P6 observation and outcome boundary tests."""

import pytest

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector
from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess
from mindmargin.intelligence.c2_contracts import C2ConfidenceValue
from mindmargin.intelligence.c2_execution import C2ExperimentExecutionBoundary
from mindmargin.intelligence.c2_hypothesis import C2HypothesisRegistry
from mindmargin.intelligence.c2_observation_outcome import C2ExperimentObservationOutcomeBoundary
from mindmargin.intelligence.c2_proposals import C2ExperimentProposalBoundary
from mindmargin.intelligence.contracts import DecisionRecord, DecisionStore, ExperimentResult, PipelineEvent
from mindmargin.intelligence.metric_registry import MetricRegistry


def make_execution(tmp_path):
    store = DecisionStore(tmp_path / "p6.jsonl")
    decision = store.save_decision(DecisionRecord.create("topic_selection", pipeline_id="p-p6", video_id="v-p6", correlation_id="corr-p6"))
    event = store.save_event(PipelineEvent.create("production.completed", "p-p6", decision_id=decision["decision_id"], video_id="v-p6", correlation_id="corr-p6", source="phase_b"))
    source_observation = ObservationCollector(store).collect_from_event(event["event_id"], metric_name="lifecycle_status", observation_type="lifecycle_signal")
    evidence = EvidenceBuilder(store).build(
        observation_ids=[source_observation["record_id"]], source_artifacts={event["event_id"]: event}, source_record_ids=[event["event_id"]], parent_record_ids=[source_observation["record_id"]], metric_name="lifecycle_status", value="production.completed", source="phase_b", claim_scope="v-p6", pipeline_id="p-p6", video_id="v-p6", correlation_id="corr-p6", window_start=source_observation["window_start"], window_end=source_observation["window_end"], source_kind="phase_b_event",
    )
    access = C2ReadOnlyEvidenceAccess(store)
    hypotheses = C2HypothesisRegistry(access)
    confidence = C2ConfidenceValue(score=0.6, dimension="evidence_support", basis="provenance_based", limitations=("observational",))
    hypothesis = hypotheses.propose(
        statement="A bounded retention pattern may be testable in this scope.", supporting_evidence_ids=[evidence["record_id"]], measurable_prediction="Retention will increase by at least 5 percentage points.", falsification_condition="A result below 5 percentage points falsifies the hypothesis.", inconclusive_condition="Fewer than 10 comparable observations is inconclusive.", expected_direction="increase", confidence=confidence, limitations=({"scope": "single video"},), pipeline_id="p-p6", video_id="v-p6", correlation_id="corr-p6",
    )
    assert hypotheses.mark_testable(hypothesis).validation.valid
    proposals = C2ExperimentProposalBoundary(access, hypotheses, MetricRegistry())
    proposal = proposals.propose(
        hypothesis_id=hypothesis.hypothesis_id, supporting_evidence_ids=[evidence["record_id"]], decision_ids=[decision["decision_id"]], metric_name="lifecycle_status",
        variants=({"variant_id": "control", "role": "control", "description": "Current bounded behavior."}, {"variant_id": "treatment", "role": "treatment", "description": "Proposed bounded variation."}), population={"unit": "video", "scope": "same channel"}, eligibility={"rule": "same defined scope"}, minimum_sample=10,
        success_rule={"metric": "lifecycle_status", "operator": "eq", "threshold": "production.completed", "window": "24h"}, inconclusive_rule={"metric": "lifecycle_status", "operator": "eq", "threshold": "insufficient_data", "window": "24h"}, safety_constraints=({"condition": "error rate exceeds 5%", "action": "do not execute"},), rollback_criteria=({"criterion": "safety threshold breached", "action": "restore control"},), pipeline_id="p-p6", video_id="v-p6", correlation_id="corr-p6",
    )
    approved = proposals.approve(proposal)
    assert approved.proposal is not None
    executions = C2ExperimentExecutionBoundary(proposals)
    prepared = executions.prepare(approved.proposal)
    authorized = executions.authorize(prepared)
    execution = executions.execute(authorized)
    return store, executions, execution


def observe(boundary, execution, *, value="production.completed", sample=10, variant_id="control", timestamp="2026-08-20T12:00:00+00:00", start="2026-08-20T11:00:00+00:00", end="2026-08-20T13:00:00+00:00", provenance=None, population=None, eligibility=None):
    return boundary.observe(execution, variant={"variant_id": variant_id, "role": "control" if variant_id == "control" else "treatment", "description": "bounded"}, observation_timestamp=timestamp, window_start=start, window_end=end, sample_count=sample, metric_value=value, provenance=provenance if provenance is not None else {"source": "isolated measurement", "source_kind": "test"}, population=population, eligibility=eligibility)


def test_valid_observation_and_success_outcome(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    observation = observe(boundary, execution)
    outcome = boundary.evaluate_outcome(execution, [observation.observation_id])
    assert observation.execution_id == execution.execution_id
    assert outcome.result == "success"
    assert outcome.causality_status == "not_claimed"
    assert boundary.lineage_view(outcome.outcome_id)["status"] == "complete"


def test_unknown_execution_rejected(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    with pytest.raises(ValueError, match="execution_unknown"):
        observe(boundary, "missing-execution")


def test_invalid_variant_population_eligibility_and_window_rejected(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    with pytest.raises(ValueError, match="variant_not_in_execution"):
        observe(boundary, execution, variant_id="unknown")
    with pytest.raises(ValueError, match="population_mismatch"):
        observe(boundary, execution, population={"unit": "channel"})
    with pytest.raises(ValueError, match="eligibility_mismatch"):
        observe(boundary, execution, eligibility={"rule": "wrong"})
    with pytest.raises(ValueError, match="observation_window_invalid_or_outside"):
        observe(boundary, execution, timestamp="2026-08-20T14:00:00+00:00")


def test_missing_provenance_and_causal_claim_rejected(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    with pytest.raises(ValueError, match="provenance_missing"):
        observe(boundary, execution, provenance={})
    with pytest.raises(ValueError, match="causal_claim_rejected"):
        observe(boundary, execution, value="causal result")


def test_insufficient_sample_outcome(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    observation = observe(boundary, execution, sample=3)
    outcome = boundary.evaluate_outcome(execution, [observation.observation_id])
    assert outcome.result == "insufficient_sample"
    assert outcome.result_reason == "sample_count_below_proposal_minimum"


def test_failure_and_inconclusive_outcomes(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    failure_observation = observe(boundary, execution, value="other")
    failure = boundary.evaluate_outcome(execution, [failure_observation.observation_id])
    assert failure.result == "failure"

    _, executions2, execution2 = make_execution(tmp_path / "second")
    boundary2 = C2ExperimentObservationOutcomeBoundary(executions2)
    inconclusive_observation = observe(boundary2, execution2, value="insufficient_data")
    inconclusive = boundary2.evaluate_outcome(execution2, [inconclusive_observation.observation_id])
    assert inconclusive.result == "inconclusive"


def test_duplicate_observation_and_outcome_idempotency(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    kwargs = {"variant_id": "control", "timestamp": "2026-08-20T12:00:00+00:00"}
    first = observe(boundary, execution, **kwargs)
    with pytest.raises(ValueError, match="duplicate_observation_identity"):
        observe(boundary, execution, **kwargs)
    boundary.evaluate_outcome(execution, [first.observation_id])
    with pytest.raises(ValueError, match="duplicate_outcome_idempotency_key"):
        boundary.evaluate_outcome(execution, [first.observation_id])


def test_lineage_and_serialization_security(tmp_path):
    _, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    observation = observe(boundary, execution, provenance={"source": "safe", "metadata": {"api_key": "secret"}})
    outcome = boundary.evaluate_outcome(execution, [observation.observation_id])
    assert outcome.lineage["source_record_ids"] == [observation.observation_id]
    assert "secret" not in str(observation.to_dict())
    assert "api_key" not in str(observation.to_dict())
    assert boundary.lineage_view(outcome.outcome_id)["status"] == "complete"


def test_no_production_mutation_and_legacy_compatibility(tmp_path):
    store, executions, execution = make_execution(tmp_path)
    boundary = C2ExperimentObservationOutcomeBoundary(executions)
    before = store.ledger.read()
    observation = observe(boundary, execution)
    boundary.evaluate_outcome(execution, [observation.observation_id])
    assert store.ledger.read() == before
    assert not hasattr(boundary, "publish")
    assert not hasattr(boundary, "schedule")
    assert not hasattr(boundary, "write_knowledge")
    assert not hasattr(boundary, "update_strategy")
    legacy = ExperimentResult.create(hypothesis="legacy", variable="v")
    assert legacy.hypothesis == "legacy"
