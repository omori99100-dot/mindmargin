from datetime import datetime, timedelta, timezone

from mindmargin.intelligence.c1 import assess_freshness
from mindmargin.intelligence.contracts import DecisionStore, EvidenceRecord, ObservationRecord
from mindmargin.intelligence.metric_registry import MetricRegistry


def test_observation_contract_is_fact_only_and_versioned():
    record = ObservationRecord.create(metric_name="ctr", subject_id="v1", window_start="a", window_end="b", observed_value=2.0)
    payload = record.to_dict()
    assert payload["record_type"] == "observation"
    assert payload["schema_version"] == "c1-1"
    assert "causal_claim" not in payload
    assert "diagnosis" not in payload


def test_evidence_contract_requires_explicit_ids_and_version():
    record = EvidenceRecord.create(observation_ids=["obs-1"], source_artifact_ids=["artifact-1"], metric_name="ctr", value=2.0)
    payload = record.to_dict()
    assert payload["record_type"] == "evidence"
    assert payload["schema_version"] == "c1-1"
    assert payload["observation_ids"] == ["obs-1"]
    assert payload["source_artifact_ids"] == ["artifact-1"]


def test_metric_registry_definitions_are_versioned_and_supported():
    registry = MetricRegistry()
    assert all(item.registry_version == "c1-1" for item in registry.all())
    assert registry.require("ctr").supported_source


def test_freshness_unknown_is_not_valid():
    metric = MetricRegistry().require("ctr")
    result = assess_freshness(metric, "bad timestamp")
    assert result.state == "unknown"
    assert result.seconds is None


def test_c1_idempotency_key_is_deterministic():
    kwargs = dict(metric_name="ctr", subject_id="v1", window_start="a", window_end="b", observed_value=2.0, pipeline_id="p")
    first = ObservationRecord.create(**kwargs)
    second = ObservationRecord.create(**kwargs)
    assert first.idempotency_key == second.idempotency_key
    assert first.record_id != second.record_id


def test_c1_persistence_deduplicates_same_observation(tmp_path):
    store = DecisionStore(tmp_path / "lineage.jsonl")
    kwargs = dict(metric_name="ctr", subject_id="v1", window_start="a", window_end="b", observed_value=2.0, pipeline_id="p")
    first = store.save_observation(ObservationRecord.create(**kwargs))
    second = store.save_observation(ObservationRecord.create(**kwargs))
    assert first["record_id"] == second["record_id"]
    assert len(store.observations_for_pipeline("p")) == 1


def test_allowlist_drops_raw_evidence_payload_at_persistence_boundary(tmp_path):
    store = DecisionStore(tmp_path / "lineage.jsonl")
    record = EvidenceRecord.create(
        observation_ids=["obs-1"], source_artifact_ids=["artifact-1"], metric_name="ctr",
        value={"ctr": 2.0, "raw_provider_response": {"api_key": "SECRET"}},
        provenance={"source_kind": "youtube_metric", "source_locator": "https://example.invalid", "collector_version": "c1-1"},
    )
    row = store.save_evidence(record)
    assert "raw_provider_response" not in row["value"]
    assert "SECRET" not in str(row)
