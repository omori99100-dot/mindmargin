import json
import tempfile
from unittest.mock import MagicMock

import pytest

from mindmargin.core.recovery import RecoveryManager, RecoveryReport


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        m = RecoveryManager(persist_dir=tmpdir)
        yield m


class TestRecoveryManager:
    def test_initial_report(self, manager):
        report = manager.recover_all()
        assert report.recovered_queues == 0
        assert report.recovered_schedules == 0
        assert report.recovered_workflows == 0
        assert len(report.errors) == 0

    def test_recover_queue(self, manager):
        mock_q = MagicMock()
        mock_q.recover.return_value = 5
        manager.bind_queue(mock_q)
        assert manager.recover_queue() == 5
        mock_q.recover.assert_called_once()

    def test_recover_scheduler(self, manager):
        mock_s = MagicMock()
        mock_s.recover.return_value = 3
        manager.bind_scheduler(mock_s)
        assert manager.recover_scheduler() == 3
        mock_s.recover.assert_called_once()

    def test_recover_workflows(self, manager):
        mock_w = MagicMock()
        mock_w.recover.return_value = 7
        manager.bind_workflow(mock_w)
        assert manager.recover_workflows() == 7
        mock_w.recover.assert_called_once()

    def test_recover_all_calls_all(self, manager):
        mock_q = MagicMock()
        mock_q.recover.return_value = 2
        mock_s = MagicMock()
        mock_s.recover.return_value = 4
        mock_w = MagicMock()
        mock_w.recover.return_value = 6
        manager.bind_queue(mock_q)
        manager.bind_scheduler(mock_s)
        manager.bind_workflow(mock_w)
        report = manager.recover_all()
        assert report.recovered_queues == 2
        assert report.recovered_schedules == 4
        assert report.recovered_workflows == 6

    def test_recover_all_errors_isolated(self, manager):
        mock_q = MagicMock()
        mock_q.recover.side_effect = ValueError("queue error")
        mock_s = MagicMock()
        mock_s.recover.return_value = 3
        manager.bind_queue(mock_q)
        manager.bind_scheduler(mock_s)
        report = manager.recover_all()
        assert report.recovered_queues == 0
        assert report.recovered_schedules == 3
        assert any("queue" in e.lower() for e in report.errors)

    def test_simulate_crash_and_recover(self, manager):
        mock_q = MagicMock()
        mock_q.recover.return_value = 1
        manager.bind_queue(mock_q)
        report = manager.simulate_crash_and_recover()
        assert report.recovered_queues == 1

    def test_last_report_none(self, manager):
        assert manager.last_report() is None

    def test_last_report_after_recovery(self, manager):
        manager.recover_all()
        report = manager.last_report()
        assert report is not None
        assert report.recovered_queues == 0

    def test_list_reports(self, manager):
        manager.recover_all()
        manager.recover_all()
        reports = manager.list_reports()
        assert len(reports) == 2

    def test_recovery_report_to_dict(self):
        report = RecoveryReport(
            recovered_queues=3,
            recovered_schedules=2,
            recovered_workflows=1,
            dlq_items_restored=0,
            errors=["something went wrong"],
            timestamp="2026-01-01T00:00:00",
        )
        d = report.to_dict()
        assert d["recovered_queues"] == 3
        assert d["errors"] == ["something went wrong"]

    def test_recovery_report_saved_to_disk(self, manager):
        report = manager.recover_all()
        reports = sorted(manager._persist_dir.glob("recovery_*.json"))
        assert len(reports) == 1
        data = json.loads(reports[0].read_text(encoding="utf-8"))
        assert data["recovered_queues"] == 0

    def test_bind_none_does_not_crash(self, manager):
        manager.bind_queue(None)
        manager.bind_scheduler(None)
        manager.bind_workflow(None)
        report = manager.recover_all()
        assert report.recovered_queues == 0
        assert report.recovered_schedules == 0
        assert report.recovered_workflows == 0


class TestRecoveryEdgeCases:
    def test_recover_queue_exception(self, manager):
        mock_q = MagicMock()
        mock_q.recover.side_effect = ValueError("queue error")
        manager.bind_queue(mock_q)
        assert manager.recover_queue() == 0

    def test_recover_scheduler_exception(self, manager):
        mock_s = MagicMock()
        mock_s.recover.side_effect = ValueError("scheduler error")
        manager.bind_scheduler(mock_s)
        assert manager.recover_scheduler() == 0

    def test_recover_workflow_exception(self, manager):
        mock_w = MagicMock()
        mock_w.recover.side_effect = ValueError("workflow error")
        manager.bind_workflow(mock_w)
        assert manager.recover_workflows() == 0

    def test_recover_queue_no_impl(self, manager):
        assert manager.recover_queue() == 0

    def test_recover_scheduler_no_impl(self, manager):
        assert manager.recover_scheduler() == 0

    def test_recover_workflows_no_impl(self, manager):
        assert manager.recover_workflows() == 0

    def test_scheduler_recover_all_error(self, manager):
        mock_s = MagicMock()
        mock_s.recover.side_effect = ValueError("sched error")
        manager.bind_scheduler(mock_s)
        report = manager.recover_all()
        assert any("scheduler" in e.lower() for e in report.errors)

    def test_workflow_recover_all_error(self, manager):
        mock_w = MagicMock()
        mock_w.recover.side_effect = ValueError("wf error")
        manager.bind_workflow(mock_w)
        report = manager.recover_all()
        assert any("workflow" in e.lower() for e in report.errors)

    def test_last_report_corrupt(self, manager):
        bad_file = manager._persist_dir / "recovery_corrupt.json"
        bad_file.write_text("not json")
        assert manager.last_report() is None

    def test_list_reports_skips_corrupt(self, manager):
        manager.recover_all()
        bad_file = manager._persist_dir / "recovery_corrupt.json"
        bad_file.write_text("not json")
        reports = manager.list_reports()
        assert len(reports) == 1
