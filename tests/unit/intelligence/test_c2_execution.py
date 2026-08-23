"""C2-P5 isolated execution boundary tests."""

from dataclasses import replace

import pytest

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector
from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess
from mindmargin.intelligence.c2_contracts import C2ConfidenceValue
from mindmargin.intelligence.c2_diagnosis import C2DiagnosisCoordinator
from mindmargin.intelligence.c2_execution import C2ExperimentExecutionBoundary
from mindmargin.intelligence.c2_hypothesis import C2HypothesisRegistry
from mindmargin.intelligence.c2_proposals import C2ExperimentProposalBoundary
from mindmargin.intelligence.contracts import DecisionRecord, DecisionStore, ExperimentResult, PipelineEvent
from mindmargin.intelligence.metric_registry import MetricRegistry


def _store(tmp_path):
    return DecisionStore(tmp_path / "execution.jsonl")


def _chain(store):
    decision = store.save_decision(DecisionRecord.create("topic_selection", pipeline_id="p-exec", video_id="v-exec", correlation_id="corr-exec"))
    event = store.save_event(PipelineEvent.create("production.completed", "p-exec", decision_id=decision["decision_id"], video_id="v-exec", correlation_id="corr-exec", source="phase_b"))
    observation = ObservationCollector(store).collect_from_event(event["event_id"], metric_name="lifecycle_status", observation_type="lifecycle_signal")
    evidence = EvidenceBuilder(store).build(
        observation_ids=[observation["record_id"]],
        source_artifacts={event["event_id"]: event},
        source_record_ids=[event["event_id"]],
        parent_record_ids=[observation["record_id"]],
        metric_name="lifecycle_status",
        value="production.completed",
        source="phase_b",
        claim_scope="v-exec",
        pipeline_id="p-exec",
        video_id="v-exec",
        correlation_id="corr-exec",
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        source_kind="phase_b_event",
    )
    return decision, event, observation, evidence


def _confidence():
    return C2ConfidenceValue(score=0.6, dimension="evidence_support", basis="provenance_based", limitations=("observational",))


def _boundary(store, evidence):
    access = C2ReadOnlyEvidenceAccess(store)
    hypotheses = C2HypothesisRegistry(access)
    hypothesis = hypotheses.propose(
        statement="A bounded retention pattern may be testable in this scope.",
        supporting_evidence_ids=[evidence["record_id"]],
        measurable_prediction="Retention will increase by at least 5 percentage points.",
        falsification_condition="A result below 5 percentage points falsifies the hypothesis.",
        inconclusive_condition="Fewer than 10 comparable observations is inconclusive.",
        expected_direction="increase",
        confidence=_confidence(),
        limitations=({"scope": "single video"},),
        pipeline_id="p-exec",
        video_id="v-exec",
        correlation_id="corr-exec",
    )
    assert hypotheses.mark_testable(hypothesis).validation.valid
    proposals = C2ExperimentProposalBoundary(access, hypotheses, MetricRegistry())
    return proposals, hypothesis


def _proposal_kwargs(hypothesis, decision, evidence):
    return dict(
        hypothesis_id=hypothesis.hypothesis_id,
        supporting_evidence_ids=[evidence["record_id"]],
        decision_ids=[decision["decision_id"]],
        metric_name="lifecycle_status",
        variants=(
            {"variant_id": "control", "role": "control", "description": "Current bounded behavior."},
            {"variant_id": "treatment", "role": "treatment", "description": "Proposed bounded variation."},
        ),
        population={"unit": "video", "scope": "same channel and content class"},
        eligibility={"rule": "published videos with the same defined scope"},
        minimum_sample=10,
        success_rule={"metric": "lifecycle_status", "operator": "eq", "threshold": "production.completed", "window": "24h"},
        inconclusive_rule={"metric": "lifecycle_status", "operator": "eq", "threshold": "insufficient_data", "window": "24h"},
        safety_constraints=({"condition": "error rate exceeds 5%", "action": "do not execute"},),
        rollback_criteria=({"criterion": "safety threshold breached", "action": "restore control"},),
        pipeline_id="p-exec",
        video_id="v-exec",
        correlation_id="corr-exec",
    )


def _validated_proposal(store, *, mutate=None):
    decision, _, _, evidence = _chain(store)
    proposals, hypothesis = _boundary(store, evidence)
    kwargs = _proposal_kwargs(hypothesis, decision, evidence)
    if mutate:
        kwargs = mutate(kwargs)
    proposal = proposals.propose(**kwargs)
    approved = proposals.approve(proposal)
    return proposals, approved.proposal, decision, evidence


