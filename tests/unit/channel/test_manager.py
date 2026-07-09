import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from mindmargin.channel.manager import ChannelManager
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState


class TestChannelManager:
    @pytest.fixture
    def manager(self):
        mgr = ChannelManager()
        yield mgr

    def test_create(self, manager):
        assert manager is not None

    def test_get_status(self, manager):
        report = manager.get_status()
        assert report.status in ("operational", "degraded")
        assert isinstance(report.active_content, int)
        assert isinstance(report.total_items, int)
        assert isinstance(report.health_score, float)

    def test_get_calendar(self, manager):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock:
            mock.return_value = []
            entries = manager.get_calendar(7)
            assert isinstance(entries, list)

    def test_get_content_empty(self, manager):
        items = manager.get_content()
        assert isinstance(items, list)

    def test_get_content_with_items(self, manager):
        manager.lifecycle.create_item("Manager test", "short", "cat")
        items = manager.get_content()
        assert len(items) >= 1

    def test_advance_content(self, manager):
        item = manager.lifecycle.create_item("Advance test", "long", "cat")
        ok = manager.advance_content(item.content_id, "researching")
        assert ok is True

    def test_advance_content_invalid(self, manager):
        ok = manager.advance_content("nonexistent", "published")
        assert ok is False

    def test_get_governance_rules(self, manager):
        rules = manager.get_governance_rules()
        assert len(rules) >= 7

    def test_toggle_governance_rule(self, manager):
        rules = manager.get_governance_rules()
        first_id = rules[0]["rule_id"]
        result = manager.toggle_governance_rule(first_id)
        assert result is not None

    def test_toggle_nonexistent_rule(self, manager):
        result = manager.toggle_governance_rule("nonexistent_rule")
        assert result is None

    def test_run_daily_cycle(self, manager):
        with patch.object(manager._strategy, "select_topics", return_value=[]), \
             patch.object(manager._strategy, "build_content_plan", return_value=[]), \
             patch.object(manager._calendar, "generate_7_day", return_value=[]), \
             patch.object(manager._calendar, "generate_30_day", return_value=[]), \
             patch.object(manager._calendar, "generate_90_day", return_value=[]):
            result = manager.run_daily_cycle()
            assert result["status"] == "completed"
            assert "steps" in result
            assert len(result["steps"]) >= 4
