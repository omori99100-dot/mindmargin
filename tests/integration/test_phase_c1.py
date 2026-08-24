from datetime import datetime, timedelta, timezone

import pytest

from mindmargin.intelligence.c1 import EvidenceBuilder, ObservationCollector, assess_freshness
from mindmargin.intelligence.contracts import DecisionStore, EvidenceRecord, ObservationRecord
from mindmargin.intelligence.metric_registry import MetricRegistry


def store(tmp_path):
    return DecisionStore(tmp_path / "events" / "lineage.jsonl")


def collect(store, observed_at=None, value=12, parent_record_ids=None, source_record_ids=None, **kwargs):
    now = observed_at or datetime.now(timezone.utc).isoformat()
    return ObservationCollector(store).collect(
        metric_name="impressions", observed_value=value, subject_id="video-1",
        source_kind="youtube_metric", source="youtube.analytics", window_start="2026-08-19T00:00:00+00:00",
        window_end="2026-08-19T01:00:00+00:00", observed_at=now, pipeline_id="pipe-c1",
        video_id="video-1", parent_record_ids=parent_record_ids or ["dec-1"], source_record_ids=source_record_ids or ["evt-1"], **kwargs,
    )


def test_metric_registry_contains_only_canonical_metrics():
    registry = MetricRegistry()
    assert registry.version == "c1-1"
    assert registry.require("impressions").unit == "count"
    with pytest.raises(ValueError):
        registry.require("invented_metric")


def test_freshness_mapping_is_explicit():
    definition = MetricRegistry().require("impressions")
    now = datetime.now(timezone.utc)
    assert assess_freshness(definition, now.isoformat(), now).state == "fresh"
    old = (now - timedelta(days=3)).isoformat()
    assert assess_freshness(definition, old, now).state == "stale"
    assert assess_freshness(definition, "not-a-time").state == "unknown"


def test_collector_creates_metric_snapshot_with_real_lineage(tmp_path):
    s = store(tmp_path)
    row = collect(s)
    assert row["record_type"] == "observation"
    assert row["observation_type"] == "metric_snapshot"
    assert row["parent_record_ids"] == ["dec-1"]
    assert row["source_record_ids"] == ["evt-1"]
    assert row["quality"] == "valid"
    events = s.ledger.read(pipeline_id="pipe-c1")
    assert any(item.get("event_type") == "observation.recorded" for item in events)


def test_metric_movement_is_not_anomaly_without_explicit_rule(tmp_path):
    row = collect(store(tmp_path), value=99, baseline_value=10)
    assert row["observation_type"] == "metric_snapshot"
    assert row["anomaly_rule_id"] == ""


def test_explicit_anomaly_rule_creates_anomaly(tmp_path):
    row = collect(store(tmp_path), value=99, baseline_value=10, anomaly_rule_id="ctr-drop-v1", anomaly_rule=lambda value, baseline: value > baseline)
    assert row["observation_type"] == "anomaly"
    assert row["anomaly_rule_id"] == "ctr-drop-v1"


