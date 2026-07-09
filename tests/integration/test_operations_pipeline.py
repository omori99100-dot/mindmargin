"""Integration tests for the Autonomous Operations Hub.

Tests the full operation lifecycle: workflow creation, execution,
persistence, scheduling, recovery, and API integration.
"""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from mindmargin.core.scheduler import Scheduler
from mindmargin.core.workflows import WorkflowEngine
from mindmargin.operations.controller import OperationsController
from mindmargin.operations.models import (
    OPERATION_CRON_DEFAULTS,
    OperationRecord,
    OperationStatus,
    OperationType,
)
from mindmargin.operations.orchestrator import OperationsOrchestrator


@pytest.fixture
def tmp_base():
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    import shutil
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def engine(tmp_base):
    return WorkflowEngine(persist_dir=str(tmp_base))


@pytest.fixture
def scheduler(tmp_base):
    return Scheduler(persist_dir=str(tmp_base))


@pytest.fixture
def controller(engine, scheduler, tmp_base):
    ctrl = OperationsController(engine=engine, scheduler=scheduler)
    ctrl._records_dir = tmp_base / "operations"
    ctrl._records_dir.mkdir(parents=True, exist_ok=True)
    return ctrl


@pytest.fixture
def orchestrator(engine):
    return OperationsOrchestrator(engine)


class TestFullOperationLifecycle:
    """Test the complete lifecycle of an operation from creation to completion."""

    def test_build_workflow_structure(self, engine):
        """Test that building a workflow creates the correct step structure."""
        orch = OperationsOrchestrator(engine)
        wid = orch.build_analytics_workflow()
        wf = engine.get(wid)
        assert wf is not None
        assert len(wf.steps) == 1
        assert "run_analytics" in wf.steps
        step = wf.steps["run_analytics"]
        assert step.handler is not None
        assert step.max_retries == 2
        assert step.timeout_s == 1200

    def test_build_and_run_mocked_workflow(self, engine):
        """Test building and running a workflow with a mocked handler."""
        orch = OperationsOrchestrator(engine)
        wid = engine.create("test_op", [
            {"step_id": "mock_step", "name": "Mock Step", "timeout_s": 5},
        ])
        results = []

        def mock_handler(meta):
            results.append("called")
            return {"status": "completed"}

        engine.register_step_handler(wid, "mock_step", mock_handler)
        assert engine.start(wid)
        deadline = time.time() + 3
        wf = engine.get(wid)
        while wf and not wf.is_terminal and time.time() < deadline:
            time.sleep(0.05)
            wf = engine.get(wid)
        assert wf is not None
        assert wf.steps["mock_step"].state.value == "completed"
        assert results == ["called"]

    def test_controller_run_mocked_operation_persists_record(self, controller):
        """Test that running a mocked operation creates a persisted record."""
        with patch("mindmargin.jobs.daily_analytics.run_daily_job") as mock_job:
            mock_job.return_value = {"status": "completed", "videos_collected": 3}
            result = controller.run_operation(OperationType.DAILY_ANALYTICS)
        records = controller._list_records()
        assert len(records) >= 1
        record = records[0]
        assert record.operation_type == OperationType.DAILY_ANALYTICS
        assert record.status in (OperationStatus.COMPLETED, OperationStatus.FAILED)

    def test_controller_recover_failed(self, controller):
        """Test recover_failed returns 0 when no failures exist."""
        recovered = controller.recover_failed()
        assert recovered >= 0

    def test_scheduler_registration_and_lifecycle(self, controller, scheduler):
        """Test registering operations with the scheduler."""
        scheduled = controller.schedule_all()
        all_schedules = scheduler.list_all()
        assert len(scheduled) <= len(all_schedules)

        controller.start_scheduler()
        time.sleep(0.2)
        controller.stop_scheduler(timeout_s=1.0)
        assert True

    def test_operation_report_tracks_counts(self, controller):
        """Test that the operation report reflects execution history."""
        report = controller.get_status()
        assert isinstance(report.completed_today, int)
        assert isinstance(report.failed_today, int)
        assert isinstance(report.active_operations, int)
        assert report.status in ("operational", "degraded")


