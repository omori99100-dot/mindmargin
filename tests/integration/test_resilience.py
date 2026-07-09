"""Phase 9 resilience validation tests for Queue, WorkflowEngine, Scheduler, RecoveryManager."""

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mindmargin.core.queue import (
    Queue,
    QueueItem,
    QueueState,
    DeadLetterQueue,
    RetryPolicy,
)
from mindmargin.core.scheduler import Scheduler, ScheduleState
from mindmargin.core.workflows import WorkflowEngine, WorkflowState, StepState
from mindmargin.core.recovery import RecoveryManager


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestCrashSimulation:
    """Simulate crashes in core subsystems and verify recovery."""

    def test_queue_crash_during_processing(self, tmpdir):
        q1 = Queue(persist_dir=tmpdir)
        qid = q1.enqueue("test", {"data": "crash"})
        q1.dequeue()

        q2 = Queue(persist_dir=tmpdir)
        count = q2.recover()
        assert count >= 1

        recovered = q2.get(qid)
        assert recovered is not None
        assert recovered.state == QueueState.PENDING

        results = []

        def handler(payload):
            results.append(payload["data"])
            return {}

        q2.register_handler("test", handler)
        q2.start_worker()
        time.sleep(0.3)
        q2.stop_worker()

        assert results == ["crash"]
        assert q2.get(qid).state == QueueState.COMPLETED

    def test_workflow_crash_during_execution(self, tmpdir):
        engine1 = WorkflowEngine(persist_dir=tmpdir)
        wid = engine1.create("crash_wf", [
            {"step_id": "s1", "name": "Step1"},
        ])
        wf = engine1.get(wid)
        wf.state = WorkflowState.RUNNING
        wf.steps["s1"].state = StepState.RUNNING
        engine1._save(wf)

        engine2 = WorkflowEngine(persist_dir=tmpdir)
        count = engine2.recover()
        assert count >= 1

        recovered = engine2.get(wid)
        assert recovered is not None
        assert recovered.state == WorkflowState.PENDING
        assert recovered.steps["s1"].state == StepState.PENDING

    def test_scheduler_crash_during_execution(self, tmpdir):
        sched1 = Scheduler(persist_dir=tmpdir)
        sid = sched1.register("test_sched", lambda: None, interval_s=3600)

        sched2 = Scheduler(persist_dir=tmpdir)
        count = sched2.recover()
        assert count >= 1

        recovered = sched2.get(sid)
        assert recovered is not None
        assert recovered.name == "test_sched"
        assert recovered.state == ScheduleState.ACTIVE


