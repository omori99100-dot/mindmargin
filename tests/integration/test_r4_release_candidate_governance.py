"""Direct checks for the bounded R4 release-candidate governance scope."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ROOT / "release_candidates"


def _candidate() -> Path:
    candidates = sorted(p for p in CANDIDATES.iterdir() if p.is_dir())
    assert len(candidates) == 1
    return candidates[0]


def test_candidate_is_immutable_and_traceable():
    candidate = _candidate()
    source = json.loads((candidate / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    governance = json.loads((candidate / "GOVERNANCE_RECORD.json").read_text(encoding="utf-8"))
    assert source["candidate_id"] == candidate.name
    assert source["candidate_status"] == "CREATED_IMMUTABLE_SNAPSHOT"
    assert source["source_reference"]["git_head"]
    assert source["included_file_count"] == len(source["files"])
    assert governance["immutable_reference"].endswith("release_snapshot.tar.gz")
    assert governance["workspace_is_release_candidate"] is False
    for path in candidate.rglob("*"):
        if path.is_file():
            assert os.stat(path).st_mode & 0o222 == 0


def test_manifest_and_artifact_hashes_match():
    candidate = _candidate()
    source = json.loads((candidate / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    for entry in source["files"]:
        assert len(entry["sha256"]) == 64
        assert entry["size"] >= 0
    hash_lines = (candidate / "ARTIFACT_MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    assert hash_lines
    for line in hash_lines:
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == digest


def test_risk_acceptance_is_formal_and_no_production_authorization():
    candidate = _candidate()
    risk = json.loads((candidate / "RISK_ACCEPTANCE.json").read_text(encoding="utf-8"))
    governance = json.loads((candidate / "GOVERNANCE_RECORD.json").read_text(encoding="utf-8"))
    assert risk["risk_id"] == "R4-RISK-PIPER-MODEL-PATH"
    assert risk["status"] == "ACCEPTED-RISK"
    assert risk["remediation"] == "DEFERRED"
    assert risk["accepted_by_role"]
    assert risk["conditions"]
    assert risk["expiry"]
    assert governance["production_authorization"] == "NOT_GRANTED"
    assert governance["production_rollout"] == "NOT_GRANTED"


def test_snapshot_excludes_credentials_persistence_and_production_activation():
    candidate = _candidate()
    with tarfile.open(candidate / "release_snapshot.tar.gz", "r:gz") as tar:
        names = tar.getnames()
    lowered = "\n".join(names).lower()
    forbidden_names = ("auth_url.txt", ".env", "mindmargin.db", ".sqlite", "token", "secret", "credential")
    assert not any(forbidden in lowered for forbidden in forbidden_names)
    assert "production/" not in lowered
    assert "publish/" not in lowered
    assert candidate.name.startswith("r4-rc-")
