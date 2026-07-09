"""Regression tests for is_successful_publish() — the canonical single source of truth.

Every scenario that determines whether an execution_log entry represents a real
YouTube upload is defined here.  If a new edge case is discovered, add it here
FIRST, then update the canonical function in memory.py.
"""
import pytest
from mindmargin.analytics.memory import is_successful_publish


class TestIsSuccessfulPublish:
    """is_successful_publish must return True ONLY when:
    1. pipeline_status == "completed"
    2. video_id is truthy (non-empty string)
    3. error is falsy (empty string or None)
    """

    def test_successful_upload(self):
        """Real upload: completed + video_id + no error → True"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "abc123",
            "error": "",
        }) is True

    def test_pipeline_failed_no_video(self):
        """Pipeline crash: status=failed, no video, no error → False"""
        assert is_successful_publish({
            "pipeline_status": "failed",
            "video_id": "",
            "error": "",
        }) is False

    def test_pipeline_failed_with_error(self):
        """Pipeline crash: status=failed, no video, with error → False"""
        assert is_successful_publish({
            "pipeline_status": "failed",
            "video_id": "",
            "error": "Module crashed",
        }) is False

    def test_pipeline_failed_with_video(self):
        """Pipeline crash but has video (edge): status=failed, has video, no error → False"""
        assert is_successful_publish({
            "pipeline_status": "failed",
            "video_id": "abc123",
            "error": "",
        }) is False

    def test_blocked_by_health_gate(self):
        """Channel health block: completed + no video + no error → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "",
            "error": "",
        }) is False

    def test_blocked_by_daily_cap(self):
        """Daily cap block: completed + no video + error message → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "",
            "error": "daily cap 1 reached (1 published today)",
        }) is False

    def test_publish_skipped(self):
        """Skipped publish: completed + no video + skip message → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "",
            "error": "publish skipped (auto_publish=False)",
        }) is False

    def test_upload_failed_exception(self):
        """Upload exception: completed + no video + error → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "",
            "error": "YouTube API quota exceeded",
        }) is False

    def test_duplicate_detected(self):
        """Duplicate detection: completed + no video + duplicate error → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "",
            "error": "duplicate: already published",
        }) is False

    def test_restart_recovery_with_old_entries(self):
        """Restart recovery: old successful entries should still count → True"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "old_video_001",
            "error": "",
        }) is True

    def test_realistic_mixed_log_blocks_first(self):
        """Mixed log: blocked publish must NOT count toward cap → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "",
            "error": "",
        }) is False

    def test_realistic_mixed_log_success_counts(self):
        """Mixed log: real upload after block must count → True"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "real_video_002",
            "error": "",
        }) is True

    def test_empty_dict(self):
        """Empty dict: missing all keys → False"""
        assert is_successful_publish({}) is False

    def test_none_values(self):
        """None values: video_id=None → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": None,
            "error": "",
        }) is False

    def test_error_is_none(self):
        """error=None: should be treated as falsy → True (with valid video_id)"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "valid_video",
            "error": None,
        }) is True

    def test_unknown_status(self):
        """Unknown pipeline status: should not count → False"""
        assert is_successful_publish({
            "pipeline_status": "running",
            "video_id": "",
            "error": "",
        }) is False

    def test_running_with_video_id(self):
        """Running with video_id (shouldn't happen but guard): → False"""
        assert is_successful_publish({
            "pipeline_status": "running",
            "video_id": "abc123",
            "error": "",
        }) is False

    def test_only_video_id_no_status(self):
        """Only video_id set, no status → False"""
        assert is_successful_publish({
            "video_id": "abc123",
        }) is False

    def test_whitespace_video_id(self):
        """Whitespace video_id should not count → False"""
        assert is_successful_publish({
            "pipeline_status": "completed",
            "video_id": "   ",
            "error": "",
        }) is False
