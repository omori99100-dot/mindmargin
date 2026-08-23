"""C2-P2 bounded Diagnosis Coordinator tests over real P1/C1 records."""

from datetime import datetime, timezone

import pytest

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector
from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess, LineageScope
from mindmargin.intelligence.c2_contracts import C2ConfidenceValue
from mindmargin.intelligence.c2_diagnosis import C2DiagnosisCoordinator
from mindmargin.intelligence.contracts import (
    DecisionRecord,
    DecisionStore,
    EvidenceRecord,
    PipelineEvent,
)


def _store(tmp_path):
    return DecisionStore(tmp_path / "lineage.jsonl")


def _valid_chain(store, *, pipeline="p-diagnosis", video="v-diagnosis", correlation="corr-diagnosis"):
    decision = store.save_decision(
        DecisionRecord.create(
            "topic_selection",
            pipeline_id=pipeline,
            video_id=video,
            correlation_id=correlation,
            selected_option="topic-a",
        )
    )
    event = store.save_event(
        PipelineEvent.create(
            "production.completed",
            pipeline,
            decision_id=decision["decision_id"],
            video_id=video,
            correlation_id=correlation,
            source="phase_b",
        )
    )
    observation = ObservationCollector(store).collect_from_event(
        event["event_id"],
        metric_name="lifecycle_status",
        observation_type="lifecycle_signal",
    )
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


def _coordinator(store):
    return C2DiagnosisCoordinator(C2ReadOnlyEvidenceAccess(store))


def _confidence():
    return C2ConfidenceValue(
        score=0.7,
        dimension="evidence_support",
        basis="provenance_based",
        limitations=("observational evidence only",),
    )


def _valid_candidate(evidence_id):
    return (
        {
            "label": "quota pattern",
            "text": "The pattern is consistent with a quota issue within this bounded scope.",
            "evidence_ids": [evidence_id],
        },
        {
            "label": "authentication pattern",
            "text": "The pattern is also consistent with an authentication issue within this scope.",
            "evidence_ids": [evidence_id],
        },
    )


def test_valid_evidence_produces_valid_bounded_diagnosis(tmp_path):
    store = _store(tmp_path)
    _, _, observation, evidence = _valid_chain(store)
    coordinator = _coordinator(store)
    before = len(store.ledger.read())

    outcome = coordinator.diagnose_for_lineage(
        scope=LineageScope(pipeline_id="p-diagnosis", video_id="v-diagnosis", correlation_id="corr-diagnosis"),
        problem_statement="The completed publish signal is valid but requires bounded interpretation.",
        confidence=_confidence(),
        diagnosis_type="operational_failure",
        candidate_explanations=_valid_candidate(evidence["record_id"]),
        limitations=({"reason": "observational evidence only", "scope": "single video"},),
    )

    assert outcome.validation.valid
    assert outcome.validation.status == "validated"
    assert outcome.record is not None
    assert outcome.record.status == "validated"
    assert outcome.record.evidence_ids == (evidence["record_id"],)
    assert outcome.record.observation_ids == (observation["record_id"],)
    assert outcome.record.causal_claim is None
    assert len(outcome.record.candidate_explanations) == 2
    assert len(store.ledger.read()) == before


def test_missing_evidence_is_rejected_without_guessing(tmp_path):
    store = _store(tmp_path)
    coordinator = _coordinator(store)
    record = coordinator.propose(
        problem_statement="A bounded problem with unresolved support.",
        evidence_ids=["missing-evidence"],
        pipeline_id="p-missing",
        correlation_id="corr-missing",
        confidence=_confidence(),
        limitations=({"reason": "support unresolved"},),
    )

    validation = coordinator.validate(record)

    assert not validation.valid
    assert validation.status == "rejected"
    assert "evidence_not_found:missing-evidence" in validation.errors
    assert record.status == "planned"


