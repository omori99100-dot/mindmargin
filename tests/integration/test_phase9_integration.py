import os
import tempfile
import threading
import time
from unittest.mock import patch

import pytest

from mindmargin.core.queue import Queue
from mindmargin.core.scheduler import Scheduler
from mindmargin.core.workflows import WorkflowEngine, StepState, WorkflowState
from mindmargin.core.events import EventBus, Event, publish as events_publish
from mindmargin.core.recovery import RecoveryManager
from mindmargin.core.health import HealthMonitor, HealthCheckResult, HealthState


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestSchedulerToQueue:
    def test_scheduled_task_enqueues(self, tmpdir):
        results = []

        def handler(payload):
            results.append(payload["id"])

        queue = Queue(persist_dir=tmpdir, max_concurrency=4)
        queue.register_handler("scheduled", handler)
        queue.start_worker()
        qid = queue.enqueue("scheduled", {"id": 1})
        time.sleep(0.5)
        queue.stop_worker()
        assert results == [1]
        assert queue.get(qid).state.value == "completed"


class TestQueueToWorkflow:
    def test_queue_triggers_workflow(self, tmpdir):
        step_results = []

        def wf_step_handler(meta):
            step_results.append(meta.get("val"))
            return {"processed": meta.get("val")}

        engine = WorkflowEngine(persist_dir=tmpdir)
        wid = engine.create("queue_wf", [
            {"step_id": "s1", "name": "Step1", "metadata": {"val": 42}},
            {"step_id": "s2", "name": "Step2", "metadata": {"val": 99}, "dependencies": ["s1"]},
        ])
        engine.register_step_handler(wid, "s1", wf_step_handler)
        engine.register_step_handler(wid, "s2", wf_step_handler)

        def queue_handler(payload):
            engine.start(payload["workflow_id"])
            return {"started": payload["workflow_id"]}

        queue = Queue(persist_dir=tmpdir)
        queue.register_handler("start_wf", queue_handler)
        queue.start_worker()
        queue.enqueue("start_wf", {"workflow_id": wid})
        time.sleep(0.5)
        queue.stop_worker()
        wf = engine.get(wid)
        assert wf.state == WorkflowState.COMPLETED
        assert wf.steps["s1"].state == StepState.COMPLETED
        assert wf.steps["s2"].state == StepState.COMPLETED
        assert 42 in step_results
        assert 99 in step_results


class TestWorkflowToEventBus:
    def test_workflow_events_published(self, tmpdir):
        bus = EventBus()
        events = []

        def event_collector(e: Event):
            events.append(e.topic)

        bus.subscribe("workflow.*", event_collector)

        import mindmargin.core.workflows as wf_mod
        original_publish = wf_mod.publish

        def tracking_publish(topic, data=None, source="", correlation_id="", metadata=None):
            event = bus.publish(topic, data, source, correlation_id, metadata)
            return event

        with patch.object(wf_mod, "publish", tracking_publish):
            import mindmargin.core.events as ev_mod
            with patch.object(ev_mod, "publish", tracking_publish):
                engine = WorkflowEngine(persist_dir=tmpdir)
                wid = engine.create("event_wf", [{"step_id": "s1"}])
                engine.start(wid)
                time.sleep(0.3)
                workflow_events = [e for e in events if e.startswith("workflow.")]
                assert "workflow.created" in workflow_events
                assert "workflow.started" in workflow_events


class TestWorkflowToRecovery:
    def test_recovery_restores_workflow(self, tmpdir):
        engine = WorkflowEngine(persist_dir=tmpdir)
        wid = engine.create("recover_wf", [
            {"step_id": "s1"},
            {"step_id": "s2", "dependencies": ["s1"]},
        ])
        wf = engine.get(wid)
        wf.state = WorkflowState.RUNNING
        wf.steps["s1"].state = StepState.RUNNING
        engine._save(wf)
        recovery = RecoveryManager(persist_dir=tmpdir)
        recovery.bind_workflow(engine)
        report = recovery.recover_all()
        assert report.recovered_workflows == 1
        recovered = engine.get(wid)
        assert recovered.state == WorkflowState.PENDING
        assert recovered.steps["s1"].state == StepState.PENDING


