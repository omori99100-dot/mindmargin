import asyncio
import fnmatch
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from mindmargin.core.hardening import generate_correlation_id, get_correlation_id

logger = logging.getLogger(__name__)

SyncHandler = Callable[["Event"], None]
AsyncHandler = Callable[["Event"], Any]


@dataclass
class Event:
    topic: str
    data: Any = None
    source: str = ""
    correlation_id: str = ""
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)
    _event_id: str = ""

    def __post_init__(self):
        if not self._event_id:
            self._event_id = generate_correlation_id()
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.correlation_id:
            self.correlation_id = get_correlation_id()


class EventBus:
    def __init__(self, max_history: int = 1000):
        self._sync_handlers: dict[str, list[SyncHandler]] = defaultdict(list)
        self._async_handlers: dict[str, list[AsyncHandler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._history: list[Event] = []
        self._max_history = max_history
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_async_loop(self, loop: asyncio.AbstractEventLoop):
        self._async_loop = loop

    def _matching_keys(self, topic: str) -> list[str]:
        with self._lock:
            all_keys = set(self._sync_handlers.keys()) | set(self._async_handlers.keys())
        return [k for k in all_keys if fnmatch.fnmatch(topic, k)]

    def subscribe(self, topic: str, handler: SyncHandler):
        with self._lock:
            self._sync_handlers[topic].append(handler)
        logger.debug("Subscribed sync handler to '%s'", topic)

    def subscribe_async(self, topic: str, handler: AsyncHandler):
        with self._lock:
            self._async_handlers[topic].append(handler)
        logger.debug("Subscribed async handler to '%s'", topic)

    def unsubscribe(self, topic: str, handler: Callable):
        with self._lock:
            if handler in self._sync_handlers.get(topic, []):
                self._sync_handlers[topic].remove(handler)
            if handler in self._async_handlers.get(topic, []):
                self._async_handlers[topic].remove(handler)

    def publish(self, topic: str, data: Any = None, source: str = "",
                correlation_id: str = "", metadata: Optional[dict] = None) -> Event:
        event = Event(
            topic=topic,
            data=data,
            source=source,
            correlation_id=correlation_id or get_correlation_id(),
            metadata=metadata or {},
        )
        self._record(event)
        self._dispatch_sync(event)
        self._dispatch_async(event)
        return event

    def _record(self, event: Event):
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)

    def _dispatch_sync(self, event: Event):
        matching = self._matching_keys(event.topic)
        for key in matching:
            with self._lock:
                handlers = list(self._sync_handlers.get(key, []))
            for handler in handlers:
                try:
                    handler(event)
                except Exception as e:
                    logger.error("Sync handler for '%s' failed: %s", key, e)

    def _dispatch_async(self, event: Event):
        matching = self._matching_keys(event.topic)
        for key in matching:
            with self._lock:
                handlers = list(self._async_handlers.get(key, []))
            for handler in handlers:
                try:
                    loop = self._async_loop or asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(handler(event), loop)
                    else:
                        loop.run_until_complete(handler(event))
                except RuntimeError:
                    try:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(handler(event))
                        loop.close()
                    except Exception as e2:
                        logger.error("Async handler for '%s' failed: %s", key, e2)
                except Exception as e:
                    logger.error("Async handler for '%s' failed: %s", key, e)

    @property
    def history(self) -> list[Event]:
        with self._lock:
            return list(self._history)

    def history_by_topic(self, topic: str) -> list[Event]:
        return [e for e in self.history if fnmatch.fnmatch(e.topic, topic)]

    def clear_history(self):
        with self._lock:
            self._history.clear()

    def handler_count(self, topic: str = "") -> int:
        with self._lock:
            if topic:
                sync = len(self._sync_handlers.get(topic, []))
                async_ = len(self._async_handlers.get(topic, []))
                return sync + async_
            total = sum(len(v) for v in self._sync_handlers.values())
            total += sum(len(v) for v in self._async_handlers.values())
            return total


_global_bus = EventBus()


def get_bus() -> EventBus:
    return _global_bus


def publish(topic: str, data: Any = None, source: str = "",
            correlation_id: str = "", metadata: Optional[dict] = None) -> Event:
    return _global_bus.publish(topic, data, source, correlation_id, metadata)


def subscribe(topic: str, handler: SyncHandler):
    _global_bus.subscribe(topic, handler)


def subscribe_async(topic: str, handler: AsyncHandler):
    _global_bus.subscribe_async(topic, handler)


def unsubscribe(topic: str, handler: Callable):
    _global_bus.unsubscribe(topic, handler)
