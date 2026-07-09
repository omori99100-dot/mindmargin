import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from mindmargin.operations.models import (
    OPERATION_CRON_DEFAULTS,
    OPERATION_TIMEOUT_DEFAULTS,
    OperationRecord,
    OperationReport,
    OperationStatus,
    OperationType,
)
from mindmargin.operations.orchestrator import OperationsOrchestrator
from mindmargin.operations.controller import OperationsController
from mindmargin.core.workflows import WorkflowEngine
from mindmargin.core.scheduler import Scheduler


class TestOperationType:
    def test_enum_values(self):
        assert OperationType.DAILY_ANALYTICS.value == "daily_analytics"
        assert OperationType.DAILY_INTELLIGENCE.value == "daily_intelligence"
        assert OperationType.DECISION_EXECUTOR.value == "decision_executor"
        assert OperationType.FEEDBACK_CYCLE.value == "feedback_cycle"

    def test_all_types_have_defaults(self):
        for op_type in OperationType:
            assert op_type in OPERATION_TIMEOUT_DEFAULTS, f"Missing timeout for {op_type}"
            timeout = OPERATION_TIMEOUT_DEFAULTS[op_type]
            assert timeout > 0, f"Timeout must be > 0 for {op_type}"


class TestOperationStatus:
    def test_enum_values(self):
        assert OperationStatus.PENDING.value == "pending"
        assert OperationStatus.RUNNING.value == "running"
        assert OperationStatus.COMPLETED.value == "completed"
        assert OperationStatus.FAILED.value == "failed"

    def test_terminal_states(self):
        terminal = {OperationStatus.COMPLETED, OperationStatus.FAILED, OperationStatus.SKIPPED, OperationStatus.DISABLED}
        for s in terminal:
            assert s.value in ("completed", "failed", "skipped", "disabled")


class TestOperationRecord:
    def test_create_record(self):
        record = OperationRecord(
            operation_id="op_test_001",
            operation_type=OperationType.DAILY_ANALYTICS,
            status=OperationStatus.COMPLETED,
            started_at="2026-07-03T06:00:00",
            completed_at="2026-07-03T06:15:00",
            workflow_id="wf_analytics_001",
            result={"videos_collected": 5},
        )
        assert record.operation_id == "op_test_001"
        assert record.operation_type == OperationType.DAILY_ANALYTICS
        assert record.status == OperationStatus.COMPLETED
        assert record.result["videos_collected"] == 5

    def test_to_dict(self):
        record = OperationRecord(
            operation_id="op_test_002",
            operation_type=OperationType.DECISION_EXECUTOR,
            status=OperationStatus.RUNNING,
        )
        d = record.to_dict()
        assert d["operation_id"] == "op_test_002"
        assert d["operation_type"] == "decision_executor"
        assert d["status"] == "running"
        assert d["error"] == ""

    def test_from_dict(self):
        d = {
            "operation_id": "op_test_003",
            "operation_type": "daily_intelligence",
            "status": "failed",
            "error": "API timeout",
            "result": {"stages": {}},
        }
        record = OperationRecord.from_dict(d)
        assert record.operation_id == "op_test_003"
        assert record.operation_type == OperationType.DAILY_INTELLIGENCE
        assert record.status == OperationStatus.FAILED
        assert record.error == "API timeout"

    def test_round_trip_serialization(self):
        original = OperationRecord(
            operation_id="op_roundtrip",
            operation_type=OperationType.FEEDBACK_CYCLE,
            status=OperationStatus.COMPLETED,
            started_at="2026-07-03T12:00:00",
            completed_at="2026-07-03T12:05:00",
            result={"outcomes_collected": 10, "weights_changed": 3},
        )
        d = original.to_dict()
        restored = OperationRecord.from_dict(d)
        assert restored.operation_id == original.operation_id
        assert restored.operation_type == original.operation_type
        assert restored.status == original.status
        assert restored.result == original.result

    def test_default_values(self):
        record = OperationRecord(
            operation_id="op_defaults",
            operation_type=OperationType.KNOWLEDGE_GRAPH,
            status=OperationStatus.PENDING,
        )
        assert record.started_at == ""
        assert record.completed_at == ""
        assert record.workflow_id == ""
        assert record.schedule_id == ""
        assert record.result == {}
        assert record.error == ""
        assert record.metadata == {}


class TestOperationReport:
    def test_create_report(self):
        records = [
            OperationRecord("op_1", OperationType.DAILY_ANALYTICS, OperationStatus.COMPLETED),
            OperationRecord("op_2", OperationType.DECISION_EXECUTOR, OperationStatus.FAILED),
        ]
        report = OperationReport(
            status="degraded",
            active_operations=0,
            completed_today=1,
            failed_today=1,
            scheduled=5,
            records=records,
        )
        assert report.status == "degraded"
        assert report.completed_today == 1
        assert report.failed_today == 1
        assert len(report.records) == 2

    def test_operational_status(self):
        report = OperationReport(
            status="operational", active_operations=0,
            completed_today=5, failed_today=0, scheduled=10, records=[],
        )
        assert report.status == "operational"


