from unittest.mock import patch, MagicMock

import pytest

from mindmargin.executive.observer import Observer, PlatformSnapshot


class TestPlatformSnapshot:
    def test_create(self):
        snap = PlatformSnapshot()
        assert snap.channel_health == 10.0
        assert snap.problems == []
        assert snap.opportunities == []

    def test_to_dict(self):
        snap = PlatformSnapshot(channel_health=8.0, active_content=5)
        d = snap.to_dict()
        assert d["channel_health"] == 8.0
        assert d["active_content"] == 5


class TestObserver:
    @pytest.fixture
    def observer(self):
        return Observer()

    def test_create(self, observer):
        assert observer is not None

    def test_observe_channel(self, observer):
        snap = PlatformSnapshot()
        with patch("mindmargin.channel.manager.ChannelManager") as MockMgr:
            mock_report = MagicMock()
            mock_report.health_score = 8.5
            mock_report.active_content = 3
            mock_report.scheduled_count = 2
            mock_report.published_today = 1
            MockMgr.return_value.get_status.return_value = mock_report
            result = observer.observe_channel(snap)
            assert result.channel_health == 8.5
            assert result.active_content == 3

    def test_observe_channel_error(self, observer):
        snap = PlatformSnapshot()
        with patch("mindmargin.channel.manager.ChannelManager", side_effect=Exception("fail")):
            result = observer.observe_channel(snap)
            assert result.channel_health == 10.0

    def test_observe_workflows(self, observer):
        snap = PlatformSnapshot()
        with patch("mindmargin.core.workflows.WorkflowEngine") as MockEng:
            MockEng.return_value.list_all.return_value = [
                {"state": "completed"},
                {"state": "failed"},
                {"state": "pending"},
            ]
            result = observer.observe_workflows(snap)
            assert result.pending_workflows == 1
            assert result.failed_workflows == 1

    def test_observe_queue(self, observer):
        snap = PlatformSnapshot()
        with patch("mindmargin.core.queue.Queue") as MockQ:
            MockQ.return_value.stats.return_value = {"pending": 5, "running": 2, "dlq": 1}
            result = observer.observe_queue(snap)
            assert result.pending_queue == 5
            assert result.failed_queue == 1

    def test_observe_scheduler(self, observer):
        snap = PlatformSnapshot()
        with patch("mindmargin.core.scheduler.Scheduler") as MockS:
            MockS.return_value.list_all.return_value = [
                {"state": "active"},
                {"state": "active"},
                {"state": "paused"},
            ]
            result = observer.observe_scheduler(snap)
            assert result.scheduler_active == 2
            assert result.scheduler_paused == 1

    def test_observe_providers(self, observer):
        snap = PlatformSnapshot()
        with patch("mindmargin.integrations.manager.ProviderManager") as MockPM:
            MockPM.return_value.list_providers.return_value = ["ollama", "openai"]
            MockPM.return_value.health_check.return_value = True
            result = observer.observe_providers(snap)
            assert result.avg_provider_health == 1.0

    def test_observe_all(self, observer):
        snap = observer.observe_all()
        assert snap.timestamp != ""
        assert isinstance(snap.problems, list)
        assert isinstance(snap.opportunities, list)

    def test_detect_problems_health_critical(self, observer):
        snap = PlatformSnapshot(channel_health=3.0)
        snap = observer._detect_problems(snap)
        assert any("critical" in p for p in snap.problems)

    def test_detect_problems_high_failures(self, observer):
        snap = PlatformSnapshot(failed_workflows=10)
        snap = observer._detect_problems(snap)
        assert any("workflow failures" in p for p in snap.problems)

    def test_detect_problems_no_publish(self, observer):
        snap = PlatformSnapshot(published_today=0, active_content=5)
        snap = observer._detect_problems(snap)
        assert any("nothing published" in p for p in snap.problems)

    def test_detect_opportunities_rich_pool(self, observer):
        snap = PlatformSnapshot(opportunities_count=10)
        snap = observer._detect_opportunities(snap)
        assert any("Rich opportunity" in o for o in snap.opportunities)

    def test_detect_opportunities_strong_health(self, observer):
        snap = PlatformSnapshot(channel_health=9.0)
        snap = observer._detect_opportunities(snap)
        assert any("Strong channel health" in o for o in snap.opportunities)

    def test_detect_opportunities_no_experiments(self, observer):
        snap = PlatformSnapshot(experiments_active=0)
        snap = observer._detect_opportunities(snap)
        assert any("No active experiments" in o for o in snap.opportunities)
