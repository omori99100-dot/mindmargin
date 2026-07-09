import tempfile
import os

import pytest

from mindmargin.channel.governance import GovernanceEngine
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState, GovernanceRuleType, GovernanceRule


class TestGovernanceEngine:
    @pytest.fixture
    def engine(self):
        tmpdir = tempfile.mkdtemp()
        ge = GovernanceEngine(persist_dir=tmpdir)
        yield ge
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_create(self, engine):
        assert engine is not None

    def test_get_default_rules(self, engine):
        rules = engine.get_rules()
        assert len(rules) >= 7

    def test_add_rule(self, engine):
        rule = GovernanceRule(
            rule_id="rule_custom_001",
            rule_type=GovernanceRuleType.MAX_DAILY_UPLOADS,
            name="Custom Max Daily",
            enabled=True,
            config={"max": 5},
        )
        engine.add_rule(rule)
        rules = engine.get_rules()
        assert any(r.rule_id == "rule_custom_001" for r in rules)

    def test_remove_rule(self, engine):
        rule = GovernanceRule(
            rule_id="rule_to_remove",
            rule_type=GovernanceRuleType.MANUAL_LOCK,
            name="To Remove",
            enabled=True,
            config={},
        )
        engine.add_rule(rule)
        ok = engine.remove_rule(rule.rule_id)
        assert ok is True
        rules = engine.get_rules()
        assert all(r.rule_id != rule.rule_id for r in rules)

    def test_remove_nonexistent(self, engine):
        ok = engine.remove_rule("nonexistent_rule")
        assert ok is False

    def test_toggle_rule(self, engine):
        rules = engine.get_rules()
        first = rules[0]
        original = first.enabled
        result = engine.toggle_rule(first.rule_id)
        assert result is not None
        assert result is not original

    def test_toggle_nonexistent(self, engine):
        result = engine.toggle_rule("nonexistent_rule")
        assert result is None

    def test_evaluate_allowed(self, engine):
        item = ContentItem(
            content_id="c001",
            topic="Clean topic",
            format=ContentFormat.SHORT,
            category="tech",
            state=ContentState.PLANNED,
            confidence=0.8,
            opportunity_score=60.0,
        )
        result = engine.evaluate(item)
        assert result.allowed is True

    def test_evaluate_many(self, engine):
        items = [
            ContentItem(f"c{i}", f"Topic {i}", ContentFormat.SHORT, "cat",
                        ContentState.PLANNED, confidence=0.8, opportunity_score=50.0)
            for i in range(5)
        ]
        results = engine.evaluate_many(items)
        assert len(results) >= 1

    def test_get_rule(self, engine):
        rules = engine.get_rules()
        first = rules[0]
        fetched = engine.get_rule(first.rule_id)
        assert fetched is not None
        assert fetched.rule_id == first.rule_id

    def test_get_rule_nonexistent(self, engine):
        assert engine.get_rule("nonexistent") is None
