"""R2 controlled integration readiness checks.

These tests consume existing C1/C2/Phase A-B interfaces only. They do not
invoke production execution paths, write production persistence, or mutate
frozen contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector
from mindmargin.intelligence.contracts import DecisionRecord, DecisionStore, PipelineEvent
from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess, LineageScope
from mindmargin.intelligence.c2_contracts import C2_SCHEMA_VERSION, CAUSALITY_STATUSES
from mindmargin.intelligence.metric_registry import MetricRegistry


def _store(tmp_path):
    return DecisionStore(tmp_path / "isolated" / "events" / "lineage.jsonl")


def _complete_lineage(store: DecisionStore, pipeline_id: str = "r2-pipeline", correlation_id: str = "r2-correlation"):
    decision = store.save_decision(
        DecisionRecord.create(
            "topic_selection",
            pipeline_id=pipeline_id,
            correlation_id=correlation_id,
            context={"topic": "controlled-readiness"},
        )
    )
    event = store.save_event(
        PipelineEvent.create(
            "production.completed",
            pipeline_id,
            decision_id=decision["decision_id"],
            correlation_id=correlation_id,
            source="phase_b",
        )
    )
    observed_at = datetime.now(timezone.utc).isoformat()
    observation = ObservationCollector(store).collect(
        metric_name="impressions",
        observed_value=12,
        subject_id="r2-video",
        source_kind="youtube_metric",
        source="phase_b",
        window_start="2026-08-19T00:00:00+00:00",
        window_end="2026-08-19T01:00:00+00:00",
        observed_at=observed_at,
        pipeline_id=pipeline_id,
        video_id="r2-video",
        correlation_id=correlation_id,
        parent_record_ids=[decision["decision_id"]],
        source_record_ids=[event["event_id"]],
    )
    evidence = EvidenceBuilder(store).build(
        observation_ids=[observation["record_id"]],
        source_artifacts={event["event_id"]: event},
        source_record_ids=[event["event_id"]],
        metric_name="impressions",
        value=12,
        source="phase_b",
        claim_scope="r2-video",
        pipeline_id=pipeline_id,
        video_id="r2-video",
        correlation_id=correlation_id,
        window_start=observation["window_start"],
        window_end=observation["window_end"],
        source_kind="youtube_metric",
    )
    return decision, event, observation, evidence


def test_existing_c1_c2_interfaces_provide_complete_read_only_lineage(tmp_path):
    store = _store(tmp_path)
    decision, event, observation, evidence = _complete_lineage(store)
    ledger_path = store.ledger.path
    before = ledger_path.read_bytes()

    access = C2ReadOnlyEvidenceAccess(store)
    resolved_observation = access.get_observation(observation["record_id"])
    resolved_evidence = access.get_evidence(evidence["record_id"])
    view = access.lineage_view(
        scope=LineageScope(pipeline_id="r2-pipeline", correlation_id="r2-correlation")
    )

    assert resolved_observation is not None
    assert resolved_evidence is not None
    assert resolved_observation["record_id"] == observation["record_id"]
    assert resolved_evidence["validation_status"] == "valid"
    assert view.status == "complete"
    assert not view.missing_ids
    assert not view.invalid_edges
    assert view.resolved_edges
    assert any(row.get("decision_id") == decision["decision_id"] for row in view.records_by_type["decision"])
    assert any(row.get("event_id") == event["event_id"] for row in view.records_by_type["event"])

    # Returned rows are copies; mutating the read result cannot mutate the store.
    resolved_observation["pipeline_id"] = "mutated-outside-store"
    assert access.get_observation(observation["record_id"])["pipeline_id"] == "r2-pipeline"
    assert ledger_path.read_bytes() == before


def test_read_only_access_reports_not_found_partial_and_scope_mismatch(tmp_path):
    empty_store = _store(tmp_path / "empty")
    empty_access = C2ReadOnlyEvidenceAccess(empty_store)
    assert empty_access.lineage_view(scope=LineageScope(pipeline_id="missing")).status == "not_found"

    store = _store(tmp_path / "partial")
    foreign_event = store.save_event(
        PipelineEvent.create("production.completed", "foreign-pipeline", correlation_id="foreign-correlation")
    )
    observation = ObservationCollector(store).collect(
        metric_name="impressions",
        observed_value=1,
        subject_id="r2-video",
        source_kind="youtube_metric",
        source="phase_b",
        window_start="2026-08-19T00:00:00+00:00",
        window_end="2026-08-19T01:00:00+00:00",
        observed_at=datetime.now(timezone.utc).isoformat(),
        pipeline_id="r2-pipeline",
        video_id="r2-video",
        correlation_id="r2-correlation",
        source_record_ids=[foreign_event["event_id"], "missing-event"],
    )
    access = C2ReadOnlyEvidenceAccess(store)
    view = access.lineage_view(scope=LineageScope(pipeline_id="r2-pipeline", correlation_id="r2-correlation"))

    assert view.status == "partial"
    assert "missing-event" in view.missing_ids
    assert view.invalid_edges
    mismatch = access.validate_scope(
        {"pipeline_id": "r2-pipeline", "correlation_id": "r2-correlation"},
        {"pipeline_id": "foreign-pipeline", "correlation_id": "foreign-correlation"},
    )
    assert not mismatch.valid
    assert "pipeline_id_mismatch" in mismatch.reasons
    assert "correlation_id_mismatch" in mismatch.reasons
    assert observation["pipeline_id"] == "r2-pipeline"


def test_readiness_access_surface_has_no_mutator_methods(tmp_path):
    access = C2ReadOnlyEvidenceAccess(_store(tmp_path))
    mutators = [
        name for name in dir(access)
        if any(token in name.lower() for token in ("save", "append", "write", "update", "delete", "persist"))
    ]
    assert mutators == []


def test_frozen_c1_and_c2_contract_markers_remain_unchanged():
    assert MetricRegistry().version == "c1-1"
    assert C2_SCHEMA_VERSION == "c2-1"
    assert CAUSALITY_STATUSES == frozenset({"not_claimed"})


def test_readiness_fixture_isolated_from_production_persistence(tmp_path):
    store = _store(tmp_path)
    _complete_lineage(store, pipeline_id="isolated-pipeline", correlation_id="isolated-correlation")
    access = C2ReadOnlyEvidenceAccess(store)
    assert access.lineage_view(scope=LineageScope(pipeline_id="isolated-pipeline")).status == "complete"
    assert not list(tmp_path.rglob("*.db"))
    assert not list(tmp_path.rglob("*.sqlite"))
    assert store.ledger.path.is_relative_to(tmp_path)
