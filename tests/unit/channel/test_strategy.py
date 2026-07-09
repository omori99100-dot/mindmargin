import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState
from mindmargin.channel.strategy import ChannelStrategy


class TestChannelStrategy:
    @pytest.fixture
    def lifecycle(self):
        tmpdir = tempfile.mkdtemp()
        lc = ContentLifecycle(persist_dir=tmpdir)
        yield lc
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    @pytest.fixture
    def strategy(self, lifecycle):
        return ChannelStrategy(lifecycle=lifecycle)

    def test_create(self, strategy):
        assert strategy is not None

    def test_select_topics_empty(self, strategy):
        with patch("mindmargin.channel.strategy.get_top_opportunities") as mock_opp:
            mock_opp.return_value = []
            topics = strategy.select_topics(limit=10)
            assert isinstance(topics, list)
            assert topics == []

    def test_detect_duplicates_empty(self, strategy):
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_ph, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_el:
            mock_ph.return_value = []
            mock_el.return_value = []
            dups = strategy.detect_duplicates("Python tips")
            assert isinstance(dups, list)
            assert len(dups) == 0

    def test_detect_duplicates_in_planned(self, lifecycle, strategy):
        lifecycle.create_item("Python tips", "short", "programming")
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_ph, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_el:
            mock_ph.return_value = []
            mock_el.return_value = []
            dups = strategy.detect_duplicates("Python tips")
            assert len(dups) == 1
            assert dups[0]["source"] == "planned_content"

    def test_estimate_format_short(self, strategy):
        opp = {"opportunity_score": 30, "evergreen_score": 0.1, "confidence": 0.3, "novelty": 0.1}
        fmt = strategy.estimate_format(opp)
        assert fmt == ContentFormat.SHORT

    def test_estimate_format_long(self, strategy):
        opp = {"opportunity_score": 80, "evergreen_score": 0.8, "confidence": 0.9, "novelty": 0.7}
        fmt = strategy.estimate_format(opp)
        assert fmt == ContentFormat.LONG

    def test_assign_category(self, strategy):
        cat = strategy.assign_category("Business failure of a startup")
        assert cat == "business_failure"

    def test_assign_category_fallback(self, strategy):
        cat = strategy.assign_category("Random unrelated topic xyz")
        assert cat in ["business_failure", "corruption", "financial_crisis", "startup_failure",
                        "tech_disruption", "fraud", "regulatory_failure", "industry_disruption",
                        "cultural_phenomenon", "legal_battle", "scandal", "market_collapse"]

    def test_build_content_plan_empty(self, strategy):
        items = strategy.build_content_plan([])
        assert items == []

    def test_build_content_plan_with_opportunities(self, strategy):
        opps = [
            {"topic": "AI News", "opportunity_score": 85.0, "confidence": 0.8},
            {"topic": "Python Tips", "opportunity_score": 72.0, "confidence": 0.7},
        ]
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_ph, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_el:
            mock_ph.return_value = []
            mock_el.return_value = []
            items = strategy.build_content_plan(opps)
        assert len(items) == 2
        assert items[0].topic == "AI News"
        assert items[0].state == ContentState.PLANNED
