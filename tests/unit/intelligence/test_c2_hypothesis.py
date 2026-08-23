"""C2-P3 Hypothesis Registry tests over P0/P1/P2 and real JSONL."""

import pytest

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector
from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess, LineageScope
from mindmargin.intelligence.c2_contracts import C2ConfidenceValue, C2HypothesisRecord
from mindmargin.intelligence.c2_diagnosis import C2DiagnosisCoordinator
from mindmargin.intelligence.c2_hypothesis import C2HypothesisRegistry
from mindmargin.intelligence.contracts import DecisionRecord, DecisionStore, EvidenceRecord, ExperimentResult, ObservationRecord, PipelineEvent


def _store(tmp_path):
    return DecisionStore(tmp_path / "hypothesis.jsonl")


def _chain(store, pipeline="p-hyp", video="v-hyp", correlation="corr-hyp"):
    decision = store.save_decision(DecisionRecord.create("topic_selection", pipeline_id=pipeline, video_id=video, correlation_id=correlation))
    event = store.save_event(PipelineEvent.create("production.completed", pipeline, decision_id=decision["decision_id"], video_id=video, correlation_id=correlation, source="phase_b"))
    observation = ObservationCollector(store).collect_from_event(event["event_id"], metric_name="lifecycle_status", observation_type="lifecycle_signal")
    evidence = EvidenceBuilder(store).build(
        observation_ids=[observation["record_id"]],
        source_artifacts={event["event_id"]: event},
        source_record_ids=[event["event_id"]],
        parent_record_ids=[observation["record_id"]],
        metric_name="lifecycle_status",
        value="production.completed",
        source="phase_b",
        claim_scope=video,
        pipeline_id=pipeline,
        video_id=video,
        correlation_id=correlation,
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        source_kind="phase_b_event",
    )
    return decision, event, observation, evidence


def _confidence():
    return C2ConfidenceValue(score=0.65, dimension="evidence_support", basis="provenance_based", limitations=("observational",))


def _registry(store):
    return C2HypothesisRegistry(C2ReadOnlyEvidenceAccess(store))


def _valid_kwargs(evidence_id):
    return dict(
        statement="Within this bounded video scope, the observed pattern may be consistent with a measurable retention shift.",
        supporting_evidence_ids=[evidence_id],
        measurable_prediction="Retention at 3 seconds will increase by at least 5 percentage points in the next comparable observation window.",
        falsification_condition="If the measured 3-second retention change is below 5 percentage points in the defined window, the hypothesis is falsified.",
        inconclusive_condition="If fewer than 10 comparable observations are available, the result is inconclusive rather than rejected.",
        expected_direction="increase",
        confidence=_confidence(),
        limitations=({"scope": "single video", "data": "observational"},),
        pipeline_id="p-hyp",
        video_id="v-hyp",
        correlation_id="corr-hyp",
    )


def _validated_diagnosis(store):
    _, _, _, evidence = _chain(store)
    diagnosis = C2DiagnosisCoordinator(C2ReadOnlyEvidenceAccess(store)).diagnose_for_lineage(
        scope=LineageScope(pipeline_id="p-hyp", video_id="v-hyp", correlation_id="corr-hyp"),
        problem_statement="A bounded operational pattern requires a testable interpretation.",
        confidence=_confidence(),
        candidate_explanations=({"label": "pattern", "text": "The pattern is consistent with a bounded operational issue.", "evidence_ids": [evidence["record_id"]]},),
        limitations=({"scope": "single video"},),
    )
    assert diagnosis.record is not None and diagnosis.validation.valid
    return diagnosis.record, evidence


def test_valid_evidence_produces_testable_hypothesis(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)

    record = registry.propose(**_valid_kwargs(evidence["record_id"]))
    outcome = registry.mark_testable(record)

    assert outcome.validation.valid
    assert outcome.validation.status == "testable"
    assert outcome.record is not None
    assert outcome.record.status == "testable"
    assert outcome.record.causality_status == "not_claimed"


