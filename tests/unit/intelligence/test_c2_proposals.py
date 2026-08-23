"""C2-P4 proposal boundary tests over real P0-P3 components."""

import pytest

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector
from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess, LineageScope
from mindmargin.intelligence.c2_contracts import C2ConfidenceValue
from mindmargin.intelligence.c2_hypothesis import C2HypothesisRegistry
from mindmargin.intelligence.c2_proposals import C2ExperimentProposalBoundary
from mindmargin.intelligence.contracts import DecisionRecord, DecisionStore, PipelineEvent
from mindmargin.intelligence.metric_registry import MetricRegistry


def _store(tmp_path):
    return DecisionStore(tmp_path / "proposal.jsonl")


def _chain(store):
    decision = store.save_decision(DecisionRecord.create("topic_selection", pipeline_id="p-prop", video_id="v-prop", correlation_id="corr-prop"))
    event = store.save_event(PipelineEvent.create("production.completed", "p-prop", decision_id=decision["decision_id"], video_id="v-prop", correlation_id="corr-prop", source="phase_b"))
    observation = ObservationCollector(store).collect_from_event(event["event_id"], metric_name="lifecycle_status", observation_type="lifecycle_signal")
    evidence = EvidenceBuilder(store).build(
        observation_ids=[observation["record_id"]],
        source_artifacts={event["event_id"]: event},
        source_record_ids=[event["event_id"]],
        parent_record_ids=[observation["record_id"]],
        metric_name="lifecycle_status",
        value="production.completed",
        source="phase_b",
        claim_scope="v-prop",
        pipeline_id="p-prop",
        video_id="v-prop",
        correlation_id="corr-prop",
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        source_kind="phase_b_event",
    )
    return decision, event, observation, evidence


def _confidence():
    return C2ConfidenceValue(score=0.6, dimension="evidence_support", basis="provenance_based", limitations=("observational",))


def _boundary(store, evidence):
    access = C2ReadOnlyEvidenceAccess(store)
    registry = C2HypothesisRegistry(access)
    hypothesis = registry.propose(
        statement="Within this bounded scope, a measurable retention pattern may be testable.",
        supporting_evidence_ids=[evidence["record_id"]],
        measurable_prediction="Retention will increase by at least 5 percentage points.",
        falsification_condition="A result below 5 percentage points falsifies the hypothesis.",
        inconclusive_condition="Fewer than 10 comparable observations is inconclusive.",
        expected_direction="increase",
        confidence=_confidence(),
        limitations=({"scope": "single video"},),
        pipeline_id="p-prop",
        video_id="v-prop",
        correlation_id="corr-prop",
    )
    assert registry.mark_testable(hypothesis).validation.valid
    return C2ExperimentProposalBoundary(access, registry, MetricRegistry()), hypothesis


def _kwargs(hypothesis, decision, evidence):
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
        pipeline_id="p-prop",
        video_id="v-prop",
        correlation_id="corr-prop",
    )