def test_invalid_evidence_is_rejected(tmp_path):
    store = _store(tmp_path)
    _, event, observation, _ = _valid_chain(store)
    invalid = EvidenceRecord.create(
        observation_ids=[observation["record_id"]],
        source_artifact_ids=[event["event_id"]],
        metric_name="lifecycle_status",
        value="production.completed",
        pipeline_id="p-diagnosis",
        video_id="v-diagnosis",
        correlation_id="corr-diagnosis",
        parent_record_ids=[observation["record_id"]],
        source_record_ids=[event["event_id"]],
        source="phase_b",
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        provenance={"source_kind": "phase_b_event"},
        validation_status="invalid",
        status="rejected",
    )
    invalid_row = store.save_evidence(invalid)
    coordinator = _coordinator(store)
    record = coordinator.propose(
        problem_statement="Invalid evidence must not support diagnosis.",
        evidence_ids=[invalid_row["record_id"]],
        pipeline_id="p-diagnosis",
        video_id="v-diagnosis",
        correlation_id="corr-diagnosis",
        confidence=_confidence(),
        limitations=({"reason": "invalid evidence"},),
    )

    validation = coordinator.validate(record)

    assert not validation.valid
    assert "evidence_not_valid:" + invalid_row["record_id"] in validation.errors
    assert validation.status == "rejected"


def test_stale_observation_and_missing_provenance_do_not_validate(tmp_path):
    store = _store(tmp_path)
    _, event, observation, _ = _valid_chain(store)
    stale = ObservationCollector(store).collect(
        metric_name="lifecycle_status",
        observed_value="production.completed",
        subject_id="v-diagnosis",
        source_kind="phase_b_event",
        source="phase_b",
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        observed_at="2000-01-01T00:00:00+00:00",
        pipeline_id="p-stale",
        video_id="v-diagnosis",
        correlation_id="corr-stale",
        parent_record_ids=[],
        source_record_ids=[event["event_id"]],
        observation_type="lifecycle_signal",
    )
    missing_provenance = EvidenceRecord.create(
        observation_ids=[stale["record_id"]],
        source_artifact_ids=[event["event_id"]],
        metric_name="lifecycle_status",
        value="production.completed",
        pipeline_id="p-stale",
        video_id="v-diagnosis",
        correlation_id="corr-stale",
        parent_record_ids=[stale["record_id"]],
        source_record_ids=[event["event_id"]],
        source="phase_b",
        window_start=stale["window_start"],
        window_end=stale["window_end"],
        provenance={},
        validation_status="valid",
        status="validated",
    )
    evidence = store.save_evidence(missing_provenance)
    coordinator = _coordinator(store)
    record = coordinator.propose(
        problem_statement="Stale evidence must not validate.",
        evidence_ids=[evidence["record_id"]],
        pipeline_id="p-stale",
        video_id="v-diagnosis",
        correlation_id="corr-stale",
        confidence=_confidence(),
        limitations=({"reason": "stale source"},),
    )

    validation = coordinator.validate(record)

    assert not validation.valid
    assert any(error.startswith("observation_not_valid:") for error in validation.errors)
    assert any(error.startswith("evidence_provenance_missing:") for error in validation.errors)