def test_validated_diagnosis_is_required_and_linked(tmp_path):
    store = _store(tmp_path)
    diagnosis, evidence = _validated_diagnosis(store)
    registry = _registry(store)

    outcome = registry.register_from_diagnosis(
        diagnosis,
        statement="The diagnosed pattern may predict a measurable retention change within this scope.",
        measurable_prediction="3-second retention will increase by at least 5 percentage points.",
        falsification_condition="A change below 5 percentage points falsifies this claim.",
        inconclusive_condition="Fewer than 10 comparable observations is inconclusive.",
        expected_direction="increase",
        confidence=_confidence(),
        limitations=({"scope": "single video"},),
    )

    assert outcome.validation.valid
    assert outcome.record.diagnosis_ids == (diagnosis.diagnosis_id,)
    assert outcome.record.supporting_evidence_ids == (evidence["record_id"],)


def test_missing_invalid_stale_or_unprovenance_evidence_rejects(tmp_path):
    store = _store(tmp_path)
    registry = _registry(store)
    record = registry.propose(**_valid_kwargs("missing-evidence"))

    outcome = registry.mark_testable(record)

    assert not outcome.validation.valid
    assert outcome.validation.status == "rejected"
    assert "evidence_not_found:missing-evidence" in outcome.validation.errors


def test_invalid_stale_and_missing_provenance_evidence_rejects(tmp_path):
    store = _store(tmp_path)
    _, event, observation, _ = _chain(store)
    stale_observation = ObservationRecord.create(
        metric_name="lifecycle_status",
        subject_id="v-hyp",
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        observed_value="production.completed",
        pipeline_id="p-hyp",
        video_id="v-hyp",
        correlation_id="corr-hyp",
        source="phase_b",
        source_kind="phase_b_event",
        quality="stale",
        freshness_seconds=None,
        source_record_ids=[event["event_id"]],
    )
    stale_row = store.save_observation(stale_observation)
    stale_evidence = EvidenceRecord.create(
        observation_ids=[stale_row["record_id"]],
        source_artifact_ids=[event["event_id"]],
        metric_name="lifecycle_status",
        value="production.completed",
        pipeline_id="p-hyp",
        video_id="v-hyp",
        correlation_id="corr-hyp",
        parent_record_ids=[stale_row["record_id"]],
        source_record_ids=[event["event_id"]],
        source="phase_b",
        validation_status="valid",
        status="validated",
        provenance={"source_kind": "phase_b_event"},
    )
    stale_evidence_row = store.save_evidence(stale_evidence)
    invalid_evidence = EvidenceRecord.create(
        observation_ids=[observation["record_id"]],
        source_artifact_ids=[event["event_id"]],
        metric_name="lifecycle_status",
        value="production.completed",
        pipeline_id="p-hyp",
        video_id="v-hyp",
        correlation_id="corr-hyp",
        parent_record_ids=[observation["record_id"]],
        source_record_ids=[event["event_id"]],
        source="phase_b",
        validation_status="invalid",
        status="rejected",
        provenance={},
    )
    invalid_row = store.save_evidence(invalid_evidence)
    registry = _registry(store)

    for evidence_id in (stale_evidence_row["record_id"], invalid_row["record_id"]):
        outcome = registry.mark_testable(registry.propose(**{**_valid_kwargs(evidence_id), "idempotency_key": "edge-" + evidence_id}))
        assert not outcome.validation.valid
        assert outcome.validation.status == "rejected"


def test_diagnosis_scope_mismatch_rejects(tmp_path):
    store = _store(tmp_path)
    diagnosis, evidence = _validated_diagnosis(store)
    registry = _registry(store)
    kwargs = _valid_kwargs(evidence["record_id"])
    kwargs["diagnosis_ids"] = (diagnosis.diagnosis_id,)
    kwargs["pipeline_id"] = "wrong-pipeline"
    record = registry.propose(**kwargs)

    outcome = registry.mark_testable(record, diagnoses={diagnosis.diagnosis_id: diagnosis})

    assert not outcome.validation.valid
    assert any("diagnosis" in error or "scope_mismatch" in error for error in outcome.validation.errors)


def test_prediction_falsification_inconclusive_and_direction_are_required(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)
    base = _valid_kwargs(evidence["record_id"])

    for field_name in ("measurable_prediction", "falsification_condition", "inconclusive_condition"):
        kwargs = dict(base)
        kwargs[field_name] = ""
        with pytest.raises(ValueError, match=field_name):
            registry.propose(**kwargs)

    with pytest.raises(ValueError, match="expected_direction"):
        registry.propose(**{**base, "expected_direction": "cause"})