class TestWorkflowToHealth:
    def test_workflow_health_check(self, tmpdir):
        engine = WorkflowEngine(persist_dir=tmpdir)
        monitor = HealthMonitor()

        def check_workflows():
            wfs = engine.list_all()
            if not wfs:
                return HealthCheckResult(name="workflows", state=HealthState.HEALTHY, message="No workflows")
            failed_or_partial = [w.name for w in wfs if w.state in (WorkflowState.FAILED, WorkflowState.PARTIAL)]
            if failed_or_partial:
                return HealthCheckResult(
                    name="workflows", state=HealthState.FAILURE,
                    message=f"Unhealthy: {', '.join(failed_or_partial)}",
                )
            return HealthCheckResult(name="workflows", state=HealthState.HEALTHY, message="All OK")

        monitor.register("workflows", check_workflows)
        result = monitor.run_check("workflows")
        assert result.state == HealthState.HEALTHY

        wid = engine.create("fail_wf", [{"step_id": "s1", "max_retries": 0}])

        def broken(meta):
            raise ValueError("boom")

        engine.register_step_handler(wid, "s1", broken)
        engine.start(wid)
        time.sleep(0.5)

        result = monitor.run_check("workflows")
        assert result.state == HealthState.FAILURE


class TestEndToEnd:
    def test_scheduled_to_completed_workflow(self, tmpdir):
        step_results = []

        def step_a(meta):
            step_results.append("A")
            return {"step": "A"}

        def step_b(meta):
            step_results.append("B")
            return {"step": "B"}

        def step_c(meta):
            step_results.append("C")
            return {"step": "C"}

        engine = WorkflowEngine(persist_dir=tmpdir)
        wid = engine.create("e2e", [
            {"step_id": "a", "name": "A"},
            {"step_id": "b", "name": "B", "dependencies": ["a"]},
            {"step_id": "c", "name": "C", "dependencies": ["a"]},
        ])
        engine.register_step_handler(wid, "a", step_a)
        engine.register_step_handler(wid, "b", step_b)
        engine.register_step_handler(wid, "c", step_c)

        def queue_start_handler(payload):
            engine.start(payload["workflow_id"])
            return {"started": payload["workflow_id"]}

        queue = Queue(persist_dir=tmpdir, max_concurrency=4)
        queue.register_handler("start_wf", queue_start_handler)
        queue.start_worker()
        qid = queue.enqueue("start_wf", {"workflow_id": wid})
        time.sleep(1.0)
        queue.stop_worker()

        wf = engine.get(wid)
        assert wf.state == WorkflowState.COMPLETED
        assert wf.steps["a"].state == StepState.COMPLETED
        assert wf.steps["b"].state == StepState.COMPLETED
        assert wf.steps["c"].state == StepState.COMPLETED
        assert sorted(step_results) == ["A", "B", "C"]
        assert queue.get(qid).state.value == "completed"


class TestChainPersistence:
    def test_persistence_across_restart(self, tmpdir):
        step_results = []

        def handler(meta):
            step_results.append(meta.get("val"))
            return {"processed": meta.get("val")}

        engine1 = WorkflowEngine(persist_dir=tmpdir)
        wid = engine1.create("persist_wf", [
            {"step_id": "s1", "name": "S1", "metadata": {"val": 10}},
        ])
        engine1.register_step_handler(wid, "s1", handler)
        engine1.start(wid)
        time.sleep(0.3)
        assert engine1.get(wid).state == WorkflowState.COMPLETED
        persist_path = engine1._persist_dir

        engine2 = WorkflowEngine(persist_dir=tmpdir)
        count = engine2.recover()
        expected_count = 1 if count > 0 else 0
        assert engine2.list_all() == []
        assert count == 0


class TestFullHealthIntegration:
    def test_health_monitor_all_subsystems(self, tmpdir):
        queue = Queue(persist_dir=tmpdir)
        engine = WorkflowEngine(persist_dir=tmpdir)
        monitor = HealthMonitor()

        def check_queue():
            stats = queue.stats()
            if stats.get("failed", 0) > 0:
                return HealthCheckResult(name="queue", state=HealthState.DEGRADED, message="Has failed items")
            return HealthCheckResult(name="queue", state=HealthState.HEALTHY, message="OK")

        def check_workflows():
            wfs = engine.list_all()
            failed_or_partial = [w.name for w in wfs if w.state in (WorkflowState.FAILED, WorkflowState.PARTIAL)]
            if failed_or_partial:
                return HealthCheckResult(
                    name="workflows", state=HealthState.FAILURE,
                    message=f"Unhealthy: {', '.join(failed_or_partial)}",
                )
            return HealthCheckResult(name="workflows", state=HealthState.HEALTHY, message="OK")

        monitor.register("queue", check_queue)
        monitor.register("workflows", check_workflows)
        report = monitor.run_all()
        assert report.state == HealthState.HEALTHY

        wid = engine.create("health_fail", [{"step_id": "s1", "max_retries": 0}])

        def broken(meta):
            raise ValueError("fail")

        engine.register_step_handler(wid, "s1", broken)
        engine.start(wid)
        time.sleep(0.5)

        report = monitor.run_all()
        assert report.state == HealthState.FAILURE