def test_stale_observation_is_explicit(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    s = store(tmp_path)
    row = collect(s, observed_at=old)
    assert row["quality"] == "stale"
    assert any(item.get("event_type") == "observation.stale" for item in s.ledger.read(pipeline_id="pipe-c1"))


def test_observation_idempotency_allows_replay_without_duplicate(tmp_path):
    s = store(tmp_path)
    first = collect(s, value=12)
    second = collect(s, value=12)
    observations = s.observations_for_pipeline("pipe-c1")
    assert first["record_id"] == second["record_id"]
    assert len(observations) == 1


def test_evidence_validates_against_real_observation_and_artifact(tmp_path):
    s = store(tmp_path)
    observation = collect(s)
    evidence = EvidenceBuilder(s).build(
        observation_ids=[observation["record_id"]], source_artifacts={"evt-1": {"event_type": "metric"}},
        metric_name="impressions", value=12, source="youtube.analytics", claim_scope="video-1",
        pipeline_id="pipe-c1", video_id="video-1", window_start=observation["window_start"], window_end=observation["window_end"],
        source_kind="youtube_metric",
    )
    assert evidence["validation_status"] == "valid"
    assert evidence["status"] == "validated"
    assert evidence["observation_ids"] == [observation["record_id"]]
    events = s.ledger.read(pipeline_id="pipe-c1")
    assert any(item.get("event_type") == "evidence.validated" for item in events)


def test_missing_source_and_observation_is_rejected(tmp_path):
    s = store(tmp_path)
    evidence = EvidenceBuilder(s).build(
        observation_ids=["missing-observation"], source_artifacts={}, metric_name="impressions", value=1,
        source="source", claim_scope="video-1", pipeline_id="pipe-c1", window_start="x", window_end="y",
        source_kind="youtube_metric",
    )
    assert evidence["validation_status"] == "rejected"
    assert evidence["status"] == "rejected"
    assert any(item.get("event_type") == "evidence.rejected" for item in s.ledger.read(pipeline_id="pipe-c1"))


def test_stale_observation_cannot_become_valid_evidence(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    s = store(tmp_path)
    observation = collect(s, observed_at=old)
    evidence = EvidenceBuilder(s).build(
        observation_ids=[observation["record_id"]], source_artifacts={"evt-1": {"event_type": "metric"}},
        metric_name="impressions", value=12, source="youtube.analytics", claim_scope="video-1",
        pipeline_id="pipe-c1", window_start=observation["window_start"], window_end=observation["window_end"], source_kind="youtube_metric",
    )
    assert evidence["validation_status"] == "stale"
    assert evidence["status"] == "rejected"


def test_redaction_drops_unknown_nested_payloads(tmp_path):
    s = store(tmp_path)
    observation = ObservationRecord.create(
        metric_name="impressions", subject_id="video-1", window_start="a", window_end="b", observed_value={"impressions": 1, "raw_response": {"api_key": "secret"}},
        pipeline_id="pipe-c1", source="source", source_kind="youtube_metric", notes="authorization: Bearer secret",
    )
    row = s.save_observation(observation)
    assert "raw_response" not in row["observed_value"]
    assert "secret" not in str(row)


def test_lineage_reports_complete_partial_and_not_found(tmp_path):
    from mindmargin.intelligence.contracts import DecisionRecord, PipelineEvent
    s = store(tmp_path)
    assert s.lineage_for_pipeline("missing")["status"] == "not_found"
    decision = s.save_decision(DecisionRecord.create("topic_selection", pipeline_id="pipe-c1", context={"topic": "x"}))
    event = s.save_event(PipelineEvent.create("production.completed", "pipe-c1"))
    observation = collect(s, parent_record_ids=[decision["decision_id"]], source_record_ids=[event["event_id"]])
    partial = s.lineage_for_pipeline("pipe-c1")
    assert partial["status"] == "partial"
    assert "evidence" in partial["warnings"]
    EvidenceBuilder(s).build(
        observation_ids=[observation["record_id"]], source_artifacts={"evt-1": {"event_type": "metric"}}, metric_name="impressions", value=12,
        source="source", claim_scope="video-1", pipeline_id="pipe-c1", window_start=observation["window_start"], window_end=observation["window_end"], source_kind="youtube_metric",
    )
    complete = s.lineage_for_pipeline("pipe-c1")
    assert complete["status"] == "complete"
    assert complete["resolved_edges"]


def test_c1_does_not_add_production_publish_hook():
    import inspect
    from mindmargin.agents import decision_executor
    assert "ObservationCollector" not in inspect.getsource(decision_executor)


def test_collector_reads_real_phase_b_event(tmp_path):
    from mindmargin.intelligence.contracts import PipelineEvent
    s = store(tmp_path)
    event = s.save_event(PipelineEvent.create("production.completed", "pipe-event", source="pipeline"))
    row = ObservationCollector(s).collect_from_event(event["event_id"])
    assert row["source_record_ids"] == [event["event_id"]]
    assert row["source_kind"] == "phase_b_event"
    assert row["pipeline_id"] == "pipe-event"


def test_observation_lifecycle_and_failure_types_are_real(tmp_path):
    from mindmargin.intelligence.contracts import PipelineEvent, ExperimentResult
    s = store(tmp_path)
    lifecycle = s.save_event(PipelineEvent.create("production.completed", "p-life", correlation_id="corr-life"))
    failure = s.save_event(PipelineEvent.create("pipeline.retry", "p-life", correlation_id="corr-life"))
    lifecycle_row = ObservationCollector(s).collect_from_event(lifecycle["event_id"])
    failure_row = ObservationCollector(s).collect_from_failure(failure["event_id"])
    experiment = s.save_experiment(ExperimentResult.create("test", "title", success_metric="impressions", sample_size=10, minimum_sample=100, pipeline_id="p-life", correlation_id="corr-life"))
    experiment_row = ObservationCollector(s).collect_from_experiment(experiment["experiment_id"])
    assert lifecycle_row["observation_type"] == "lifecycle_signal"
    assert failure_row["observation_type"] == "operational_failure"
    assert experiment_row["observation_type"] == "experiment_signal"
    assert any(item.get("event_type") == "observation.recorded" for item in s.ledger.read(pipeline_id="p-life"))


def test_invalid_observation_is_persisted_and_emits_invalid_event(tmp_path):
    s = store(tmp_path)
    row = ObservationCollector(s).collect(metric_name="unknown_metric", observed_value=1, subject_id="v", source_kind="unknown", source="test", window_start="a", window_end="b", observed_at="bad", pipeline_id="p-invalid", correlation_id="c-invalid")
    assert row["status"] == "invalid"
    assert row["quality"] == "invalid"
    assert any(item.get("event_type") == "observation.invalid" and item.get("correlation_id") == "c-invalid" for item in s.ledger.read(pipeline_id="p-invalid"))


@pytest.mark.parametrize("quality", ["partial", "stale", "invalid"])
def test_insufficient_observation_quality_cannot_become_valid_evidence(tmp_path, quality):
    s = store(tmp_path)
    observation = ObservationRecord.create(metric_name="impressions", subject_id="v", window_start="a", window_end="b", observed_value=1, pipeline_id="p-quality", correlation_id="c-quality", quality=quality, freshness_seconds=None if quality == "partial" else 100)
    saved = s.save_observation(observation)
    evidence = EvidenceBuilder(s).build(observation_ids=[saved["record_id"]], source_artifacts={"artifact": {"metric": "impressions"}}, source_record_ids=[], metric_name="impressions", value=1, source="test", claim_scope="v", pipeline_id="p-quality", correlation_id="c-quality", window_start="a", window_end="b", source_kind="youtube_metric")
    assert evidence["validation_status"] in {"partial", "stale", "invalid"}
    assert evidence["status"] == "rejected"


def test_wrong_metric_unit_and_aggregation_are_rejected(tmp_path):
    s = store(tmp_path)
    observation = collect(s)
    evidence = EvidenceBuilder(s).build(observation_ids=[observation["record_id"]], source_artifacts={"artifact": {"metric": "impressions"}}, metric_name="impressions", value=1, unit="seconds", aggregation="sum", source="test", claim_scope="v", pipeline_id="pipe-c1", window_start=observation["window_start"], window_end=observation["window_end"], source_kind="youtube_metric")
    assert evidence["validation_status"] == "rejected"
    assert {item["code"] for item in evidence["validation_errors"]} >= {"unit_mismatch", "aggregation_mismatch"}


def test_unresolved_source_and_wrong_scope_are_not_complete(tmp_path):
    from mindmargin.intelligence.contracts import PipelineEvent
    s = store(tmp_path)
    event = s.save_event(PipelineEvent.create("production.completed", "other-pipeline", correlation_id="other-correlation"))
    row = ObservationCollector(s).collect(metric_name="impressions", observed_value=1, subject_id="v", source_kind="youtube_metric", source="test", window_start="a", window_end="b", observed_at=datetime.now(timezone.utc).isoformat(), pipeline_id="p-scope", correlation_id="c-scope", parent_record_ids=[event["event_id"]], source_record_ids=["missing-source"])
    evidence = EvidenceBuilder(s).build(observation_ids=[row["record_id"]], source_artifacts={"artifact": {"metric": "impressions"}}, source_record_ids=["missing-source"], metric_name="impressions", value=1, source="test", claim_scope="v", pipeline_id="p-scope", correlation_id="c-scope", window_start="a", window_end="b", source_kind="youtube_metric")
    report = s.lineage_for_pipeline("p-scope")
    assert evidence["validation_status"] != "valid"
    assert report["status"] == "partial"
    assert report["invalid_edges"] or report["missing_ids"]


def test_persistence_redaction_blocks_urls_tokens_keys_and_nested_values(tmp_path):
    s = store(tmp_path)
    observation = ObservationRecord.create(metric_name="impressions", subject_id="v", window_start="a", window_end="b", observed_value={"token": "ya29.secret-token", "nested": [{"private_key": "-----BEGIN RSA PRIVATE KEY-----\nSECRET\n-----END RSA PRIVATE KEY-----"}]}, pipeline_id="p-redact", source="https://oauth.example.test/authorize?client_secret=SECRET", notes="password=SECRET authorization: Bearer SECRET")
    row = s.save_observation(observation)
    assert "SECRET" not in str(row)
    assert "oauth.example.test" not in str(row)
    assert "ya29.secret-token" not in str(row)


def test_real_end_to_end_phase_b_to_observation_to_evidence_to_lineage(tmp_path):
    from mindmargin.intelligence.contracts import DecisionRecord, PipelineEvent
    s = store(tmp_path)
    decision = s.save_decision(DecisionRecord.create("topic_selection", pipeline_id="p-e2e", context={"topic": "real"}, correlation_id="c-e2e"))
    event = s.save_event(PipelineEvent.create("production.completed", "p-e2e", decision_id=decision["decision_id"], correlation_id="c-e2e", source="phase_b"))
    observation = ObservationCollector(s).collect_from_event(event["event_id"], metric_name="lifecycle_status", observation_type="lifecycle_signal")
    evidence = EvidenceBuilder(s).build(observation_ids=[observation["record_id"]], source_artifacts={event["event_id"]: event}, source_record_ids=[event["event_id"]], metric_name="lifecycle_status", value="production.completed", source="phase_b", claim_scope="p-e2e", pipeline_id="p-e2e", correlation_id="c-e2e", window_start=observation["window_start"], window_end=observation["window_end"], source_kind="phase_b_event")
    report = s.lineage_for_pipeline("p-e2e")
    assert evidence["status"] == "validated"
    assert evidence["validation_status"] == "valid"
    assert report["status"] == "complete"
    assert report["resolved_edges"]


def test_rejected_evidence_transition_is_append_only(tmp_path):
    s = store(tmp_path)
    observation = collect(s)
    rejected = EvidenceBuilder(s).build(observation_ids=[observation["record_id"]], source_artifacts={"artifact": object()}, source_record_ids=[], metric_name="impressions", value=1, source="test", claim_scope="v", pipeline_id="pipe-c1", window_start=observation["window_start"], window_end=observation["window_end"], source_kind="youtube_metric")
    assert rejected["status"] == "rejected"
    valid = EvidenceBuilder(s).build(observation_ids=[observation["record_id"]], source_artifacts={"artifact": {"metric": "impressions"}}, source_record_ids=[], metric_name="impressions", value=1, source="test", claim_scope="v", pipeline_id="pipe-c1", window_start=observation["window_start"], window_end=observation["window_end"], source_kind="youtube_metric")
    assert valid["status"] == "validated"
    records = s.evidence_for_pipeline("pipe-c1")
    assert len([item for item in records if item.get("idempotency_key") == rejected["idempotency_key"]]) == 2
    assert records[-1]["status"] == "validated"
