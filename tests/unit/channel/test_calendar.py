import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mindmargin.channel.calendar import PublishingCalendar
from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState


class TestPublishingCalendar:
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
    def calendar(self, lifecycle):
        return PublishingCalendar(lifecycle=lifecycle)

    def test_create(self, calendar):
        assert calendar is not None

    def test_generate_7_day_empty(self, calendar):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock:
            mock.return_value = []
            entries = calendar.generate_7_day()
            assert isinstance(entries, list)
            assert len(entries) <= 7

    def test_generate_30_day_empty(self, calendar):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock:
            mock.return_value = []
            entries = calendar.generate_30_day()
            assert isinstance(entries, list)

    def test_generate_with_planned_content(self, lifecycle, calendar):
        for i in range(3):
            lifecycle.create_item(f"Topic {i}", "short", "tech")
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock:
            mock.return_value = []
            entries = calendar.generate_7_day()
            assert isinstance(entries, list)

    def test_entries_have_required_fields(self, lifecycle, calendar):
        lifecycle.create_item("Cal test", "long", "science")
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock:
            mock.return_value = []
            entries = calendar.generate_7_day()
            if entries:
                e = entries[0]
                assert hasattr(e, "topic")
                assert hasattr(e, "format")
                assert hasattr(e, "publish_time")
