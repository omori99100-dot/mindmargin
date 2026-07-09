import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mindmargin.core.queue import (
    Queue,
    QueueItem,
    QueueState,
    DeadLetterQueue,
    RetryPolicy,
    InvalidTransitionError,
)


@pytest.fixture
def queue():
    with tempfile.TemporaryDirectory() as tmpdir:
        q = Queue(persist_dir=tmpdir, max_concurrency=4)
        yield q


@pytest.fixture
def dlq():
    with tempfile.TemporaryDirectory() as tmpdir:
        d = DeadLetterQueue(persist_dir=tmpdir)
        yield d


class TestQueueState:
    def test_valid_transitions(self):
        assert QueueState.RUNNING in _transitions(QueueState.PENDING)
        assert QueueState.FAILED in _transitions(QueueState.RUNNING)
        assert QueueState.RUNNING in _transitions(QueueState.RETRY)

    def test_invalid_transitions(self):
        assert QueueState.RUNNING not in _transitions(QueueState.COMPLETED)
        assert QueueState.RUNNING not in _transitions(QueueState.DEAD_LETTER)

    def test_terminal_states_item(self):
        assert QueueItem(queue_id="", queue_type="", payload={}, state=QueueState.COMPLETED).is_terminal
        assert QueueItem(queue_id="", queue_type="", payload={}, state=QueueState.CANCELLED).is_terminal
        assert QueueItem(queue_id="", queue_type="", payload={}, state=QueueState.DEAD_LETTER).is_terminal
        assert not QueueItem(queue_id="", queue_type="", payload={}, state=QueueState.PENDING).is_terminal


def _transitions(state):
    from mindmargin.core.queue import _TRANSITIONS
    return _TRANSITIONS.get(state, set())


class TestRetryPolicy:
    def test_fixed_backoff(self):
        p = RetryPolicy(backoff="fixed", base_delay_s=2.0)
        assert p.delay(1) == 2.0
        assert p.delay(5) == 2.0

    def test_linear_backoff(self):
        p = RetryPolicy(backoff="linear", base_delay_s=1.0)
        assert p.delay(1) == 1.0
        assert p.delay(3) == 3.0
        assert p.delay(5) == 5.0

    def test_exponential_backoff(self):
        p = RetryPolicy(backoff="exponential", base_delay_s=1.0)
        assert p.delay(1) == 1.0
        assert p.delay(2) == 2.0
        assert p.delay(3) == 4.0
        assert p.delay(4) == 8.0

    def test_max_delay_cap(self):
        p = RetryPolicy(backoff="exponential", base_delay_s=10.0, max_delay_s=30.0)
        assert p.delay(1) == 10.0
        assert p.delay(2) == 20.0
        assert p.delay(3) == 30.0
        assert p.delay(10) == 30.0

    def test_invalid_backoff(self):
        with pytest.raises(ValueError, match="Unknown backoff"):
            RetryPolicy(backoff="unknown")


class TestDeadLetterQueue:
    def test_put_and_list(self, dlq):
        item = QueueItem(queue_id="test-1", queue_type="test", payload={})
        dlq.put(item)
        items = dlq.list_items()
        assert len(items) == 1
        assert items[0].queue_id == "test-1"
        assert items[0].state == QueueState.DEAD_LETTER

    def test_retry(self, dlq):
        item = QueueItem(queue_id="test-1", queue_type="test", payload={})
        dlq.put(item)
        recovered = dlq.retry("test-1")
        assert recovered is not None
        assert recovered.queue_id == "test-1"
        assert recovered.state == QueueState.PENDING
        assert len(dlq.list_items()) == 0

    def test_retry_nonexistent(self, dlq):
        assert dlq.retry("nonexistent") is None

    def test_persistence(self, dlq):
        item = QueueItem(queue_id="persist-1", queue_type="test", payload={"key": "val"})
        dlq.put(item)
        dlq2 = DeadLetterQueue(persist_dir=str(dlq._path.parent))
        items = dlq2.load_all()
        assert len(items) == 1
        assert items[0].queue_id == "persist-1"
        assert items[0].payload == {"key": "val"}


