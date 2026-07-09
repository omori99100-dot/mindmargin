import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState
from mindmargin.channel.publisher import ChannelPublisher


class TestChannelPublisher:
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
    def publisher(self, lifecycle):
        return ChannelPublisher(lifecycle=lifecycle)

    def test_create(self, publisher):
        assert publisher is not None

    def test_publish_not_found(self, publisher):
        result = publisher.publish("nonexistent")
        assert result["status"] == "failed"
        assert result["error"] == "content_not_found"

    def test_mark_scheduled(self, lifecycle, publisher):
        item = lifecycle.create_item("Scheduled topic", "short", "cat")
        lifecycle.transition_to(item.content_id, ContentState.RESEARCHING)
        lifecycle.transition_to(item.content_id, ContentState.WRITING)
        lifecycle.transition_to(item.content_id, ContentState.PRODUCING)
        lifecycle.transition_to(item.content_id, ContentState.REVIEWING)
        ok = publisher.mark_scheduled(item.content_id, publish_at="2026-07-10T14:00:00")
        assert ok is True
        fetched = lifecycle.get(item.content_id)
        assert fetched.state == ContentState.SCHEDULED

    def test_mark_published(self, lifecycle, publisher):
        item = lifecycle.create_item("Publish topic", "long", "cat")
        lifecycle.transition_to(item.content_id, ContentState.RESEARCHING)
        lifecycle.transition_to(item.content_id, ContentState.WRITING)
        lifecycle.transition_to(item.content_id, ContentState.PRODUCING)
        lifecycle.transition_to(item.content_id, ContentState.REVIEWING)
        lifecycle.transition_to(item.content_id, ContentState.SCHEDULED)
        ok = publisher.mark_published(item.content_id, video_id="vid_123")
        assert ok is True
        fetched = lifecycle.get(item.content_id)
        assert fetched.state == ContentState.PUBLISHED
        assert fetched.video_id == "vid_123"

    def test_mark_published_nonexistent(self, publisher):
        ok = publisher.mark_published("nonexistent")
        assert ok is False

    def test_update_playlists(self, lifecycle, publisher):
        item = lifecycle.create_item("Playlist topic", "short", "cat")
        ok = publisher.update_playlists(item.content_id, ["pl_001", "pl_002"])
        assert ok is True
        fetched = lifecycle.get(item.content_id)
        assert len(fetched.playlist_ids) == 2

    def test_publish_wrong_state(self, lifecycle, publisher):
        item = lifecycle.create_item("Archived topic", "short", "cat")
        lifecycle.transition_to(item.content_id, ContentState.ARCHIVED)
        result = publisher.publish(item.content_id)
        assert result["status"] == "failed"