def test_scope_mismatch_is_rejected(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _valid_chain(store)
    coordinator = _coordinator(store)
    record = coordinator.propose(
        problem_statement="The scope must match the supporting evidence.",
        evidence_ids=[evidence["record_id"]],
        pipeline_id="wrong-pipeline",
        video_id="v-diagnosis",
        correlation_id="corr-diagnosis",
        confidence=_confidence(),
        limitations=({"reason": "scope test"},),
    )

    validation = coordinator.validate(record)

    assert not validation.valid
    assert any(error.startswith("lineage_not_complete:") for error in validation.errors)


def test_partial_lineage_returns_no_validated_diagnosis(tmp_path):
    store = _store(tmp_path)
    decision = store.save_decision(DecisionRecord.create("topic_selection", pipeline_id="p-partial"))
    store.save_event(PipelineEvent.create("production.completed", "p-partial", decision_id=decision["decision_id"]))
    coordinator = _coordinator(store)

    outcome = coordinator.diagnose_for_lineage(
        scope=LineageScope(pipeline_id="p-partial"),
        problem_statement="Partial lineage must remain explicit.",
        confidence=_confidence(),
        limitations=({"reason": "no evidence"},),
    )

    assert outcome.record is None
    assert not outcome.validation.valid
    assert outcome.validation.status == "rejected"
    assert any(error.startswith("lineage_not_complete:") for error in outcome.validation.errors)


def test_fabricated_parent_or_source_edges_are_rejected(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _valid_chain(store)
    coordinator = _coordinator(store)
    record = coordinator.propose(
        problem_statement="Explicit lineage edges must resolve.",
        evidence_ids=[evidence["record_id"]],
        pipeline_id="p-diagnosis",
        video_id="v-diagnosis",
        correlation_id="corr-diagnosis",
        parent_record_ids=("missing-parent",),
        source_record_ids=("missing-source",),
        confidence=_confidence(),
        limitations=({"reason": "edge test"},),
    )

    validation = coordinator.validate(record)

    assert not validation.valid
    assert "lineage_parent_not_found:missing-parent" in validation.errors
    assert "lineage_source_not_found:missing-source" in validation.errors


def test_causal_claim_injection_is_rejected(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _valid_chain(store)
    coordinator = _coordinator(store)
    with pytest.raises(ValueError, match="causal_claim"):
        coordinator.propose(
            problem_statement="X caused Y.",
            evidence_ids=[evidence["record_id"]],
            pipeline_id="p-diagnosis",
            video_id="v-diagnosis",
            correlation_id="corr-diagnosis",
            confidence=_confidence(),
            limitations=({"reason": "claim test"},),
            # P0 prevents a non-null causal_claim before validation.
            causal_claim="X caused Y",
        )


def test_confidence_and_alternatives_remain_bounded(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _valid_chain(store)
    coordinator = _coordinator(store)
    record = coordinator.propose(
        problem_statement="Two bounded explanations remain plausible.",
        evidence_ids=[evidence["record_id"]],
        pipeline_id="p-diagnosis",
        video_id="v-diagnosis",
        correlation_id="corr-diagnosis",
        confidence=_confidence(),
        candidate_explanations=_valid_candidate(evidence["record_id"]),
        limitations=({"reason": "observational", "scope": "single video"},),
    )
    validation = coordinator.validate(record)

    assert validation.valid
    assert record.confidence.dimension == "evidence_support"
    assert record.causal_claim is None
    assert all("caused" not in str(item).lower() for item in record.candidate_explanations)


def test_deterministic_retry_returns_one_in_memory_proposal(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _valid_chain(store)
    coordinator = _coordinator(store)
    kwargs = dict(
        problem_statement="Retry-safe bounded diagnosis.",
        evidence_ids=[evidence["record_id"]],
        pipeline_id="p-diagnosis",
        video_id="v-diagnosis",
        correlation_id="corr-diagnosis",
        confidence=_confidence(),
        limitations=({"reason": "retry test"},),
        idempotency_key="diagnosis:p-diagnosis:retry-key",
    )

    before = len(store.ledger.read())
    first = coordinator.propose(**kwargs)
    second = coordinator.propose(**kwargs)

    assert first.diagnosis_id == second.diagnosis_id
    assert first.envelope.idempotency_key == second.envelope.idempotency_key
    assert len(store.ledger.read()) == before


def test_adversarial_secrets_are_redacted_at_p0_serialization_boundary(tmp_path):
    store = _store(tmp_path)
    _, _, _, evidence = _valid_chain(store)
    coordinator = _coordinator(store)
    record = coordinator.propose(
        problem_statement="A bounded diagnosis with sanitized explanation metadata.",
        evidence_ids=[evidence["record_id"]],
        pipeline_id="p-diagnosis",
        video_id="v-diagnosis",
        correlation_id="corr-diagnosis",
        confidence=_confidence(),
        candidate_explanations=(
            {
                "label": "safe candidate",
                "text": "The pattern is consistent with a bounded operational issue.",
                "evidence_ids": [evidence["record_id"]],
                "api_key": "secret-value",
                "raw_payload": {"authorization": "Bearer secret-token"},
            },
        ),
        limitations=({"reason": "bounded", "password": "do-not-store"},),
    )
    payload = record.to_dict()
    candidate = payload["candidate_explanations"][0]

    assert candidate["api_key"] == "[REDACTED]"
    assert "raw_payload" not in candidate
    assert payload["limitations"][0]["password"] == "[REDACTED]"
    assert "Bearer secret-token" not in str(payload)