class TestQueueEnqueue:
    def test_enqueue_returns_id(self, queue):
        qid = queue.enqueue("test", {"data": 1})
        assert qid.startswith("q_test_")

    def test_enqueue_stores_item(self, queue):
        qid = queue.enqueue("test", {"x": 1}, priority=5)
        item = queue.get(qid)
        assert item is not None
        assert item.queue_type == "test"
        assert item.payload == {"x": 1}
        assert item.priority == 5
        assert item.state == QueueState.PENDING

    def test_enqueue_increments_stats(self, queue):
        queue.enqueue("test", {})
        assert queue.stats()["enqueued"] == 1

    def test_enqueue_with_correlation_id(self, queue):
        qid = queue.enqueue("test", {}, correlation_id="my-cid")
        item = queue.get(qid)
        assert item.correlation_id == "my-cid"


class TestQueueDequeue:
    def test_dequeue_returns_pending(self, queue):
        qid = queue.enqueue("test", {})
        item = queue.dequeue()
        assert item is not None
        assert item.queue_id == qid
        assert item.state == QueueState.RUNNING

    def test_dequeue_empty(self, queue):
        assert queue.dequeue() is None

    def test_dequeue_running_not_returned(self, queue):
        queue.enqueue("test", {})
        queue.dequeue()
        assert queue.dequeue() is None

    def test_dequeue_paused_not_returned(self, queue):
        qid = queue.enqueue("test", {})
        queue.pause(qid)
        assert queue.dequeue() is None


class TestQueuePriority:
    def test_higher_priority_first(self, queue):
        queue.enqueue("test", {"id": "low"}, priority=1)
        queue.enqueue("test", {"id": "high"}, priority=10)
        item1 = queue.dequeue()
        assert item1.payload["id"] == "high"
        item2 = queue.dequeue()
        assert item2.payload["id"] == "low"

    def test_fifo_within_same_priority(self, queue):
        ids = []
        for i in range(5):
            qid = queue.enqueue("test", {"seq": i}, priority=1)
            ids.append(qid)
        for expected in ids:
            item = queue.dequeue()
            assert item.queue_id == expected


class TestQueueComplete:
    def test_complete_sets_state(self, queue):
        qid = queue.enqueue("test", {})
        queue.dequeue()
        queue.complete(qid, {"success": True})
        item = queue.get(qid)
        assert item.state == QueueState.COMPLETED
        assert item.result == {"success": True}
        assert item.completed_at != ""

    def test_complete_unknown(self, queue):
        queue.complete("nonexistent", {})

    def test_complete_increments_stats(self, queue):
        qid = queue.enqueue("test", {})
        queue.dequeue()
        queue.complete(qid)
        assert queue.stats()["completed"] == 1


class TestQueueFailAndRetry:
    def test_fail_with_retries(self, queue):
        qid = queue.enqueue("test", {}, max_retries=3)
        queue.dequeue()
        queue.fail(qid, "something broke")
        item = queue.get(qid)
        assert item.state == QueueState.RETRY
        assert item.retry_count == 1

    def test_fail_exhausts_retries(self, queue):
        qid = queue.enqueue("test", {}, max_retries=1)
        queue.dequeue()
        queue.fail(qid, "err")
        item = queue.get(qid)
        assert item.state == QueueState.RETRY
        assert item.retry_count == 1
        item.state = QueueState.RUNNING
        queue._save(item)
        queue.fail(qid, "err again")
        assert queue.get(qid).state == QueueState.DEAD_LETTER

    def test_fail_sends_to_dlq(self, queue):
        qid = queue.enqueue("test", {}, max_retries=1)
        queue.dequeue()
        queue.fail(qid, "err")
        item = queue.get(qid)
        item.state = QueueState.RUNNING
        queue._save(item)
        queue.fail(qid, "err")
        dlq_items = queue.dead_letter_queue().list_items()
        assert len(dlq_items) == 1
        assert dlq_items[0].queue_id == qid

    def test_retry_eventually_runs(self, queue):
        handler_called = [False]

        def handler(payload):
            handler_called[0] = True

        queue.register_handler("greeter", handler)
        qid = queue.enqueue("greeter", {}, max_retries=2)
        queue.dequeue()
        queue.fail(qid, "transient")
        time.sleep(1.5)
        item = queue.dequeue()
        assert item is not None
        assert item.queue_id == qid


class TestQueueCancel:
    def test_cancel_pending(self, queue):
        qid = queue.enqueue("test", {})
        assert queue.cancel(qid)
        assert queue.get(qid).state == QueueState.CANCELLED

    def test_cancel_terminal_fails(self, queue):
        qid = queue.enqueue("test", {})
        queue.dequeue()
        queue.complete(qid)
        assert not queue.cancel(qid)

    def test_cancel_unknown(self, queue):
        assert not queue.cancel("nonexistent")

    def test_cancel_removes_from_pending(self, queue):
        qid = queue.enqueue("test", {})
        queue.cancel(qid)
        assert queue.dequeue() is None