class TestInterruptedWorkflows:
    """Test workflows interrupted during execution."""

    def test_workflow_interrupted_mid_step(self, tmpdir):
        step_results = []
        engine = WorkflowEngine(persist_dir=tmpdir)
        wid = engine.create("interrupted", [
            {"step_id": "s1", "name": "Step1"},
            {"step_id": "s2", "name": "Step2"},
            {"step_id": "s3", "name": "Step3", "dependencies": ["s1", "s2"]},
        ])

        def s1_ok(meta):
            step_results.append("s1")
            return {}

        def s2_fail(meta):
            step_results.append("s2_fail")
            raise ValueError("step2 crashed")

        def s3_ok(meta):
            step_results.append("s3")
            return {}

        engine.register_step_handler(wid, "s1", s1_ok)
        engine.register_step_handler(wid, "s2", s2_fail)
        engine.register_step_handler(wid, "s3", s3_ok)
        engine.start(wid)
        time.sleep(0.3)

        wf = engine.get(wid)
        assert wf.state == WorkflowState.PARTIAL
        assert wf.steps["s1"].state == StepState.COMPLETED
        assert wf.steps["s2"].state == StepState.FAILED
        assert wf.steps["s3"].state == StepState.PENDING

        def s2_ok(meta):
            step_results.append("s2_ok")
            return {}

        engine.register_step_handler(wid, "s2", s2_ok)
        engine.resume(wid)
        time.sleep(0.3)

        wf = engine.get(wid)
        assert wf.state == WorkflowState.COMPLETED
        assert wf.steps["s1"].state == StepState.COMPLETED
        assert wf.steps["s2"].state == StepState.COMPLETED
        assert wf.steps["s3"].state == StepState.COMPLETED

    def test_workflow_interrupted_dependency_chain(self, tmpdir):
        step_results = []
        engine = WorkflowEngine(persist_dir=tmpdir)
        wid = engine.create("dep_chain", [
            {"step_id": "a", "name": "A"},
            {"step_id": "b", "name": "B", "dependencies": ["a"]},
            {"step_id": "c", "name": "C", "dependencies": ["b"]},
        ])

        def handler_a(meta):
            step_results.append("A")
            return {}

        def handler_b_fail(meta):
            step_results.append("B_fail")
            raise ValueError("B crashed")

        def handler_c(meta):
            step_results.append("C")
            return {}

        engine.register_step_handler(wid, "a", handler_a)
        engine.register_step_handler(wid, "b", handler_b_fail)
        engine.register_step_handler(wid, "c", handler_c)
        engine.start(wid)
        time.sleep(0.3)

        wf = engine.get(wid)
        assert wf.state == WorkflowState.PARTIAL
        assert wf.steps["a"].state == StepState.COMPLETED
        assert wf.steps["b"].state == StepState.FAILED
        assert wf.steps["c"].state == StepState.PENDING

        def handler_b_ok(meta):
            step_results.append("B_ok")
            return {}

        engine.register_step_handler(wid, "b", handler_b_ok)
        engine.resume(wid)
        time.sleep(0.3)

        wf = engine.get(wid)
        assert wf.state == WorkflowState.COMPLETED
        assert wf.steps["a"].state == StepState.COMPLETED
        assert wf.steps["b"].state == StepState.COMPLETED
        assert wf.steps["c"].state == StepState.COMPLETED
        assert "A" in step_results
        assert "B_fail" in step_results
        assert "B_ok" in step_results
        assert "C" in step_results


class TestRecoveryGuarantees:
    """Test recovery guarantees across all subsystems."""

    def test_recovery_all_subsystems(self, tmpdir):
        q1 = Queue(persist_dir=tmpdir)
        qid = q1.enqueue("test", {"x": 1})
        q1.dequeue()

        s1 = Scheduler(persist_dir=tmpdir)
        sid = s1.register("sched1", lambda: None, interval_s=3600)

        w1 = WorkflowEngine(persist_dir=tmpdir)
        wid = w1.create("wf1", [{"step_id": "s1"}])
        wf = w1.get(wid)
        wf.state = WorkflowState.RUNNING
        wf.steps["s1"].state = StepState.RUNNING
        w1._save(wf)

        q2 = Queue(persist_dir=tmpdir)
        s2 = Scheduler(persist_dir=tmpdir)
        w2 = WorkflowEngine(persist_dir=tmpdir)

        rm = RecoveryManager(persist_dir=tmpdir)
        rm.bind_queue(q2)
        rm.bind_scheduler(s2)
        rm.bind_workflow(w2)
        report = rm.recover_all()

        assert report.recovered_queues == 1
        assert report.recovered_schedules == 1
        assert report.recovered_workflows == 1
        assert len(report.errors) == 0

        assert q2.get(qid) is not None
        assert q2.get(qid).state == QueueState.PENDING
        assert s2.get(sid) is not None
        assert s2.get(sid).state == ScheduleState.ACTIVE
        assert w2.get(wid) is not None
        assert w2.get(wid).state == WorkflowState.PENDING

    def test_recovery_partial_failure(self, tmpdir):
        q1 = Queue(persist_dir=tmpdir)
        q1.enqueue("test", {"x": 1})
        q1.dequeue()

        q2 = Queue(persist_dir=tmpdir)
        mock_w = MagicMock()
        mock_w.recover.side_effect = RuntimeError("workflow db corrupt")

        rm = RecoveryManager(persist_dir=tmpdir)
        rm.bind_queue(q2)
        rm.bind_workflow(mock_w)
        report = rm.recover_all()

        assert report.recovered_queues == 1
        assert report.recovered_workflows == 0
        assert len(report.errors) >= 1
        assert any("workflow" in err.lower() for err in report.errors)