def test_causal_claim_language_and_status_are_rejected(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)
    kwargs = _valid_kwargs(evidence["record_id"])
    kwargs["statement"] = "X caused Y."
    record = registry.propose(**kwargs)
    outcome = registry.mark_testable(record)
    assert not outcome.validation.valid
    assert "statement_causal_language" in outcome.validation.errors

    with pytest.raises(ValueError, match="causality_status"):
        C2HypothesisRecord.create(
            statement="bounded statement",
            supporting_evidence_ids=[evidence["record_id"]],
            measurable_prediction="a measurable target",
            falsification_condition="a measurable falsification",
            inconclusive_condition="a measurable inconclusive condition",
            causality_status="causal",
        )


def test_alternatives_and_limitations_are_preserved_and_validated(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)
    kwargs = _valid_kwargs(evidence["record_id"])
    kwargs["alternative_hypotheses"] = (
        {"label": "alternative-a", "text": "An alternative bounded explanation.", "evidence_ids": [evidence["record_id"]]},
        {"label": "alternative-b", "text": "Another bounded explanation.", "evidence_ids": [evidence["record_id"]]},
    )
    record = registry.propose(**kwargs)
    outcome = registry.mark_testable(record)
    assert outcome.validation.valid
    assert len(outcome.record.alternative_hypotheses) == 2
    assert outcome.record.limitations


def test_lineage_complete_partial_and_missing_edges(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)
    record = registry.propose(**_valid_kwargs(evidence["record_id"]))
    complete = registry.get_lineage(record.hypothesis_id)
    assert complete["status"] == "complete"
    assert complete["resolved_edges"]

    missing = registry.propose(**{**_valid_kwargs(evidence["record_id"]), "supporting_evidence_ids": ["missing"], "idempotency_key": "missing-key"})
    partial = registry.get_lineage(missing.hypothesis_id)
    assert partial["status"] == "partial"
    assert "missing" in partial["missing_ids"]
    assert partial["invalid_edges"]

    assert registry.get_lineage("not-found")["status"] == "not_found"


def test_deterministic_idempotency_retry_and_distinct_inputs(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)
    kwargs = _valid_kwargs(evidence["record_id"])
    first = registry.propose(**kwargs)
    second = registry.propose(**kwargs)
    distinct = registry.propose(**{**kwargs, "measurable_prediction": "A different measurable prediction.", "idempotency_key": "different-prediction"})

    assert first.hypothesis_id == second.hypothesis_id
    assert first.hypothesis_id != distinct.hypothesis_id
    assert len(registry._records_by_id) == 2


def test_future_supported_or_result_transitions_are_blocked_in_p3(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)
    record = registry.propose(**_valid_kwargs(evidence["record_id"]))

    with pytest.raises(ValueError, match="future result"):
        registry.transition(record, "supported")
    with pytest.raises(ValueError, match="future result"):
        registry.transition(record, "tested")


def test_legacy_hypothesis_string_is_not_auto_converted_and_coexists(tmp_path):
    store = _store(tmp_path)
    legacy = ExperimentResult.create(hypothesis="legacy string", variable="legacy-variable")
    store.save_experiment(legacy)
    registry = _registry(store)

    assert registry.get("legacy string") is None
    assert not registry._records_by_id
    assert len(store.ledger.read()) == 1


def test_adversarial_secrets_are_redacted_and_registry_does_not_persist(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _chain(store)
    registry = _registry(store)
    before = len(store.ledger.read())
    kwargs = _valid_kwargs(evidence["record_id"])
    kwargs["statement"] = "A bounded statement with api_key=secret-value and Bearer token-value."
    kwargs["limitations"] = ({"reason": "bounded", "raw_payload": {"authorization": "Bearer secret-token", "password": "pw"}},)
    record = registry.propose(**kwargs)
    payload = record.to_dict()

    assert "secret-value" not in str(payload)
    assert "Bearer token-value" not in str(payload)
    assert "raw_payload" not in str(payload)
    assert "Bearer secret-token" not in str(payload)
    assert len(store.ledger.read()) == before