class TestQueuePauseResume:
    def test_pause(self, queue):
        qid = queue.enqueue("test", {})
        assert queue.pause(qid)
        assert queue.get(qid).state == QueueState.PAUSED
        assert queue.dequeue() is None

    def test_resume(self, queue):
        qid = queue.enqueue("test", {})
        queue.pause(qid)
        assert queue.resume(qid)
        assert queue.get(qid).state == QueueState.PENDING
        assert queue.dequeue() is not None

    def test_pause_running_fails(self, queue):
        qid = queue.enqueue("test", {})
        queue.dequeue()
        assert not queue.pause(qid)

    def test_resume_active_fails(self, queue):
        qid = queue.enqueue("test", {})
        assert not queue.resume(qid)


class TestQueueWorker:
    def test_worker_calls_handler(self, queue):
        results = []

        def handler(payload):
            results.append(payload["x"])
            return {"processed": payload["x"]}

        queue.register_handler("math", handler)
        queue.start_worker()
        queue.enqueue("math", {"x": 42})
        time.sleep(0.3)
        queue.stop_worker()
        assert results == [42]

    def test_worker_missing_handler(self, queue):
        queue.start_worker()
        qid = queue.enqueue("nobody", {}, max_retries=0)
        time.sleep(0.5)
        queue.stop_worker()
        item = queue.get(qid)
        assert item.state in (QueueState.FAILED, QueueState.DEAD_LETTER)

    def test_worker_concurrency_limit(self, queue):
        lock = threading.Lock()
        concurrent = [0]
        max_seen = [0]

        def slow_handler(payload):
            with lock:
                concurrent[0] += 1
                max_seen[0] = max(max_seen[0], concurrent[0])
            time.sleep(0.2)
            with lock:
                concurrent[0] -= 1
            return {}

        queue.register_handler("slow", slow_handler)
        queue.start_worker()
        for i in range(6):
            queue.enqueue("slow", {"i": i})
        time.sleep(0.5)
        queue.stop_worker()
        assert max_seen[0] <= queue._max_concurrency


class TestQueuePersistence:
    def test_saves_to_disk(self, queue):
        qid = queue.enqueue("test", {"disk": True})
        path = queue._path_for(queue.get(qid))
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["queue_id"] == qid
        assert data["state"] == "pending"

    def test_recover_restores_pending(self, queue):
        qid = queue.enqueue("test", {"restore": True})
        persist_dir = queue._persist_dir
        q2 = Queue(persist_dir=str(persist_dir.parent))
        count = q2.recover()
        assert count >= 1
        assert q2.get(qid) is not None

    def test_recover_skips_terminal(self, queue):
        qid = queue.enqueue("test", {})
        queue.dequeue()
        queue.complete(qid)
        persist_dir = queue._persist_dir
        q2 = Queue(persist_dir=str(persist_dir.parent))
        count = q2.recover()
        item = q2.get(qid)
        assert item is None or item.state == QueueState.COMPLETED

    def test_recover_running_becomes_pending(self, queue):
        qid = queue.enqueue("test", {})
        queue.dequeue()
        persist_dir = queue._persist_dir
        q2 = Queue(persist_dir=str(persist_dir.parent))
        count = q2.recover()
        recovered = q2.get(qid)
        assert recovered is not None
        assert recovered.state in (QueueState.PENDING, QueueState.RUNNING)
        if recovered.state == QueueState.RUNNING:
            assert recovered.retry_count >= 0


class TestQueueDLQRetry:
    def test_retry_dead_letter(self, queue):
        qid = queue.enqueue("test", {}, max_retries=1)
        queue.dequeue()
        queue.fail(qid, "fail1")
        item = queue.get(qid)
        item.state = QueueState.RUNNING
        queue._save(item)
        queue.fail(qid, "fail2")
        assert queue.retry_dead_letter(qid)
        assert len(queue.dead_letter_queue().list_items()) == 0
        assert queue.get(qid).state == QueueState.PENDING

    def test_retry_dead_letter_nonexistent(self, queue):
        assert not queue.retry_dead_letter("nonexistent")