def test_valid_proposal_validates_without_execution(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    before = len(store.ledger.read())

    proposal = boundary.propose(**_kwargs(hypothesis, decision, evidence))
    outcome = boundary.approve(proposal)

    assert outcome.validation.valid
    assert outcome.proposal.status == "validated"
    assert outcome.proposal.metric_name == "lifecycle_status"
    assert len(store.ledger.read()) == before
    assert not hasattr(boundary, "execute")
    assert not hasattr(boundary, "schedule")


@pytest.mark.parametrize("field", ["hypothesis_id", "supporting_evidence_ids", "decision_ids", "metric_name"])
def test_missing_required_links_reject_at_contract_boundary(tmp_path, field):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    kwargs = _kwargs(hypothesis, decision, evidence)
    kwargs[field] = "" if field in {"hypothesis_id", "metric_name"} else []
    with pytest.raises(ValueError, match="required"):
        boundary.propose(**kwargs)


def test_insufficient_minimum_sample_rejects(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    kwargs = _kwargs(hypothesis, decision, evidence)
    kwargs["minimum_sample"] = 1
    result = boundary.validate(boundary.propose(**{**kwargs, "idempotency_key": "sample-low"}))
    assert not result.valid
    assert "minimum_sample_gate_too_low" in result.errors


def test_missing_rules_safety_rollback_and_invalid_variants_reject(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    base = _kwargs(hypothesis, decision, evidence)
    cases = [
        ({"success_rule": {}}, "success_rule_required"),
        ({"inconclusive_rule": {}}, "inconclusive_rule_required"),
        ({"safety_constraints": ()}, "safety_constraints_required"),
        ({"rollback_criteria": ()}, "rollback_criteria_required"),
        ({"variants": ({"variant_id": "only", "role": "control", "description": "one"},)}, "at_least_two_variants_required"),
        ({"variants": ({"variant_id": "a", "role": "control", "description": "a"}, {"variant_id": "b", "role": "control", "description": "b"})}, "control_and_treatment_required"),
    ]
    for update, expected in cases:
        proposal = boundary.propose(**{**base, **update, "idempotency_key": expected})
        result = boundary.validate(proposal)
        assert not result.valid
        assert expected in result.errors


def test_scope_lineage_mismatch_rejects(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    proposal = boundary.propose(**{**_kwargs(hypothesis, decision, evidence), "pipeline_id": "wrong", "idempotency_key": "wrong-scope"})
    result = boundary.validate(proposal)
    assert not result.valid
    assert any("scope_mismatch" in error or "lineage_not_complete" in error for error in result.errors)


def test_causal_claim_rejects(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    proposal = boundary.propose(**{**_kwargs(hypothesis, decision, evidence), "idempotency_key": "causal"})
    proposal = proposal.__class__(**{**proposal.__dict__, "success_rule": {"metric": "lifecycle_status", "operator": "eq", "threshold": "x caused y", "window": "24h"}})
    result = boundary.validate(proposal)
    assert not result.valid
    assert "proposal_causal_language" in result.errors


def test_security_redaction_and_legacy_experiment_compatibility(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    kwargs = _kwargs(hypothesis, decision, evidence)
    kwargs["eligibility"] = {"rule": "safe", "api_key": "secret", "raw_payload": {"authorization": "Bearer token"}}
    proposal = boundary.propose(**{**kwargs, "idempotency_key": "security"})
    payload = proposal.to_dict()
    assert "secret" not in str(payload)
    assert "Bearer token" not in str(payload)
    assert "raw_payload" not in str(payload)
    assert payload["envelope"]["source"] == "c2.p4.proposal_boundary"


def test_idempotency_same_inputs_same_proposal_and_distinct_prediction_rule_is_distinct(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    base = _kwargs(hypothesis, decision, evidence)
    first = boundary.propose(**base)
    second = boundary.propose(**base)
    third = boundary.propose(**{**base, "success_rule": {"metric": "lifecycle_status", "operator": "eq", "threshold": "other", "window": "24h"}})
    assert first.proposal_id == second.proposal_id
    assert first.proposal_id != third.proposal_id


def test_lineage_complete_partial_not_found_and_no_execution(tmp_path):
    store = _store(tmp_path)
    decision, _, _, evidence = _chain(store)
    boundary, hypothesis = _boundary(store, evidence)
    proposal = boundary.propose(**_kwargs(hypothesis, decision, evidence))
    complete = boundary.get_lineage(proposal.proposal_id)
    assert complete["status"] == "complete"
    assert complete["resolved_edges"]
    assert boundary.get_lineage("missing")["status"] == "not_found"
    partial = boundary.get_lineage(boundary.propose(**{**_kwargs(hypothesis, decision, evidence), "decision_ids": ["missing-decision"], "idempotency_key": "partial"}).proposal_id)
    assert partial["status"] == "partial"
    assert "missing-decision" in partial["missing_ids"]