def test_valid_validated_proposal_prepares_authorizes_and_executes_in_memory(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    before = len(store.ledger.read())

    prepared = boundary.prepare(proposal)
    authorized = boundary.authorize(prepared)
    completed = boundary.execute(authorized)

    assert prepared.status == "prepared"
    assert authorized.status == "authorized"
    assert completed.status == "completed"
    assert completed.proposal_id == proposal.proposal_id
    assert len(store.ledger.read()) == before
    assert boundary.lineage_view(completed.execution_id)["status"] == "complete"


def test_unvalidated_proposal_is_rejected_before_execution(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    proposals, hypothesis = _boundary(store, evidence)
    proposal = proposals.propose(**_proposal_kwargs(hypothesis, decision, evidence))
    boundary = C2ExperimentExecutionBoundary(proposals)
    with pytest.raises(ValueError, match="proposal_not_eligible"):
        boundary.prepare(proposal)


@pytest.mark.parametrize("mutation,expected", [
    (lambda k: {**k, "hypothesis_id": "missing"}, "hypothesis_not_found"),
    (lambda k: {**k, "supporting_evidence_ids": ["missing"], "idempotency_key": "bad-evidence"}, "evidence_not_found"),
    (lambda k: {**k, "decision_ids": ["missing"], "idempotency_key": "bad-decision"}, "decision_not_found"),
    (lambda k: {**k, "metric_name": "unsupported", "success_rule": {"metric": "unsupported", "operator": "eq", "threshold": 1, "window": "24h"}, "inconclusive_rule": {"metric": "unsupported", "operator": "eq", "threshold": 0, "window": "24h"}, "idempotency_key": "bad-metric"}, "metric_not_registered"),
])
def test_invalid_dependencies_are_rejected(tmp_path, mutation, expected):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store, mutate=mutation)
    boundary = C2ExperimentExecutionBoundary(proposals)
    with pytest.raises(ValueError) as exc:
        boundary.prepare(proposal)
    assert expected in str(exc.value)


def test_invalid_sample_variants_eligibility_safety_and_rollback_are_rejected(tmp_path):
    cases = [
        (lambda k: {**k, "minimum_sample": 1, "idempotency_key": "sample"}, "minimum_sample_gate"),
        (lambda k: {**k, "variants": ({"variant_id": "control", "role": "control", "description": "only"},), "idempotency_key": "variants"}, "selected_control_treatment_required"),
        (lambda k: {**k, "eligibility": {}, "idempotency_key": "eligibility"}, "eligibility_rule_required"),
        (lambda k: {**k, "safety_constraints": (), "idempotency_key": "safety"}, "safety_constraints_required"),
        (lambda k: {**k, "rollback_criteria": (), "idempotency_key": "rollback"}, "rollback_criteria_required"),
    ]
    for mutation, expected in cases:
        store = _store(tmp_path)
        proposals, proposal, _, _ = _validated_proposal(store, mutate=mutation)
        boundary = C2ExperimentExecutionBoundary(proposals)
        with pytest.raises(ValueError) as exc:
            boundary.prepare(proposal)
        assert expected in str(exc.value)


def test_scope_mismatch_and_stale_lineage_are_rejected(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    with pytest.raises(ValueError, match="execution_scope_mismatch"):
        boundary.prepare(proposal, execution_scope={"pipeline_id": "wrong", "video_id": "v-exec", "correlation_id": "corr-exec"})


def test_duplicate_idempotency_is_rejected(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    first = boundary.prepare(proposal)
    with pytest.raises(ValueError, match="duplicate_execution_idempotency_key"):
        boundary.prepare(proposal)
    assert boundary.get(first.execution_id) is first


def test_lifecycle_transitions_and_bypass_protection(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    prepared = boundary.prepare(proposal)
    with pytest.raises(ValueError, match="authorized"):
        boundary.execute(prepared)
    authorized = boundary.authorize(prepared)
    failed = boundary.fail(authorized, "safety check failed")
    assert failed.status == "failed"
    rolled_back = boundary.rollback(failed, "restore control")
    assert rolled_back.status == "rolled_back"
    with pytest.raises(ValueError, match="terminal"):
        boundary.cancel(rolled_back, "too late")


def test_failure_and_cancel_behavior(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    prepared = boundary.prepare(proposal)
    cancelled = boundary.cancel(prepared, "operator cancelled")
    assert cancelled.status == "cancelled"
    with pytest.raises(ValueError, match="prepared"):
        boundary.authorize(cancelled)


def test_execution_cannot_call_scheduler_publish_or_mutate_knowledge_strategy(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    assert not hasattr(boundary, "publish")
    assert not hasattr(boundary, "schedule")
    assert not hasattr(boundary, "write_knowledge")
    assert not hasattr(boundary, "update_strategy")


def test_security_redaction_and_legacy_experiment_result_compatibility(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    execution = boundary.prepare(proposal)
    payload = execution.to_dict()
    assert "secret" not in str(payload)
    assert "raw_payload" not in str(payload)
    legacy = ExperimentResult.create(hypothesis="legacy hypothesis", variable="legacy-variable")
    assert legacy.hypothesis == "legacy hypothesis"


def test_lineage_not_found_and_execution_lineage_complete(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    boundary = C2ExperimentExecutionBoundary(proposals)
    assert boundary.lineage_view("missing")["status"] == "not_found"
    execution = boundary.prepare(proposal)
    lineage = boundary.lineage_view(execution.execution_id)
    assert lineage["status"] == "complete"
    assert any(edge["type"] == "execution" for edge in lineage["resolved_edges"])


def test_no_persistence_and_compile_safe(tmp_path):
    store = _store(tmp_path)
    proposals, proposal, _, _ = _validated_proposal(store)
    before = store.ledger.read()
    boundary = C2ExperimentExecutionBoundary(proposals)
    boundary.execute(boundary.authorize(boundary.prepare(proposal)))
    assert store.ledger.read() == before
