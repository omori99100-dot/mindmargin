import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState
from mindmargin.channel.review import ContentReview


class TestContentReview:
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
    def review(self, lifecycle):
        return ContentReview(lifecycle=lifecycle)

    def test_create(self, review):
        assert review is not None

    def test_review_item_not_found(self, review):
        result = review.review_item("nonexistent")
        assert result["status"] == "failed"
        assert result["error"] == "content_not_found"

    def test_review_item_high_quality(self, lifecycle, review):
        item = lifecycle.create_item(
            topic="Great Python Tutorial Guide",
            fmt="long",
            category="programming",
            confidence=0.9,
            opportunity_score=80.0,
        )
        result = review.review_item(item.content_id)
        assert result["status"] in ("approved", "flagged")
        assert result["total_checks"] >= 4

    def test_review_item_low_confidence(self, lifecycle, review):
        item = lifecycle.create_item(
            topic="Short topic ab",
            fmt="short",
            category="cat",
            confidence=0.1,
            opportunity_score=10.0,
        )
        result = review.review_item(item.content_id)
        assert result["status"] == "flagged"

    def test_auto_approve_high(self, lifecycle, review):
        item = lifecycle.create_item(
            topic="Excellent topic for education",
            fmt="long",
            category="education",
            confidence=0.85,
            opportunity_score=75.0,
        )
        ok = review.auto_approve(item)
        assert ok is True

    def test_auto_approve_low(self, lifecycle, review):
        item = lifecycle.create_item(
            topic="Weak topic content",
            fmt="short",
            category="misc",
            confidence=0.5,
            opportunity_score=30.0,
        )
        ok = review.auto_approve(item)
        assert ok is False

    def test_flag_for_review(self, lifecycle, review):
        item = lifecycle.create_item(
            topic="Medium topic content here",
            fmt="short",
            category="tech",
            confidence=0.6,
            opportunity_score=45.0,
        )
        flagged = review.flag_for_review(item)
        assert flagged is True

    def test_checks_produced(self, lifecycle, review):
        item = lifecycle.create_item(
            topic="Check test content for review",
            fmt="long",
            category="science",
            confidence=0.75,
            opportunity_score=55.0,
        )
        result = review.review_item(item.content_id)
        check_names = [c["name"] for c in result["checks"]]
        assert "topic_quality" in check_names
        assert "confidence" in check_names
        assert "opportunity" in check_names
