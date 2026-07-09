import json
import logging
import os
import queue as stdlib_queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from mindmargin.config import settings
from mindmargin.core.events import publish
from mindmargin.core.hardening import (
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
    utcnow,
)

logger = logging.getLogger(__name__)


class QueueState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"
    PAUSED = "paused"


_TRANSITIONS: dict[QueueState, set[QueueState]] = {
    QueueState.PENDING: {QueueState.RUNNING, QueueState.CANCELLED, QueueState.PAUSED},
    QueueState.RUNNING: {QueueState.COMPLETED, QueueState.FAILED, QueueState.RETRY, QueueState.CANCELLED},
    QueueState.RETRY: {QueueState.RUNNING, QueueState.DEAD_LETTER, QueueState.CANCELLED},
    QueueState.COMPLETED: set(),
    QueueState.FAILED: {QueueState.RETRY, QueueState.PENDING},
    QueueState.CANCELLED: set(),
    QueueState.DEAD_LETTER: {QueueState.PENDING},
    QueueState.PAUSED: {QueueState.PENDING, QueueState.CANCELLED},
}


class InvalidTransitionError(Exception):
    pass


@dataclass
class QueueItem:
    queue_id: str
    queue_type: str
    payload: dict
    priority: int = 0
    state: QueueState = QueueState.PENDING
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    retry_count: int = 0
    max_retries: int = 3
    error: str = ""
    result: dict = field(default_factory=dict)
    correlation_id: str = ""
    metadata: dict = field(default_factory=dict)
    _persist_path: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.state in (QueueState.COMPLETED, QueueState.CANCELLED, QueueState.DEAD_LETTER)

    def to_dict(self) -> dict:
        return {
            "queue_id": self.queue_id,
            "queue_type": self.queue_type,
            "payload": self.payload,
            "priority": self.priority,
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error": self.error,
            "result": self.result,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueueItem":
        d["state"] = QueueState(d["state"])
        return cls(**d)


class RetryPolicy:
    def __init__(self, max_retries: int = 3, base_delay_s: float = 1.0,
                 max_delay_s: float = 60.0, backoff: str = "exponential"):
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s
        self.max_delay_s = max_delay_s
        if backoff not in ("fixed", "linear", "exponential"):
            raise ValueError(f"Unknown backoff: {backoff}")
        self.backoff = backoff

    def delay(self, attempt: int) -> float:
        if self.backoff == "fixed":
            d = self.base_delay_s
        elif self.backoff == "linear":
            d = self.base_delay_s * attempt
        else:
            d = self.base_delay_s * (2 ** (attempt - 1))
        return min(d, self.max_delay_s)


class DeadLetterQueue:
    def __init__(self, persist_dir: str = ""):
        self._items: list[QueueItem] = []
        self._lock = threading.Lock()
        root = Path(persist_dir or settings.storage.temp_root)
        self._path = root / "dead_letter_queue"
        self._path.mkdir(parents=True, exist_ok=True)

    def put(self, item: QueueItem):
        with self._lock:
            item.state = QueueState.DEAD_LETTER
            self._items.append(item)
            self._save(item)
        publish("queue.dead_letter", data=item.to_dict(), source="queue")

    def list_items(self) -> list[QueueItem]:
        with self._lock:
            return list(self._items)

    def retry(self, queue_id: str) -> Optional[QueueItem]:
        with self._lock:
            for item in self._items:
                if item.queue_id == queue_id and item.state == QueueState.DEAD_LETTER:
                    item.state = QueueState.PENDING
                    self._items.remove(item)
                    self._delete(item)
                    return item
        return None

    def _path_for(self, item: QueueItem) -> Path:
        return self._path / f"{item.queue_id}.json"

    def _save(self, item: QueueItem):
        self._path_for(item).write_text(
            json.dumps(item.to_dict(), indent=2), encoding="utf-8"
        )

    def _delete(self, item: QueueItem):
        p = self._path_for(item)
        if p.exists():
            p.unlink()

    def load_all(self) -> list[QueueItem]:
        items = []
        for f in self._path.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                items.append(QueueItem.from_dict(d))
            except Exception as e:
                logger.warning("Failed to load DLQ item %s: %s", f.name, e)
        with self._lock:
            self._items = items
        return items


class Queue:
    def __init__(self, persist_dir: str = "", max_concurrency: int = 4):
        self._items: dict[str, QueueItem] = {}
        self._pending: list[str] = []
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._max_concurrency = max_concurrency
        self._semaphore = threading.Semaphore(max_concurrency)
        self._handlers: dict[str, Callable] = {}
        self._dlq = DeadLetterQueue(persist_dir)
        self._default_retry = RetryPolicy()
        self._stats: dict = {"enqueued": 0, "completed": 0, "failed": 0, "retried": 0}
        self._cleanup_interval: int = 100
        self._ops_since_cleanup: int = 0
        root = Path(persist_dir or settings.storage.temp_root)
        self._persist_dir = root / "queue"
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    def register_handler(self, queue_type: str, handler: Callable):
        self._handlers[queue_type] = handler

    def enqueue(self, queue_type: str, payload: dict,
                priority: int = 0, max_retries: Optional[int] = None,
                correlation_id: str = "", metadata: Optional[dict] = None) -> str:
        with self._lock:
            qid = f"q_{queue_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}"
            item = QueueItem(
                queue_id=qid,
                queue_type=queue_type,
                payload=payload,
                priority=priority,
                max_retries=max_retries if max_retries is not None else self._default_retry.max_retries,
                created_at=utcnow(),
                correlation_id=correlation_id or get_correlation_id(),
                metadata=metadata or {},
            )
            self._items[qid] = item
            self._pending.append(qid)
            self._pending.sort(key=lambda i: -self._items[i].priority)
            self._save(item)
            self._stats["enqueued"] += 1
            self._ops_since_cleanup += 1
            if self._ops_since_cleanup >= self._cleanup_interval:
                self._cleanup_terminal()
                self._ops_since_cleanup = 0
            self._cond.notify()
        publish("queue.enqueued", data=item.to_dict(), source="queue",
                correlation_id=item.correlation_id)
        return qid

    def dequeue(self) -> Optional[QueueItem]:
        with self._lock:
            while self._pending:
                qid = self._pending.pop(0)
                item = self._items.get(qid)
                if item and item.state == QueueState.PENDING:
                    item.state = QueueState.RUNNING
                    item.started_at = utcnow()
                    self._save(item)
                    return item
        return None

    def complete(self, queue_id: str, result: Optional[dict] = None):
        with self._lock:
            item = self._items.get(queue_id)
            if not item:
                return
            item.state = QueueState.COMPLETED
            item.completed_at = utcnow()
            item.result = result or {}
            self._save(item)
            self._stats["completed"] += 1
        publish("queue.completed", data={"queue_id": queue_id, "result": result},
                source="queue", correlation_id=item.correlation_id)

    def fail(self, queue_id: str, error: str):
        with self._lock:
            item = self._items.get(queue_id)
            if not item:
                return
            item.error = error
            if item.retry_count < item.max_retries:
                item.retry_count += 1
                item.state = QueueState.RETRY
                self._stats["retried"] += 1
                delay = self._default_retry.delay(item.retry_count)
                self._schedule_retry(queue_id, delay)
            else:
                item.state = QueueState.FAILED
                item.completed_at = utcnow()
                self._stats["failed"] += 1
                self._dlq.put(item)
            self._save(item)
        publish("queue.failed", data={"queue_id": queue_id, "error": error,
                                      "retry_count": item.retry_count},
                source="queue", correlation_id=item.correlation_id)

    def _schedule_retry(self, queue_id: str, delay_s: float):
        def _retry():
            time.sleep(delay_s)
            with self._lock:
                item = self._items.get(queue_id)
                if item and item.state == QueueState.RETRY:
                    item.state = QueueState.PENDING
                    self._pending.append(queue_id)
                    self._pending.sort(key=lambda i: -self._items[i].priority)
                    self._save(item)
                    self._cond.notify()

        t = threading.Thread(target=_retry, daemon=True)
        t.start()

    def cancel(self, queue_id: str) -> bool:
        with self._lock:
            item = self._items.get(queue_id)
            if not item or item.is_terminal:
                return False
            if item.state == QueueState.PENDING:
                self._pending = [q for q in self._pending if q != queue_id]
            item.state = QueueState.CANCELLED
            item.completed_at = utcnow()
            self._save(item)
        publish("queue.cancelled", data={"queue_id": queue_id}, source="queue")
        return True

    def pause(self, queue_id: str) -> bool:
        with self._lock:
            item = self._items.get(queue_id)
            if not item or item.state != QueueState.PENDING:
                return False
            item.state = QueueState.PAUSED
            self._pending = [q for q in self._pending if q != queue_id]
            self._save(item)
        return True

    def resume(self, queue_id: str) -> bool:
        with self._lock:
            item = self._items.get(queue_id)
            if not item or item.state != QueueState.PAUSED:
                return False
            item.state = QueueState.PENDING
            self._pending.append(queue_id)
            self._pending.sort(key=lambda i: self._items[i].priority, reverse=True)
            self._save(item)
            self._cond.notify()
        return True

    def get(self, queue_id: str) -> Optional[QueueItem]:
        with self._lock:
            return self._items.get(queue_id)

    def list_by_state(self, state: QueueState) -> list[QueueItem]:
        with self._lock:
            return [item for item in self._items.values() if item.state == state]

    def list_all(self) -> list[QueueItem]:
        with self._lock:
            return list(self._items.values())

    def dead_letter_queue(self) -> DeadLetterQueue:
        return self._dlq

    def retry_dead_letter(self, queue_id: str) -> bool:
        item = self._dlq.retry(queue_id)
        if item:
            with self._lock:
                self._items[item.queue_id] = item
                self._pending.append(item.queue_id)
                self._pending.sort(key=lambda i: self._items[i].priority, reverse=True)
            publish("queue.retry", data={"queue_id": queue_id}, source="queue")
            return True
        return False

    def stats(self) -> dict:
        with self._lock:
            s = dict(self._stats)
            s["pending"] = len(self._pending)
            s["total"] = len(self._items)
            s["dlq"] = len(self._dlq.list_items())
            return s

    def start_worker(self):
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Queue worker started (max_concurrency=%d)", self._max_concurrency)

    def stop_worker(self, timeout_s: float = 5.0):
        self._running = False
        with self._cond:
            self._cond.notify_all()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout_s)

    def _worker_loop(self):
        while self._running:
            item = self.dequeue()
            if item:
                self._semaphore.acquire()
                t = threading.Thread(
                    target=self._process_item,
                    args=(item,),
                    daemon=True,
                )
                t.start()
            else:
                with self._cond:
                    self._cond.wait(timeout=1.0)

    def _process_item(self, item: QueueItem):
        old_cid = set_correlation_id(item.correlation_id)
        try:
            handler = self._handlers.get(item.queue_type)
            if not handler:
                self.fail(item.queue_id, f"No handler registered for '{item.queue_type}'")
                return
            result = handler(item.payload)
            self.complete(item.queue_id, result)
        except Exception as e:
            logger.error("Queue item %s failed: %s", item.queue_id, e)
            self.fail(item.queue_id, str(e))
        finally:
            set_correlation_id(old_cid)
            self._semaphore.release()

    def _cleanup_terminal(self):
        """Remove completed/cancelled items from memory (persists stay for audit trail)."""
        terminal_ids = [
            qid for qid, item in self._items.items()
            if item.is_terminal and item.state != QueueState.DEAD_LETTER
        ]
        for qid in terminal_ids:
            del self._items[qid]

    def _path_for(self, item: QueueItem) -> Path:
        return self._persist_dir / f"{item.queue_id}.json"

    def _save(self, item: QueueItem):
        self._path_for(item).write_text(
            json.dumps(item.to_dict(), indent=2), encoding="utf-8"
        )

    def _delete(self, item: QueueItem):
        p = self._path_for(item)
        if p.exists():
            p.unlink()

    def recover(self) -> int:
        count = 0
        for f in sorted(self._persist_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                item = QueueItem.from_dict(d)
                if item.is_terminal:
                    continue
                if item.state == QueueState.RUNNING:
                    item.retry_count += 1
                    item.state = QueueState.PENDING if item.retry_count <= item.max_retries else QueueState.FAILED
                if item.state == QueueState.RETRY:
                    item.state = QueueState.PENDING
                if item.state == QueueState.FAILED:
                    self._dlq.put(item)
                    count += 1
                    continue
                if item.state == QueueState.PAUSED:
                    self._items[item.queue_id] = item
                    count += 1
                    continue
                self._items[item.queue_id] = item
                self._pending.append(item.queue_id)
                count += 1
            except Exception as e:
                logger.warning("Failed to recover queue item %s: %s", f.name, e)
        self._pending.sort(key=lambda i: self._items[i].priority, reverse=True)
        logger.info("Recovered %d queue items from %s", count, self._persist_dir)
        return count
