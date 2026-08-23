"""Read-only C2-P1 boundary tests using the real temporary JSONL ledger."""

from datetime import datetime, timezone

import pytest

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector
from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess, LineageScope
from mindmargin.intelligence.contracts import DecisionRecord, DecisionStore, ObservationRecord, PipelineEvent


def _store(tmp_path):
    return DecisionStore(tmp_path / "lineage.jsonl")


def _complete_c1_chain(store):
    decision = store.save_decision(
        DecisionRecord.create(
            "topic_selection",
            pipeline_id="p-access",
            content_id="content-access",
            video_id="video-access",
            correlation_id="corr-access",
            selected_option="topic-a",
        )
    )
    event = store.save_event(
        PipelineEvent.create(
            "production.completed",
            "p-access",
            decision_id=decision["decision_id"],
            content_id="content-access",
            video_id="video-access",
            correlation_id="corr-access",
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
        claim_scope="video-access",
        pipeline_id="p-access",
        content_id="content-access",
        video_id="video-access",
        correlation_id="corr-access",
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        source_kind="phase_b_event",
    )
    return decision, event, observation, evidence


def test_get_observation_get_evidence_and_resolve_record_are_typed_and_read_only(tmp_path):
    store = _store(tmp_path)
    _, event, observation, evidence = _complete_c1_chain(store)
    access = C2ReadOnlyEvidenceAccess(store)
    before = len(store.ledger.read())

    assert access.get_observation(observation["record_id"])["record_id"] == observation["record_id"]
    assert access.get_evidence(evidence["record_id"])["record_id"] == evidence["record_id"]
    assert access.resolve_record(event["event_id"])["event_id"] == event["event_id"]
    assert access.get_observation(event["event_id"]) is None
    assert access.get_evidence(observation["record_id"]) is None
    assert access.resolve_record("missing-record") is None

    returned = access.get_observation(observation["record_id"])
    returned["quality"] = "mutated-copy"
    assert access.get_observation(observation["record_id"])["quality"] == "valid"
    assert len(store.ledger.read()) == before
    assert not hasattr(access, "save_observation")
    assert not hasattr(access, "save_evidence")


def test_complete_lineage_requires_explicit_edges_and_quality(tmp_path):
    store = _store(tmp_path)
    _complete_c1_chain(store)
    access = C2ReadOnlyEvidenceAccess(store)

    view = access.lineage_view(
        scope=LineageScope(
            pipeline_id="p-access",
            video_id="video-access",
            correlation_id="corr-access",
        )
    )

    assert view.status == "complete"
    assert view.missing_ids == ()
    assert view.invalid_edges == ()
    assert view.quality_warnings == ()
    assert view.resolved_edges
    assert view.to_dict()["status"] == "complete"


def test_pipeline_id_alone_does_not_fabricate_complete_lineage(tmp_path):
    store = _store(tmp_path)
    decision = store.save_decision(DecisionRecord.create("topic_selection", pipeline_id="p-only"))
    store.save_event(PipelineEvent.create("production.completed", "p-only", decision_id=decision["decision_id"]))
    access = C2ReadOnlyEvidenceAccess(store)

    view = access.lineage_view(scope=LineageScope(pipeline_id="p-only"))

    assert view.status == "partial"
    assert "missing_observation" in view.quality_warnings
    assert "missing_evidence" not in view.quality_warnings


def test_not_found_has_empty_records_and_no_fabricated_edges(tmp_path):
    access = C2ReadOnlyEvidenceAccess(_store(tmp_path))

    view = access.lineage_view(scope=LineageScope(pipeline_id="missing"))

    assert view.status == "not_found"
    assert all(not rows for rows in view.records_by_type.values())
    assert view.resolved_edges == ()
    assert view.missing_ids == ()
    assert view.invalid_edges == ()


def test_missing_source_id_is_reported_as_partial_and_invalid_edge(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    observation = ObservationRecord.create(
        metric_name="lifecycle_status",
        subject_id="p-missing",
        window_start=now,
        window_end=now,
        observed_value="production.completed",
        pipeline_id="p-missing",
        correlation_id="corr-missing",
        source="test",
        source_kind="phase_b_event",
        freshness_seconds=1,
        quality="valid",
        source_record_ids=["missing-source"],
    )
    saved = store.save_observation(observation)
    access = C2ReadOnlyEvidenceAccess(store)

    view = access.lineage_view(scope=LineageScope(pipeline_id="p-missing"))

    assert view.status == "partial"
    assert "missing-source" in view.missing_ids
    assert any(edge["type"] == "source" for edge in view.invalid_edges)
    assert saved["record_id"] in {row["record_id"] for row in view.records_by_type["observation"]}


def test_scope_mismatch_is_invalid_not_resolved(tmp_path):
    store = _store(tmp_path)
    event = store.save_event(PipelineEvent.create("production.completed", "p-parent", correlation_id="corr-parent"))
    now = datetime.now(timezone.utc).isoformat()
    store.save_observation(
        ObservationRecord.create(
            metric_name="lifecycle_status",
            subject_id="p-child",
            window_start=now,
            window_end=now,
            observed_value="production.completed",
            pipeline_id="p-child",
            correlation_id="corr-child",
            source="test",
            source_kind="phase_b_event",
            freshness_seconds=1,
            quality="valid",
            source_record_ids=[event["event_id"]],
        )
    )
    access = C2ReadOnlyEvidenceAccess(store)

    view = access.lineage_view(scope=LineageScope(pipeline_id="p-child"))

    assert view.status == "partial"
    assert view.resolved_edges == ()
    assert view.invalid_edges[0]["reason"] == ["pipeline_id_mismatch", "correlation_id_mismatch"]


def test_validate_scope_checks_pipeline_content_video_and_correlation():
    access = C2ReadOnlyEvidenceAccess.__new__(C2ReadOnlyEvidenceAccess)
    child = {
        "pipeline_id": "p1",
        "content_id": "c1",
        "video_id": "v1",
        "correlation_id": "corr1",
    }
    parent = {
        "pipeline_id": "p2",
        "content_id": "c2",
        "video_id": "v2",
        "correlation_id": "corr2",
    }

    result = access.validate_scope(child, parent)

    assert not result.valid
    assert set(result.reasons) == {
        "pipeline_id_mismatch",
        "content_id_mismatch",
        "video_id_mismatch",
        "correlation_id_mismatch",
    }


def test_scope_requires_at_least_one_identifier():
    with pytest.raises(ValueError, match="at least one"):
        LineageScope()
