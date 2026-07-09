"""Unit tests for mindmargin.integrations.secrets.manager."""

import json
import os
import pytest
from pathlib import Path


@pytest.fixture
def tmp_secrets_dir(tmp_path):
    return str(tmp_path / "integrations" / "secrets")


@pytest.fixture
def sm(tmp_secrets_dir):
    from mindmargin.integrations.secrets.manager import SecretManager
    return SecretManager(persist_dir=str(Path(tmp_secrets_dir).parent))


class TestSecretManagerCRUD:
    def test_get_from_env(self, sm, monkeypatch):
        monkeypatch.setenv("TEST_SECRET_XYZ", "env_value")
        assert sm.get("TEST_SECRET_XYZ") == "env_value"

    def test_get_from_store(self, sm):
        sm.set("MY_KEY", "my_value")
        assert sm.get("MY_KEY") == "my_value"

    def test_env_takes_priority(self, sm, monkeypatch):
        sm.set("PRIORITY_KEY", "store_val")
        monkeypatch.setenv("PRIORITY_KEY", "env_val")
        assert sm.get("PRIORITY_KEY") == "env_val"

    def test_get_missing_returns_none(self, sm):
        assert sm.get("NONEXISTENT_KEY") is None

    def test_set_and_persist(self, sm, tmp_secrets_dir):
        sm.set("PERSIST_KEY", "persist_val")
        sm2 = sm.__class__(persist_dir=str(Path(tmp_secrets_dir).parent))
        assert sm2.get("PERSIST_KEY") == "persist_val"

    def test_set_many(self, sm):
        sm.set_many({"A": "1", "B": "2"})
        assert sm.get("A") == "1"
        assert sm.get("B") == "2"

    def test_delete_existing(self, sm):
        sm.set("DEL_KEY", "val")
        assert sm.delete("DEL_KEY") is True
        assert sm.get("DEL_KEY") is None

    def test_delete_nonexistent(self, sm):
        assert sm.delete("NO_SUCH_KEY") is False

    def test_is_configured(self, sm, monkeypatch):
        assert sm.is_configured("NONEXISTENT") is False
        sm.set("CFG_KEY", "1")
        assert sm.is_configured("CFG_KEY") is True

    def test_require_raises(self, sm):
        with pytest.raises(ValueError, match="not configured"):
            sm.require("MISSING_REQ")

    def test_require_returns_value(self, sm):
        sm.set("REQ_KEY", "req_val")
        assert sm.require("REQ_KEY") == "req_val"


class TestSecretManagerValidation:
    def test_validate_all_missing(self, sm):
        result = sm.validate()
        assert result["valid"] is False
        assert len(result["missing_required"]) == 3

    def test_validate_with_youtube_creds(self, sm):
        sm.set("YOUTUBE_CLIENT_ID", "id")
        sm.set("YOUTUBE_CLIENT_SECRET", "secret")
        sm.set("YOUTUBE_REFRESH_TOKEN", "token")
        result = sm.validate()
        assert result["valid"] is True
        assert result["missing_required"] == []

    def test_list_all_returns_all_keys(self, sm):
        result = sm.list_all()
        assert "YOUTUBE_CLIENT_ID" in result
        assert "TELEGRAM_BOT_TOKEN" in result
        assert result["YOUTUBE_CLIENT_ID"] == "missing"

    def test_list_all_shows_set(self, sm):
        sm.set("YOUTUBE_CLIENT_ID", "x")
        result = sm.list_all()
        assert result["YOUTUBE_CLIENT_ID"] == "set"
