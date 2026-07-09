import tempfile
from pathlib import Path

import pytest

from mindmargin.executive.policy import PolicyConfig, PolicyEngine, PolicyType, PRESETS


class TestPolicyConfig:
    def test_default_config(self):
        config = PolicyConfig()
        assert config.policy_type == PolicyType.BALANCED
        assert config.publishing_frequency_hours == 24
        assert config.risk_tolerance == 0.5

    def test_to_dict(self):
        config = PolicyConfig(policy_type=PolicyType.AGGRESSIVE, publishing_frequency_hours=12)
        d = config.to_dict()
        assert d["policy_type"] == "aggressive"
        assert d["publishing_frequency_hours"] == 12

    def test_from_dict(self):
        d = {"policy_type": "conservative", "publishing_frequency_hours": 48}
        config = PolicyConfig.from_dict(d)
        assert config.policy_type == PolicyType.CONSERVATIVE
        assert config.publishing_frequency_hours == 48

    def test_presets_exist(self):
        for pt in PolicyType:
            if pt == PolicyType.CUSTOM:
                continue
            assert pt in PRESETS

    def test_conservative_preset(self):
        p = PRESETS[PolicyType.CONSERVATIVE]
        assert p.enable_auto_publish is False
        assert p.risk_tolerance == 0.2

    def test_aggressive_preset(self):
        p = PRESETS[PolicyType.AGGRESSIVE]
        assert p.publishing_frequency_hours == 12
        assert p.risk_tolerance == 0.8


class TestPolicyEngine:
    @pytest.fixture
    def engine(self):
        tmpdir = tempfile.mkdtemp()
        e = PolicyEngine(persist_dir=tmpdir)
        yield e
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_default_is_balanced(self, engine):
        config = engine.get_config()
        assert config.policy_type == PolicyType.BALANCED

    def test_set_policy(self, engine):
        config = engine.set_policy(PolicyType.AGGRESSIVE)
        assert config.policy_type == PolicyType.AGGRESSIVE
        assert config.publishing_frequency_hours == 12

    def test_update_config(self, engine):
        config = engine.update_config(publishing_frequency_hours=12)
        assert config.publishing_frequency_hours == 12

    def test_should_publish_balanced(self, engine):
        assert engine.should_publish(confidence=0.8, hours_since_last=24) is True
        assert engine.should_publish(confidence=0.8, hours_since_last=10) is False
        assert engine.should_publish(confidence=0.5, hours_since_last=24) is False

    def test_should_publish_disabled(self, engine):
        engine.set_policy(PolicyType.CONSERVATIVE)
        assert engine.should_publish(confidence=0.9, hours_since_last=48) is False

    def test_should_experiment(self, engine):
        assert engine.should_experiment(hours_since_last=168) is True
        assert engine.should_experiment(hours_since_last=50) is False

    def test_max_concurrent(self, engine):
        assert engine.max_concurrent() == 3

    def test_risk_tolerance(self, engine):
        assert engine.risk_tolerance() == 0.5

    def test_budget_pct(self, engine):
        assert engine.budget_pct() == 50.0

    def test_get_all_preset_names(self, engine):
        names = engine.get_all_preset_names()
        assert "conservative" in names
        assert "aggressive" in names

    def test_persistence(self):
        tmpdir = tempfile.mkdtemp()
        try:
            e1 = PolicyEngine(persist_dir=tmpdir)
            e1.set_policy(PolicyType.GROWTH)
            e2 = PolicyEngine(persist_dir=tmpdir)
            assert e2.get_config().policy_type == PolicyType.GROWTH
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