class TestProviderFailure:
    """Test provider/handler failure and retry behavior."""

    def test_queue_handler_failure_retries(self, tmpdir):
        q = Queue(persist_dir=tmpdir, max_concurrency=4)
        q._default_retry = RetryPolicy(base_delay_s=0.05, backoff="fixed")

        call_count = [0]

        def handler(payload):
            call_count[0] += 1
            raise ValueError("always fails")

        q.register_handler("failing", handler)
        q.start_worker()
        qid = q.enqueue("failing", {}, max_retries=2)
        time.sleep(0.5)
        q.stop_worker()

        item = q.get(qid)
        assert item.state == QueueState.DEAD_LETTER
        dlq_items = q.dead_letter_queue().list_items()
        assert len(dlq_items) == 1
        assert dlq_items[0].queue_id == qid
        assert call_count[0] == 3

    def test_queue_handler_failure_then_succeeds(self, tmpdir):
        q = Queue(persist_dir=tmpdir, max_concurrency=4)
        q._default_retry = RetryPolicy(base_delay_s=0.05, backoff="fixed")

        call_count = [0]

        def handler(payload):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("transient failure")
            return {"ok": True}

        q.register_handler("transient", handler)
        q.start_worker()
        qid = q.enqueue("transient", {}, max_retries=2)
        time.sleep(0.5)
        q.stop_worker()

        item = q.get(qid)
        assert item.state == QueueState.COMPLETED
        assert call_count[0] == 2


class TestDatabaseFailure:
    """Test recovery with corrupt persisted files."""

    def test_recovery_corrupt_files(self, tmpdir):
        q1 = Queue(persist_dir=tmpdir)
        q1.enqueue("test", {"valid": 1})
        q1.enqueue("test", {"valid": 2})

        persist = q1._persist_dir
        corrupt_file = persist / "corrupt.json"
        corrupt_file.write_text("not valid json{{{", encoding="utf-8")

        bogus_file = persist / "not_json.json"
        bogus_file.write_text("", encoding="utf-8")

        q2 = Queue(persist_dir=tmpdir)
        count = q2.recover()
        assert count == 2


class TestQueueCorruption:
    """Test queue corruption and graceful stop behavior."""

    def test_dlq_corrupt_items(self, tmpdir):
        dlq = DeadLetterQueue(persist_dir=tmpdir)
        dlq.put(QueueItem(queue_id="valid-1", queue_type="test", payload={"a": 1}))
        dlq.put(QueueItem(queue_id="valid-2", queue_type="test", payload={"b": 2}))

        corrupt_file = dlq._path / "corrupt_evil.json"
        corrupt_file.write_text("this is not json{", encoding="utf-8")

        items = dlq.load_all()
        assert len(items) == 2
        ids = [i.queue_id for i in items]
        assert "valid-1" in ids
        assert "valid-2" in ids

    def test_queue_stop_worker_gracefully(self, tmpdir):
        processed = []

        def slow_handler(payload):
            time.sleep(0.2)
            processed.append(payload["id"])
            return {}

        q = Queue(persist_dir=tmpdir, max_concurrency=4)
        q.register_handler("slow", slow_handler)
        qids = [q.enqueue("slow", {"id": i}) for i in range(4)]

        q.start_worker()
        time.sleep(0.1)
        q.stop_worker(timeout_s=3.0)

        time.sleep(0.5)

        running = q.list_by_state(QueueState.RUNNING)
        assert len(running) == 0
        for qid in qids:
            item = q.get(qid)
            assert item.state in (QueueState.COMPLETED, QueueState.PENDING)