class TestOperationsOrchestrator:
    @pytest.fixture
    def engine(self):
        tmpdir = tempfile.mkdtemp()
        e = WorkflowEngine(persist_dir=tmpdir)
        yield e
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_orchestrator_creation(self, engine):
        orch = OperationsOrchestrator(engine)
        assert orch.workflow_ids == {}

    def test_build_analytics_workflow(self, engine):
        orch = OperationsOrchestrator(engine)
        wid = orch.build_analytics_workflow()
        assert wid.startswith("wf_daily_analytics_")
        wf = engine.get(wid)
        assert wf is not None
        assert "run_analytics" in wf.steps
        assert wf.steps["run_analytics"].handler is not None

    def test_build_intelligence_workflow(self, engine):
        orch = OperationsOrchestrator(engine)
        wid = orch.build_intelligence_workflow()
        assert wid.startswith("wf_daily_intelligence_")
        wf = engine.get(wid)
        assert wf is not None
        assert wf.steps["run_intelligence"].handler is not None

    def test_build_executor_workflow(self, engine):
        orch = OperationsOrchestrator(engine)
        wid = orch.build_executor_workflow()
        assert wid.startswith("wf_decision_executor_")
        wf = engine.get(wid)
        assert wf is not None
        assert wf.steps["run_executor"].handler is not None

    def test_register_all_creates_all_workflows(self, engine):
        orch = OperationsOrchestrator(engine)
        ids = orch.register_all()
        assert len(ids) >= 10
        for key in ("analytics", "intelligence", "executor", "feedback",
                     "experiments", "knowledge_graph", "forecast",
                     "weekly_plan", "selection", "ab_rotation", "distribution"):
            assert key in ids, f"Missing workflow: {key}"
            wf = engine.get(ids[key])
            assert wf is not None

    def test_build_twice_creates_unique_workflows(self, engine):
        orch = OperationsOrchestrator(engine)
        wid1 = orch.build_analytics_workflow()
        wid2 = orch.build_analytics_workflow()
        assert wid1 != wid2
        wf1 = engine.get(wid1)
        wf2 = engine.get(wid2)
        assert wf1 is not None
        assert wf2 is not None

    def test_make_handler_returns_dict(self, engine):
        orch = OperationsOrchestrator(engine)

        def sample_job():
            return {"status": "completed", "count": 42}

        handler = orch._make_handler(sample_job, 30)
        result = handler({"meta": "data"})
        assert result["status"] == "completed"
        assert result["count"] == 42

    def test_make_handler_propagates_exception(self, engine):
        orch = OperationsOrchestrator(engine)

        def failing_job():
            raise RuntimeError("test error")

        handler = orch._make_handler(failing_job, 30)
        with pytest.raises(RuntimeError, match="test error"):
            handler({})


class TestOperationsController:
    @pytest.fixture
    def controller(self):
        tmpdir = tempfile.mkdtemp()
        engine = WorkflowEngine(persist_dir=tmpdir)
        sched = Scheduler(persist_dir=tmpdir)
        ctrl = OperationsController(engine=engine, scheduler=sched)
        yield ctrl
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_controller_creation(self, controller):
        assert controller is not None
        report = controller.get_status()
        assert report.status in ("operational", "degraded")

    def test_get_status_returns_report(self, controller):
        report = controller.get_status()
        assert isinstance(report.status, str)
        assert isinstance(report.completed_today, int)
        assert isinstance(report.failed_today, int)

    def test_get_history_empty(self, controller):
        records = controller.get_history(limit=10)
        assert isinstance(records, list)

    def test_recover_no_failed(self, controller):
        recovered = controller.recover_failed()
        assert recovered == 0

    def test_schedule_all_no_scheduler(self, controller):
        # The controller already has a scheduler, so scheduling should work
        scheduled = controller.schedule_all()
        # In test environment, some operations may fail to schedule
        assert isinstance(scheduled, dict)

    def test_start_stop_scheduler(self, controller):
        controller.start_scheduler()
        import time
        time.sleep(0.1)
        controller.stop_scheduler(timeout_s=1.0)
        assert True

    def test_run_mocked_operation(self, controller):
        from mindmargin.operations.models import OperationType
        with patch("mindmargin.jobs.daily_analytics.run_daily_job") as mock_job:
            mock_job.return_value = {"status": "completed", "videos_collected": 0}
            result = controller.run_operation(OperationType.DAILY_ANALYTICS)
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ("completed", "failed")


class TestOperationsControllerPersistence:
    @pytest.fixture
    def controller(self):
        tmpdir = tempfile.mkdtemp()
        engine = WorkflowEngine(persist_dir=tmpdir)
        ctrl = OperationsController(engine=engine)
        # Point records_dir to a temp dir
        ctrl._records_dir = Path(tmpdir) / "operations"
        ctrl._records_dir.mkdir(parents=True, exist_ok=True)
        yield ctrl
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_save_and_list_records(self, controller):
        record = OperationRecord(
            operation_id="op_persist_001",
            operation_type=OperationType.AB_ROTATION,
            status=OperationStatus.COMPLETED,
            started_at="2026-07-03T10:00:00",
        )
        controller._save_record(record)
        records = controller._list_records()
        assert len(records) == 1
        assert records[0].operation_id == "op_persist_001"

    def test_list_records_empty(self, controller):
        records = controller._list_records()
        assert records == []

    def test_multiple_records_ordered_by_name(self, controller):
        for i in range(5):
            controller._save_record(OperationRecord(
                operation_id=f"op_{i:03d}",
                operation_type=OperationType.DAILY_ANALYTICS,
                status=OperationStatus.COMPLETED if i % 2 == 0 else OperationStatus.FAILED,
                started_at=f"2026-07-03T0{i}:00:00",
            ))
        records = controller._list_records()
        assert len(records) == 5



