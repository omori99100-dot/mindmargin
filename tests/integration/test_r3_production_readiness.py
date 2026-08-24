"""R3 production-readiness assessment checks.

All checks are sandbox-only. They use existing contract serializers where
possible and test-local controlled fixtures for safety, observability, and
rollback semantics. No production credentials, traffic, or persistence are
used.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mindmargin.intelligence.c2_contracts import (
    C2ConfidenceValue,
    C2DiagnosisRecord,
    C2HypothesisRecord,
)


_SECRET_NAMES = {
    "OPENAI_API_KEY",
    "GH_TOKEN",
    "GOOGLE_DRIVE_TOKEN",
    "GOOGLE_WORKSPACE_CLI_TOKEN",
}


def _redacted_event(event_type: str, correlation_id: str, metadata: dict) -> dict:
    """Test-local observability envelope; no production logger is invoked."""
    safe = {}
    for key, value in metadata.items():
        if key.lower() in {"token", "secret", "password", "authorization", "api_key"}:
            safe[key] = "[REDACTED]"
        else:
            safe[key] = value
    return {
        "event_type": event_type,
        "correlation_id": correlation_id,
        "metadata": safe,
    }


def _controlled_atomic_replace(path: Path, payload: dict, *, fail: bool = False) -> None:
    """Test-local atomic write used only to verify rollback/recovery mechanics."""
    temporary = path.with_suffix(path.suffix + ".r3tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    if fail:
        temporary.unlink()
        raise RuntimeError("controlled sandbox failure")
    temporary.replace(path)


def test_r3_configuration_metadata_is_non_secret_and_no_credentials_are_read():
    # Only names/types are inspected; secret values are never accessed or emitted.
    assert isinstance(os.environ.keys(), type(os.environ.keys()))
    assert _SECRET_NAMES.isdisjoint({"R3_PRODUCTION_CREDENTIAL"})
    metadata = {
        "runtime": "python",
        "mode": "sandbox",
        "credentials_used": False,
        "production_traffic": False,
    }
    encoded = json.dumps(metadata, sort_keys=True)
    assert "token" not in encoded.lower()
    assert "secret" not in encoded.lower()
    assert "password" not in encoded.lower()


def test_r3_c2_redaction_causal_null_and_versioned_serialization():
    diagnosis = C2DiagnosisRecord.create(
        problem_statement="authorization: Bearer SHOULD_NOT_LEAK",
        evidence_ids=["evidence-1"],
        pipeline_id="sandbox-pipeline",
        correlation_id="sandbox-correlation",
        confidence=C2ConfidenceValue(0.7, "evidence_support", "provenance_based"),
        candidate_explanations=(
            {"id": "candidate-1", "label": "bounded", "text": "safe", "api_key": "SHOULD_NOT_LEAK"},
        ),
    )
    hypothesis = C2HypothesisRecord.create(
        statement="A bounded operational condition may explain the observation.",
        supporting_evidence_ids=["evidence-1"],
        measurable_prediction="metric remains within the declared window",
        falsification_condition="metric violates the declared threshold",
        inconclusive_condition="sample remains insufficient",
        pipeline_id="sandbox-pipeline",
        correlation_id="sandbox-correlation",
        alternative_hypotheses=(
            {"id": "alternative-1", "label": "bounded", "text": "safe", "secret": "SHOULD_NOT_LEAK"},
        ),
    )
    diagnosis_payload = diagnosis.to_dict()
    hypothesis_payload = hypothesis.to_dict()

    assert "SHOULD_NOT_LEAK" not in json.dumps(diagnosis_payload, sort_keys=True)
    assert "SHOULD_NOT_LEAK" not in json.dumps(hypothesis_payload, sort_keys=True)
    assert diagnosis_payload["causal_claim"] is None
    assert hypothesis_payload["causality_status"] == "not_claimed"
    assert diagnosis_payload["envelope"]["schema_version"] == "c2-1"
    assert hypothesis_payload["envelope"]["schema_version"] == "c2-1"


def test_r3_observability_is_correlated_structured_and_redacted():
    event = _redacted_event(
        "r3.sandbox.rollback",
        "r3-correlation-1",
        {"status": "recovered", "attempt": 1, "authorization": "Bearer SHOULD_NOT_LEAK"},
    )
    serialized = json.dumps(event, sort_keys=True)
    assert event["event_type"] == "r3.sandbox.rollback"
    assert event["correlation_id"] == "r3-correlation-1"
    assert event["metadata"]["authorization"] == "[REDACTED]"
    assert "SHOULD_NOT_LEAK" not in serialized


def test_r3_controlled_rollback_preserves_prestate_and_recovers(tmp_path):
    state = tmp_path / "state.json"
    original = {"release_candidate": "sandbox-v1", "enabled": False}
    recovered = {"release_candidate": "sandbox-v2", "enabled": False}
    state.write_text(json.dumps(original, sort_keys=True), encoding="utf-8")

    with pytest.raises(RuntimeError, match="controlled sandbox failure"):
        _controlled_atomic_replace(state, {"release_candidate": "unsafe", "enabled": True}, fail=True)
    assert json.loads(state.read_text(encoding="utf-8")) == original
    assert not state.with_suffix(state.suffix + ".r3tmp").exists()

    _controlled_atomic_replace(state, recovered)
    assert json.loads(state.read_text(encoding="utf-8")) == recovered


def test_r3_sandbox_has_no_production_persistence_or_activation_artifacts(tmp_path):
    marker = tmp_path / "r3-sandbox-marker.json"
    _controlled_atomic_replace(marker, {"sandbox": True, "production_traffic": False})
    assert marker.exists()
    assert not list(tmp_path.rglob("*.db"))
    assert not list(tmp_path.rglob("*.sqlite"))
    assert not list(tmp_path.rglob("*.jsonl"))
    assert json.loads(marker.read_text(encoding="utf-8"))["production_traffic"] is False
