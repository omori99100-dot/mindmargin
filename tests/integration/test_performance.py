"""Performance benchmarks for Phase 9 core subsystems.

Each benchmark measures wall-clock time with time.perf_counter()
and asserts minimum throughput/latency requirements.
"""

import asyncio
import tempfile
import time

import pytest

from mindmargin.core.queue import Queue
from mindmargin.core.workflows import WorkflowEngine, StepState, WorkflowState
from mindmargin.core.scheduler import Scheduler, parse_cron, cron_matches
from mindmargin.core.events import EventBus


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ── TestQueueThroughput ──────────────────────────────────────────────


class TestQueueThroughput:
    @pytest.mark.benchmark
    def test_enqueue_throughput(self, tmpdir):
        q = Queue(persist_dir=tmpdir)
        n = 100
        start = time.perf_counter()
        for i in range(n):
            q.enqueue("test", {"i": i})
        elapsed = time.perf_counter() - start
        rate = n / elapsed
        print(f"\n  Enqueue: {n} items in {elapsed:.3f}s ({rate:.0f} items/sec)")
        assert rate >= 200, f"Enqueue throughput too low: {rate:.0f} items/sec"

    @pytest.mark.benchmark
    def test_dequeue_throughput(self, tmpdir):
        q = Queue(persist_dir=tmpdir)
        n = 100
        for i in range(n):
            q.enqueue("test", {"i": i})
        start = time.perf_counter()
        for _ in range(n):
            q.dequeue()
        elapsed = time.perf_counter() - start
        rate = n / elapsed
        print(f"\n  Dequeue: {n} items in {elapsed:.3f}s ({rate:.0f} items/sec)")
        assert rate >= 300, f"Dequeue throughput too low: {rate:.0f} items/sec"

    @pytest.mark.benchmark
    def test_queue_process_throughput(self, tmpdir):
        results = []

        def handler(payload):
            results.append(payload["i"])

        q = Queue(persist_dir=tmpdir, max_concurrency=4)
        q.register_handler("proc", handler)
        q.start_worker()
        n = 50
        start = time.perf_counter()
        for i in range(n):
            q.enqueue("proc", {"i": i})
        while len(results) < n:
            time.sleep(0.01)
        elapsed = time.perf_counter() - start
        q.stop_worker()
        rate = n / elapsed
        print(f"\n  Process: {n} items in {elapsed:.3f}s ({rate:.0f} items/sec)")
        assert rate >= 20, f"Process throughput too low: {rate:.0f} items/sec"


# ── TestWorkflowExecution ───────────────────────────────────────────


class TestWorkflowExecution:
    @pytest.mark.benchmark
    def test_single_step_workflow(self, tmpdir):
        engine = WorkflowEngine(persist_dir=tmpdir)
        wid = engine.create("single", [{"step_id": "s1", "name": "S1"}])

        def handler(meta):
            return {"done": True}

        engine.register_step_handler(wid, "s1", handler)
        start = time.perf_counter()
        engine.start(wid)
        while True:
            wf = engine.get(wid)
            if wf and wf.is_terminal:
                break
            time.sleep(0.005)
        elapsed = time.perf_counter() - start
        print(f"\n  Single-step workflow: {elapsed:.4f}s")
        assert elapsed < 2.0, f"Single-step workflow too slow: {elapsed:.4f}s"

    @pytest.mark.benchmark
    def test_five_step_workflow(self, tmpdir):
        engine = WorkflowEngine(persist_dir=tmpdir)
        steps = [
            {"step_id": "s1", "name": "S1"},
            {"step_id": "s2", "name": "S2", "dependencies": ["s1"]},
            {"step_id": "s3", "name": "S3", "dependencies": ["s2"]},
            {"step_id": "s4", "name": "S4", "dependencies": ["s3"]},
            {"step_id": "s5", "name": "S5", "dependencies": ["s4"]},
        ]
        wid = engine.create("five", steps)

        def handler(meta):
            return {"done": True}

        for sid in ["s1", "s2", "s3", "s4", "s5"]:
            engine.register_step_handler(wid, sid, handler)
        start = time.perf_counter()
        engine.start(wid)
        while True:
            wf = engine.get(wid)
            if wf and wf.is_terminal:
                break
            time.sleep(0.005)
        elapsed = time.perf_counter() - start
        print(f"\n  Five-step workflow: {elapsed:.4f}s")
        assert elapsed < 5.0, f"Five-step workflow too slow: {elapsed:.4f}s"

    @pytest.mark.benchmark
    def test_parallel_workflow(self, tmpdir):
        engine = WorkflowEngine(persist_dir=tmpdir)
        steps = [
            {"step_id": "s1", "name": "S1"},
            {"step_id": "s2", "name": "S2"},
            {"step_id": "s3", "name": "S3"},
            {"step_id": "s4", "name": "S4"},
        ]
        wid = engine.create("parallel", steps)

        def handler(meta):
            return {"done": True}

        for sid in ["s1", "s2", "s3", "s4"]:
            engine.register_step_handler(wid, sid, handler)
        start = time.perf_counter()
        engine.start(wid)
        while True:
            wf = engine.get(wid)
            if wf and wf.is_terminal:
                break
            time.sleep(0.005)
        elapsed = time.perf_counter() - start
        print(f"\n  Parallel 4-step workflow: {elapsed:.4f}s")
        assert elapsed < 3.0, f"Parallel workflow too slow: {elapsed:.4f}s"