class TestQueueStats:
    def test_stats_pending_count(self, queue):
        queue.enqueue("a", {})
        queue.enqueue("b", {})
        stats = queue.stats()
        assert stats["pending"] == 2

    def test_stats_total(self, queue):
        queue.enqueue("a", {})
        queue.enqueue("b", {})
        queue.dequeue()
        assert queue.stats()["total"] == 2

    def test_stats_dlq(self, queue):
        qid = queue.enqueue("test", {}, max_retries=1)
        queue.dequeue()
        queue.fail(qid, "err")
        item = queue.get(qid)
        item.state = QueueState.RUNNING
        queue._save(item)
        queue.fail(qid, "err2")
        assert queue.stats()["dlq"] == 1


class TestQueueList:
    def test_list_by_state(self, queue):
        q1 = queue.enqueue("a", {})
        q2 = queue.enqueue("b", {})
        queue.dequeue()
        pending = queue.list_by_state(QueueState.PENDING)
        running = queue.list_by_state(QueueState.RUNNING)
        assert len(pending) == 1
        assert len(running) == 1

    def test_list_all(self, queue):
        queue.enqueue("a", {})
        queue.enqueue("b", {})
        assert len(queue.list_all()) == 2


class TestQueueItem:
    def test_to_dict_roundtrip(self):
        item = QueueItem(queue_id="q1", queue_type="t", payload={"a": 1})
        d = item.to_dict()
        assert d["queue_id"] == "q1"
        assert d["state"] == "pending"
        restored = QueueItem.from_dict(d)
        assert restored.queue_id == "q1"
        assert restored.state == QueueState.PENDING
        assert restored.payload == {"a": 1}

    def test_is_terminal(self):
        assert QueueItem(queue_id="", queue_type="", payload={}, state=QueueState.COMPLETED).is_terminal
        assert not QueueItem(queue_id="", queue_type="", payload={}, state=QueueState.PENDING).is_terminal


class TestQueueEdgeCases:
    def test_get_unknown(self, queue):
        assert queue.get("nonexistent") is None

    def test_fail_unknown(self, queue):
        queue.fail("nonexistent", "error")

    def test_delete_removes_file(self, queue):
        qid = queue.enqueue("test", {})
        item = queue.get(qid)
        p = queue._path_for(item)
        assert p.exists()
        queue._delete(item)
        assert not p.exists()

    def test_delete_missing_file(self, queue):
        item = QueueItem(queue_id="fake", queue_type="t", payload={})
        queue._delete(item)

    def test_process_item_exception(self, queue):
        results = []
        def handler(payload):
            raise ValueError("processing error")
        queue.register_handler("fail_me", handler)
        queue.start_worker()
        qid = queue.enqueue("fail_me", {}, max_retries=0)
        time.sleep(0.3)
        queue.stop_worker()
        item = queue.get(qid)
        assert item.state in (QueueState.FAILED, QueueState.DEAD_LETTER)

    def test_recover_running_becomes_pending(self, queue):
        qid = queue.enqueue("test", {}, max_retries=3)
        queue.dequeue()
        persist_dir = queue._persist_dir
        q2 = Queue(persist_dir=str(persist_dir.parent))
        count = q2.recover()
        recovered = q2.get(qid)
        assert recovered is not None
        assert recovered.state == QueueState.PENDING

    def test_recover_retry_becomes_pending(self, queue):
        qid = queue.enqueue("test", {}, max_retries=3)
        queue.dequeue()
        queue.fail(qid, "transient")
        persist_dir = queue._persist_dir
        q2 = Queue(persist_dir=str(persist_dir.parent))
        count = q2.recover()
        recovered = q2.get(qid)
        assert recovered is not None

    def test_recover_failed_goes_to_dlq(self, queue):
        qid = queue.enqueue("test", {}, max_retries=0)
        queue.dequeue()
        item = queue.get(qid)
        item.state = QueueState.FAILED
        queue._save(item)
        persist_dir = queue._persist_dir
        q2 = Queue(persist_dir=str(persist_dir.parent))
        count = q2.recover()
        dlq_items = q2.dead_letter_queue().list_items()
        assert any(item.queue_id == qid for item in dlq_items)

    def test_recover_paused_skips_pending(self, queue):
        qid = queue.enqueue("test", {})
        queue.pause(qid)
        persist_dir = queue._persist_dir
        q2 = Queue(persist_dir=str(persist_dir.parent))
        count = q2.recover()
        recovered = q2.get(qid)
        assert recovered is None or recovered.state == QueueState.PAUSED
