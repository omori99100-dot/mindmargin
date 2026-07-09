import logging
import threading
import time
from pathlib import Path

import pytest

from mindmargin.core.hardening import (
    generate_correlation_id,
    set_correlation_id,
    get_correlation_id,
    correlation_scope,
    StructuredLogger,
    validate_config,
    register_shutdown_hook,
    run_shutdown_hooks,
    _reset_shutdown_hooks,
    TimeoutGuard,
    ExecutionGuard,
    safe_path,
    safe_filename,
    utcnow,
    utcnow_ts,
)


class TestCorrelationId:
    def test_generate(self):
        cid = generate_correlation_id()
        assert len(cid) == 16
        assert isinstance(cid, str)

    def test_set_get(self):
        cid = set_correlation_id("my-cid")
        assert cid == "my-cid"
        assert get_correlation_id() == "my-cid"

    def test_auto_generate(self):
        cid = set_correlation_id()
        assert cid is not None

    def test_context_manager(self):
        outer = get_correlation_id()
        with correlation_scope("inner-cid") as cid:
            assert cid == "inner-cid"
            assert get_correlation_id() == "inner-cid"
        assert get_correlation_id() == outer

    def test_context_manager_nested(self):
        with correlation_scope("a") as cid_a:
            assert cid_a == "a"
            with correlation_scope("b") as cid_b:
                assert cid_b == "b"
                assert get_correlation_id() == "b"
            assert get_correlation_id() == "a"


class TestStructuredLogger:
    def test_log_with_correlation_id(self, caplog):
        caplog.set_level(logging.INFO)
        logger = StructuredLogger("test_logger")
        set_correlation_id("test-cid")
        logger.info("hello %s", "world")
        record = caplog.records[-1]
        assert record.message == "hello world"
        assert "correlation_id" in dir(record)


class TestValidateConfig:
    def test_valid_config(self):
        schema = {"name": str, "count": int}
        config = {"name": "test", "count": 5}
        assert validate_config(config, schema) == []

    def test_missing_key(self):
        schema = {"name": str, "count": int}
        config = {"name": "test"}
        errors = validate_config(config, schema)
        assert any("count" in e for e in errors)

    def test_wrong_type(self):
        schema = {"count": int}
        config = {"count": "not an int"}
        errors = validate_config(config, schema)
        assert any("count" in e for e in errors)

    def test_empty_config(self):
        schema = {"required_key": str}
        errors = validate_config({}, schema)
        assert len(errors) == 1


class TestShutdownHooks:
    def setup_method(self):
        _reset_shutdown_hooks()

    def test_register_and_run(self):
        results = []

        def hook():
            results.append("done")

        register_shutdown_hook(hook, priority=100)
        run_shutdown_hooks()
        assert "done" in results

    def test_register_priority_order(self):
        results = []

        def make_hook(val):
            def h():
                results.append(val)
            return h

        register_shutdown_hook(make_hook(1), priority=50)
        register_shutdown_hook(make_hook(2), priority=10)
        run_shutdown_hooks()
        assert results == [1, 2]

    def test_hook_error_does_not_block(self):
        results = []

        def broken():
            raise ValueError("fail")

        def ok():
            results.append("ok")

        register_shutdown_hook(broken, priority=50)
        register_shutdown_hook(ok, priority=10)
        run_shutdown_hooks()
        assert "ok" in results

    def test_idempotent(self):
        _reset_shutdown_hooks()
        call_count = [0]

        def hook():
            call_count[0] += 1

        register_shutdown_hook(hook)
        run_shutdown_hooks()
        run_shutdown_hooks()
        assert call_count[0] == 1


class TestTimeoutGuard:
    def test_no_timeout(self):
        with TimeoutGuard(timeout_s=1.0) as guard:
            pass
        assert not guard.timed_out

    def test_timeout_occurs(self):
        with TimeoutGuard(timeout_s=0.05) as guard:
            time.sleep(0.2)
        assert guard.timed_out

    def test_zero_timeout_no_guard(self):
        with TimeoutGuard(timeout_s=0) as guard:
            time.sleep(0.1)
        assert not guard.timed_out


class TestExecutionGuard:
    def test_acquire_release(self):
        guard = ExecutionGuard()
        assert guard.acquire()
        guard.release()
        assert guard.acquire()

    def test_acquire_twice_fails(self):
        guard = ExecutionGuard()
        guard.acquire()
        assert not guard.acquire()
        guard.release()

    def test_context_manager(self):
        guard = ExecutionGuard()
        with guard:
            assert guard._running
        assert not guard._running

    def test_context_manager_already_running(self):
        guard = ExecutionGuard()
        guard.acquire()
        with pytest.raises(RuntimeError):
            with guard:
                pass
        guard.release()


class TestSafePath:
    def test_valid_path(self, tmp_path):
        result = safe_path(tmp_path, "subdir/file.txt")
        assert result == (tmp_path / "subdir/file.txt").resolve()

    def test_path_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal"):
            safe_path(tmp_path, "../../etc/passwd")

    def test_valid_absolute(self, tmp_path):
        inner = tmp_path / "sub"
        inner.mkdir()
        f = inner / "f.txt"
        f.write_text("")
        result = safe_path(tmp_path, str(f))
        assert result == f.resolve()


class TestSafeFilename:
    def test_clean_name(self):
        assert safe_filename("hello_world.txt") == "hello_world.txt"

    def test_remove_special_chars(self):
        assert safe_filename("hello<>world|file.txt") == "hello__world_file.txt"

    def test_spaces_preserved(self):
        assert " " in safe_filename("my file.txt")

    def test_strip_whitespace(self):
        result = safe_filename("  file.txt  ")
        assert result == "file.txt"


class TestUtcNow:
    def test_utcnow_string(self):
        now = utcnow()
        assert "T" in now
        assert now.endswith("+00:00") or "+" in now or "Z" not in now

    def test_utcnow_ts(self):
        ts = utcnow_ts()
        assert ts > 1_700_000_000


class TestHardeningEdgeCases:
    def test_structured_logger_warning(self, caplog):
        caplog.set_level(logging.WARNING)
        logger = StructuredLogger("test_warn")
        logger.warning("warn message")
        assert any("warn message" in r.message for r in caplog.records)

    def test_structured_logger_error(self, caplog):
        caplog.set_level(logging.ERROR)
        logger = StructuredLogger("test_err")
        logger.error("error message")
        assert any("error message" in r.message for r in caplog.records)

    def test_structured_logger_debug(self, caplog):
        caplog.set_level(logging.DEBUG)
        logger = StructuredLogger("test_dbg")
        logger.debug("debug message")
        assert any("debug message" in r.message for r in caplog.records)