# ── TestSchedulerLatency ─────────────────────────────────────────────


class TestSchedulerLatency:
    @pytest.mark.benchmark
    def test_scheduler_register_latency(self, tmpdir):
        sched = Scheduler(persist_dir=tmpdir)
        n = 100

        def dummy():
            pass

        start = time.perf_counter()
        for i in range(n):
            sched.register(f"job_{i}", dummy, interval_s=60)
        elapsed = time.perf_counter() - start
        rate = n / elapsed
        print(f"\n  Register {n} schedules in {elapsed:.3f}s ({rate:.0f} reg/sec)")
        assert rate >= 20, f"Register throughput too low: {rate:.0f} reg/sec"

    @pytest.mark.benchmark
    def test_scheduler_cron_match_latency(self):
        n = 1000
        fields = parse_cron("*/5 9-17 * * 1-5")
        start = time.perf_counter()
        for _ in range(n):
            cron_matches(fields)
        elapsed = time.perf_counter() - start
        rate = n / elapsed
        print(f"\n  Cron match: {n} checks in {elapsed:.4f}s ({rate:.0f} checks/sec)")
        assert rate >= 5000, f"Cron match throughput too low: {rate:.0f} checks/sec"


# ── TestEventDispatch ────────────────────────────────────────────────


class TestEventDispatch:
    @pytest.mark.benchmark
    def test_sync_dispatch_latency(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(1)

        bus.subscribe("bench", handler)
        n = 1000
        start = time.perf_counter()
        for i in range(n):
            bus.publish("bench", {"i": i})
        elapsed = time.perf_counter() - start
        rate = n / elapsed
        print(f"\n  Sync dispatch: {n} events in {elapsed:.3f}s ({rate:.0f} events/sec)")
        assert rate >= 5000, f"Sync dispatch throughput too low: {rate:.0f} events/sec"

    @pytest.mark.benchmark
    def test_async_dispatch_latency(self):
        bus = EventBus()

        async def handler(event):
            pass

        bus.subscribe_async("bench", handler)
        n = 100
        start = time.perf_counter()
        for i in range(n):
            bus.publish("bench", {"i": i})
        elapsed = time.perf_counter() - start
        rate = n / elapsed
        print(f"\n  Async dispatch: {n} events in {elapsed:.3f}s ({rate:.0f} events/sec)")
        assert rate >= 50, f"Async dispatch throughput too low: {rate:.0f} events/sec"

    @pytest.mark.benchmark
    def test_multiple_handler_dispatch(self):
        bus = EventBus()

        def make_handler(idx):
            def h(event):
                pass
            return h

        n_handlers = 10
        for i in range(n_handlers):
            bus.subscribe("multi", make_handler(i))
        n = 100
        start = time.perf_counter()
        for i in range(n):
            bus.publish("multi", {"i": i})
        elapsed = time.perf_counter() - start
        rate = n / elapsed
        print(f"\n  Multi-handler: {n} events x {n_handlers} handlers in {elapsed:.3f}s ({rate:.0f} events/sec)")
        assert rate >= 500, f"Multi-handler dispatch throughput too low: {rate:.0f} events/sec"
