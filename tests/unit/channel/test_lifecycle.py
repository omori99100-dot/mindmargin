import tempfile
from pathlib import Path

import pytest

from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState


class TestContentLifecycle:
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

    def test_create_and_get(self, lifecycle):
        item = lifecycle.create_item(
            topic="Test topic",
            fmt="short",
            category="tech",
        )
        assert item.content_id is not None
        assert item.topic == "Test topic"
        assert item.state == ContentState.PLANNED

        fetched = lifecycle.get(item.content_id)
        assert fetched is not None
        assert fetched.topic == "Test topic"

    def test_get_nonexistent(self, lifecycle):
        assert lifecycle.get("nonexistent") is None

    def test_transition_to_valid(self, lifecycle):
        item = lifecycle.create_item("Topic A", "long", "education")
        ok = lifecycle.transition_to(item.content_id, ContentState.RESEARCHING)
        assert ok is True
        fetched = lifecycle.get(item.content_id)
        assert fetched.state == ContentState.RESEARCHING

    def test_transition_to_invalid(self, lifecycle):
        item = lifecycle.create_item("Topic B", "short", "news")
        ok = lifecycle.transition_to(item.content_id, ContentState.PUBLISHED)
        assert ok is False
        fetched = lifecycle.get(item.content_id)
        assert fetched.state == ContentState.PLANNED

    def test_full_state_path(self, lifecycle):
        item = lifecycle.create_item("Full path", "long", "science")
        states = [
            ContentState.RESEARCHING,
            ContentState.WRITING,
            ContentState.PRODUCING,
            ContentState.REVIEWING,
            ContentState.SCHEDULED,
            ContentState.PUBLISHED,
        ]
        for s in states:
            ok = lifecycle.transition_to(item.content_id, s)
            assert ok is True, f"Failed transition to {s}"
        fetched = lifecycle.get(item.content_id)
        assert fetched.state == ContentState.PUBLISHED

    def test_update_item(self, lifecycle):
        item = lifecycle.create_item("Update test", "short", "gaming")
        ok = lifecycle.update_item(item.content_id, confidence=0.95, priority=10)
        assert ok is True
        fetched = lifecycle.get(item.content_id)
        assert fetched.confidence == 0.95
        assert fetched.priority == 10
        assert fetched.updated_at != ""

    def test_update_nonexistent(self, lifecycle):
        ok = lifecycle.update_item("nonexistent", confidence=0.5)
        assert ok is False

    def test_list_all(self, lifecycle):
        lifecycle.create_item("A", "short", "cat1")
        lifecycle.create_item("B", "long", "cat2")
        items = lifecycle.list_all()
        assert len(items) >= 2

    def test_list_by_state(self, lifecycle):
        item = lifecycle.create_item("State filter", "short", "cat")
        lifecycle.transition_to(item.content_id, ContentState.RESEARCHING)
        researching = lifecycle.list_by_state(ContentState.RESEARCHING)
        assert len(researching) >= 1

    def test_count_by_state(self, lifecycle):
        lifecycle.create_item("Count A", "short", "cat")
        lifecycle.create_item("Count B", "long", "cat")
        counts = lifecycle.count_by_state()
        assert counts.get("planned", 0) >= 2

    def test_search_by_topic(self, lifecycle):
        lifecycle.create_item("Python tutorial", "long", "programming")
        lifecycle.create_item("JavaScript basics", "short", "programming")
        results = lifecycle.search_by_topic("Python")
        assert len(results) >= 1
        assert results[0].topic == "Python tutorial"

    def test_search_by_topic_no_match(self, lifecycle):
        results = lifecycle.search_by_topic("zzzznonexistent")
        assert results == []

    def test_transition_nonexistent(self, lifecycle):
        ok = lifecycle.transition_to("nonexistent", ContentState.PUBLISHED)
        assert ok is False

    def test_delete(self, lifecycle):
        item = lifecycle.create_item("Delete me", "short", "cat")
        ok = lifecycle.delete(item.content_id)
        assert ok is True
        assert lifecycle.get(item.content_id) is None

    def test_delete_nonexistent(self, lifecycle):
        ok = lifecycle.delete("nonexistent")
        assert ok is False
