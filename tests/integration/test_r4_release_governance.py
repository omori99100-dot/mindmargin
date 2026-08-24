"""R4 governance-only checks.

These tests validate metadata and controlled prerequisites. They never create,
approve, or deploy a release candidate and never access production credentials.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DOC = ROOT / "docs" / "R4_RELEASE_CANDIDATE_GOVERNANCE.md"
PREREQUISITES_DOC = ROOT / "docs" / "R4_PRODUCTION_AUTHORIZATION_PREREQUISITES.md"


def _metadata() -> dict[str, str]:
    return {
        "r3_status": "REQUIRES_REVIEW",
        "r4_status": "IN_PROGRESS",
        "candidate_status": "NOT_CREATED",
        "production_authorization": "NOT_GRANTED",
        "production_rollout": "NOT_GRANTED",
        "piper_risk": "ACCEPTED-RISK / DEFERRED-REMEDIATION",
    }


def test_r4_governance_metadata_keeps_candidate_uncreated():
    metadata = _metadata()
    assert metadata["r3_status"] == "REQUIRES_REVIEW"
    assert metadata["r4_status"] == "IN_PROGRESS"
    assert metadata["candidate_status"] == "NOT_CREATED"
    assert metadata["production_authorization"] == "NOT_GRANTED"
    assert metadata["production_rollout"] == "NOT_GRANTED"
    assert metadata["piper_risk"] == "ACCEPTED-RISK / DEFERRED-REMEDIATION"


def test_r4_documents_define_immutable_candidate_requirements_without_candidate_id():
    governance = GOVERNANCE_DOC.read_text(encoding="utf-8")
    prerequisites = PREREQUISITES_DOC.read_text(encoding="utf-8")
    combined = governance + "\n" + prerequisites
    assert "candidate_status`: `NOT_CREATED" in governance
    assert "immutable_reference`: `REQUIRED_BEFORE_PRODUCTION_AUTHORIZATION" in governance
    assert "artifact_manifest" in governance
    assert "artifact_hashes" in governance
    assert "candidate_id`: `UNASSIGNED" in governance
    assert "Production Authorization" in combined
    assert "PRODUCTION_CREDENTIAL" not in combined
    assert "Bearer " not in combined


def test_r4_risk_approval_is_explicitly_pending():
    prerequisites = PREREQUISITES_DOC.read_text(encoding="utf-8")
    governance = GOVERNANCE_DOC.read_text(encoding="utf-8")
    assert "`PENDING`" in prerequisites
    assert "Formal production risk acceptance or separate remediation authorization" in governance
    assert "PiperSettings.model_path" in prerequisites
    assert "does not modify" in governance


def test_r4_security_metadata_is_non_secret_and_sandbox_only():
    metadata = {
        "environment_mode": "sandbox",
        "credentials_used": False,
        "production_traffic": False,
        "candidate_created": False,
    }
    encoded = json.dumps(metadata, sort_keys=True)
    assert "token" not in encoded.lower()
    assert "secret" not in encoded.lower()
    assert "password" not in encoded.lower()
    assert metadata["credentials_used"] is False
    assert metadata["production_traffic"] is False


def test_r4_protected_area_and_stop_rule_are_documented():
    combined = GOVERNANCE_DOC.read_text(encoding="utf-8") + PREREQUISITES_DOC.read_text(encoding="utf-8")
    for protected in ("C1", "C2-P0–P9", "Phase A/B", "DecisionStore/EventLedger", "JSONL/SQLite", "PiperSettings.model_path"):
        assert protected in combined
    assert "BLOCKED — SEPARATE AUTHORIZATION REQUIRED" in combined


def test_r4_artifacts_are_only_metadata_and_tests():
    assert GOVERNANCE_DOC.exists()
    assert PREREQUISITES_DOC.exists()
    assert not (ROOT / "tests" / "r4").exists()
    r4_paths = (GOVERNANCE_DOC, PREREQUISITES_DOC, Path(__file__))
    assert all(path.suffix not in {".db", ".sqlite"} for path in r4_paths)