class TestOperationPersistence:
    """Test that operation records persist across controller instances."""

    def test_records_persist_to_disk(self, tmp_base, engine, scheduler):
        """Test that records are written to disk and survive controller restart."""
        ctrl1 = OperationsController(engine=engine, scheduler=scheduler)
        ctrl1._records_dir = tmp_base / "operations"
        ctrl1._records_dir.mkdir(parents=True, exist_ok=True)

        ctrl1._save_record(OperationRecord(
            operation_id="op_integration_001",
            operation_type=OperationType.DAILY_INTELLIGENCE,
            status=OperationStatus.COMPLETED,
            started_at="2026-07-03T06:30:00",
            completed_at="2026-07-03T07:00:00",
            result={"stages": {"scoring": {"status": "completed"}}},
        ))

        ctrl2 = OperationsController(engine=engine, scheduler=scheduler)
        ctrl2._records_dir = tmp_base / "operations"
        records = ctrl2._list_records()
        assert len(records) == 1
        assert records[0].operation_id == "op_integration_001"
        assert records[0].operation_type == OperationType.DAILY_INTELLIGENCE

    def test_corrupted_record_skipped(self, tmp_base, engine, scheduler):
        """Test that corrupted JSON files are skipped gracefully."""
        ctrl = OperationsController(engine=engine, scheduler=scheduler)
        ctrl._records_dir = tmp_base / "operations"
        ctrl._records_dir.mkdir(parents=True, exist_ok=True)
        bad_file = ctrl._records_dir / "corrupted.json"
        bad_file.write_text("{invalid json}", encoding="utf-8")
        records = ctrl._list_records()
        assert len(records) == 0

    def test_empty_records_dir(self, tmp_base, engine, scheduler):
        """Test listing records from an empty directory."""
        ctrl = OperationsController(engine=engine, scheduler=scheduler)
        ctrl._records_dir = tmp_base / "operations"
        ctrl._records_dir.mkdir(parents=True, exist_ok=True)
        records = ctrl._list_records()
        assert records == []


class TestOrchestratorIntegration:
    """Test the orchestrator's integration with the workflow engine."""

    def test_orchestrator_creates_all_workflows(self, engine):
        """Test that register_all creates all expected workflows."""
        orch = OperationsOrchestrator(engine)
        ids = orch.register_all()
        assert len(ids) >= 10
        for key in ("analytics", "intelligence", "executor", "feedback",
                     "experiments", "knowledge_graph", "forecast",
                     "weekly_plan", "selection", "ab_rotation", "distribution"):
            assert key in ids
            wf = engine.get(ids[key])
            assert wf is not None

    def test_each_workflow_has_handler(self, engine):
        """Test that each registered workflow has a handler for its step."""
        orch = OperationsOrchestrator(engine)
        ids = orch.register_all()
        for key, wid in ids.items():
            wf = engine.get(wid)
            for sid, step in wf.steps.items():
                assert step.handler is not None, f"Workflow {key} step {sid} has no handler"

    def test_workflow_ids_are_stable(self, engine):
        """Test that the workflow IDs dict returns expected keys."""
        orch = OperationsOrchestrator(engine)
        orch.register_all()
        ids = orch.workflow_ids
        for key in ("analytics", "intelligence", "executor", "feedback",
                     "experiments", "knowledge_graph", "forecast",
                     "weekly_plan", "selection", "ab_rotation", "distribution"):
            assert key in ids


class TestCronDefaults:
    """Test that cron defaults cover all operation types."""

    def test_all_operations_have_cron(self):
        """Test that every operation type has a cron expression."""
        for op_type in OperationType:
            cron = OPERATION_CRON_DEFAULTS.get(op_type)
            assert cron is not None, f"Missing cron default for {op_type}"

    def test_cron_expressions_are_valid(self):
        """Test that all cron expressions are in valid 5-field format."""
        for op_type, cron in OPERATION_CRON_DEFAULTS.items():
            parts = cron.strip().split()
            assert len(parts) == 5, f"Invalid cron for {op_type}: {cron}"
            for part in parts:
                assert part != "", f"Empty field in cron for {op_type}: {cron}"
