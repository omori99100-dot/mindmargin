import asyncio
import threading
import time

import pytest

from mindmargin.core.events import EventBus, Event, get_bus, publish, subscribe, subscribe_async, unsubscribe
from mindmargin.core.hardening import set_correlation_id, correlation_scope


@pytest.fixture
def bus():
    return EventBus(max_history=100)


@pytest.fixture
def fresh_bus():
    old = get_bus()
    new_bus = EventBus()
    import mindmargin.core.events as evmod
    evmod._global_bus = new_bus
    yield new_bus
    evmod._global_bus = old


class TestEvent:
    def test_event_auto_fields(self):
        with correlation_scope("test-cid"):
            e = Event(topic="test", data={"key": "val"})
        assert e._event_id
        assert e.timestamp
        assert e.correlation_id
        assert e.topic == "test"
        assert e.data == {"key": "val"}

    def test_event_custom_correlation_id(self):
        e = Event(topic="t", correlation_id="custom")
        assert e.correlation_id == "custom"


class TestEventBusPublishSubscribe:
    def test_publish_calls_sync_handler(self, bus):
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("test", handler)
        bus.publish("test", {"msg": "hello"})
        assert len(received) == 1
        assert received[0].data == {"msg": "hello"}

    def test_publish_calls_multiple_handlers(self, bus):
        results = []

        def h1(e):
            results.append("h1")

        def h2(e):
            results.append("h2")

        bus.subscribe("test", h1)
        bus.subscribe("test", h2)
        bus.publish("test")
        assert sorted(results) == ["h1", "h2"]

    def test_publish_unrelated_topic(self, bus):
        called = [False]

        def handler(e):
            called[0] = True

        bus.subscribe("topic_a", handler)
        bus.publish("topic_b")
        assert not called[0]

    def test_unsubscribe(self, bus):
        called = [False]

        def handler(e):
            called[0] = True

        bus.subscribe("test", handler)
        bus.unsubscribe("test", handler)
        bus.publish("test")
        assert not called[0]


class TestWildcard:
    def test_wildcard_match(self, bus):
        received = []

        def handler(e):
            received.append(e.topic)

        bus.subscribe("system.*", handler)
        bus.publish("system.ready")
        bus.publish("system.error")
        bus.publish("app.event")
        assert "system.ready" in received
        assert "system.error" in received
        assert "app.event" not in received


class TestEventHistory:
    def test_history_records_event(self, bus):
        bus.publish("test", {"n": 1})
        assert len(bus.history) == 1
        assert bus.history[0].topic == "test"

    def test_history_by_topic(self, bus):
        bus.publish("sys.ready")
        bus.publish("sys.error")
        bus.publish("app.start")
        hist = bus.history_by_topic("sys.*")
        assert len(hist) == 2

    def test_history_max(self, bus):
        for i in range(200):
            bus.publish(f"t{i}")
        assert len(bus.history) == 100

    def test_clear_history(self, bus):
        bus.publish("test")
        bus.clear_history()
        assert len(bus.history) == 0


class TestHandlerCount:
    def test_handler_count_total(self, bus):
        bus.subscribe("a", lambda e: None)
        bus.subscribe("b", lambda e: None)
        assert bus.handler_count() == 2

    def test_handler_count_by_topic(self, bus):
        bus.subscribe("test", lambda e: None)
        bus.subscribe("test", lambda e: None)
        assert bus.handler_count("test") == 2
        assert bus.handler_count("other") == 0


class TestAsyncEvents:
    def test_async_handler(self, bus):
        results = []

        async def handler(event):
            results.append(event.data)

        bus.subscribe_async("async_test", handler)
        bus.publish("async_test", {"a": 1})
        time.sleep(0.1)
        assert len(results) == 1
        assert results[0] == {"a": 1}


class TestCorrelationId:
    def test_event_gets_current_cid(self, bus):
        set_correlation_id("test-cid")
        received = []

        def handler(e):
            received.append(e.correlation_id)

        bus.subscribe("test", handler)
        bus.publish("test")
        assert received[0] == "test-cid"

    def test_custom_correlation_id(self, bus):
        received = []

        def handler(e):
            received.append(e.correlation_id)

        bus.subscribe("test", handler)
        bus.publish("test", correlation_id="custom-cid")
        assert received[0] == "custom-cid"


class TestGlobalBus:
    def test_global_publish_subscribe(self, fresh_bus):
        received = []

        def handler(e):
            received.append(e)

        subscribe("global", handler)
        publish("global", {"ok": True})
        assert len(received) == 1
        assert received[0].data == {"ok": True}

    def test_global_unsubscribe(self, fresh_bus):
        def handler(e):
            pass

        subscribe("g", handler)
        unsubscribe("g", handler)
        assert fresh_bus.handler_count("g") == 0


class TestBusThreadSafety:
    def test_concurrent_publish(self, bus):
        results = []
        lock = threading.Lock()

        def handler(e):
            with lock:
                results.append(e.topic)

        bus.subscribe("test", handler)
        threads = []
        for i in range(20):
            t = threading.Thread(target=lambda: bus.publish("test"))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=5)
        assert len(results) == 20


class TestEventEdgeCases:
    def test_unsubscribe_async_handler(self, bus):
        results = []
        async def handler(e):
            results.append(e.data)
        bus.subscribe_async("test", handler)
        bus.unsubscribe("test", handler)
        bus.publish("test", {"val": 1})
        time.sleep(0.1)
        assert len(results) == 0

    def test_sync_handler_exception_isolated(self, bus):
        results = []
        def broken(e):
            raise ValueError("broken")
        def ok_handler(e):
            results.append("ok")
        bus.subscribe("test", broken)
        bus.subscribe("test", ok_handler)
        bus.publish("test")
        assert results == ["ok"]

    def test_set_async_loop(self, bus):
        loop = asyncio.new_event_loop()
        bus.set_async_loop(loop)
        results = []
        async def handler(e):
            results.append(e.data)
        bus.subscribe_async("test", handler)
        bus.publish("test", {"val": 1})
        time.sleep(0.1)
        assert len(results) == 1
        loop.close()

    def test_subscribe_async_global(self, fresh_bus):
        results = []
        async def handler(e):
            results.append(e.data)
        subscribe_async("global_async", handler)
        publish("global_async", {"ok": True})
        time.sleep(0.1)
        assert len(results) == 1
