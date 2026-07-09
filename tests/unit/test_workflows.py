import json
import tempfile
import threading
import time

import pytest

from mindmargin.core.workflows import (
    WorkflowEngine,
    Workflow,
    WorkflowStep,
    WorkflowState,
    StepState,
)


@pytest.fixture
def engine():
    tmpdir = tempfile.mkdtemp()
    e = WorkflowEngine(persist_dir=tmpdir)
    yield e
    import shutil
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


class TestWorkflowEngine:
    def test_create_workflow(self, engine):
        wid = engine.create("test", [
            {"step_id": "s1", "name": "Step 1", "dependencies": []},
        ])
        assert wid.startswith("wf_test_")
        wf = engine.get(wid)
        assert wf.name == "test"
        assert wf.state == WorkflowState.PENDING

    def test_create_workflow_no_steps(self, engine):
        wid = engine.create("empty", [])
        wf = engine.get(wid)
        assert wf is not None
        assert len(wf.steps) == 0

    def test_start_workflow(self, engine):
        wid = engine.create("go", [{"step_id": "s1", "name": "S1"}])
        assert engine.start(wid)
        time.sleep(0.1)
        wf = engine.get(wid)
        assert wf.state == WorkflowState.COMPLETED

    def test_start_twice_fails(self, engine):
        wid = engine.create("t", [{"step_id": "s1"}])
        assert engine.start(wid)
        assert not engine.start(wid)

    def test_start_unknown(self, engine):
        assert not engine.start("nonexistent")


class TestWorkflowSteps:
    def test_step_execution(self, engine):
        results = []

        def handler(meta):
            results.append(meta.get("val"))
            return {"processed": meta.get("val")}

        wid = engine.create("steps", [{"step_id": "s1", "name": "S1", "metadata": {"val": 42}}])
        engine.register_step_handler(wid, "s1", handler)
        engine.start(wid)
        time.sleep(0.1)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.COMPLETED
        assert wf.steps["s1"].result == {"processed": 42}
        assert results == [42]

    def test_step_no_handler_completes(self, engine):
        wid = engine.create("nohandler", [{"step_id": "s1"}])
        engine.start(wid)
        time.sleep(0.1)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.COMPLETED

    def test_step_error_fails_step(self, engine):
        def broken(meta):
            raise ValueError("fail")

        wid = engine.create("broken", [{"step_id": "s1", "max_retries": 0}])
        engine.register_step_handler(wid, "s1", broken)
        engine.start(wid)
        time.sleep(0.2)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.FAILED
        assert "fail" in wf.steps["s1"].error

    def test_step_retry(self, engine):
        attempts = [0]

        def flaky(meta):
            attempts[0] += 1
            if attempts[0] < 2:
                raise ValueError("not yet")
            return {"ok": True}

        wid = engine.create("flaky", [{"step_id": "s1", "max_retries": 2}])
        engine.register_step_handler(wid, "s1", flaky)
        engine.start(wid)
        time.sleep(0.3)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.COMPLETED
        assert attempts[0] == 2

    def test_step_retry_exhausted(self, engine):
        attempts = [0]

        def always_fail(meta):
            attempts[0] += 1
            raise ValueError("always breaks")

        wid = engine.create("always", [{"step_id": "s1", "max_retries": 1}])
        engine.register_step_handler(wid, "s1", always_fail)
        engine.start(wid)
        time.sleep(0.3)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.FAILED
        assert attempts[0] == 2


class TestWorkflowDependencies:
    def test_dependency_ordering(self, engine):
        order = []

        def make_handler(val):
            def h(meta):
                order.append(val)
                return {}
            return h

        wid = engine.create("dag", [
            {"step_id": "s1", "name": "First"},
            {"step_id": "s2", "name": "Second", "dependencies": ["s1"]},
            {"step_id": "s3", "name": "Third", "dependencies": ["s2"]},
        ])
        engine.register_step_handler(wid, "s1", make_handler(1))
        engine.register_step_handler(wid, "s2", make_handler(2))
        engine.register_step_handler(wid, "s3", make_handler(3))
        engine.start(wid)
        time.sleep(0.3)
        assert order == [1, 2, 3]
        wf = engine.get(wid)
        assert wf.state == WorkflowState.COMPLETED

    def test_dependency_failure_propagation(self, engine):
        def fail_step(meta):
            raise ValueError("fail")

        wid = engine.create("dagfail", [
            {"step_id": "s1", "name": "Fails"},
            {"step_id": "s2", "name": "Depends", "dependencies": ["s1"]},
        ])
        engine.register_step_handler(wid, "s1", fail_step)
        engine.start(wid)
        time.sleep(0.3)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.FAILED
        assert wf.steps["s2"].state == StepState.PENDING
        assert wf.state == WorkflowState.PARTIAL

    def test_parallel_execution(self, engine):
        execution_order = []
        lock = threading.Lock()

        def make_handler(val):
            def h(meta):
                time.sleep(0.05)
                with lock:
                    execution_order.append(val)
                return {}
            return h

        wid = engine.create("parallel", [
            {"step_id": "s1", "name": "A"},
            {"step_id": "s2", "name": "B"},
            {"step_id": "s3", "name": "C"},
        ])
        engine.register_step_handler(wid, "s1", make_handler(1))
        engine.register_step_handler(wid, "s2", make_handler(2))
        engine.register_step_handler(wid, "s3", make_handler(3))
        engine.start(wid)
        time.sleep(0.3)
        assert len(execution_order) == 3
        assert all(x in execution_order for x in [1, 2, 3])


class TestWorkflowCancel:
    def test_cancel_workflow(self, engine):
        def slow(meta):
            time.sleep(0.5)
            return {}

        wid = engine.create("cancel", [{"step_id": "s1"}])
        engine.register_step_handler(wid, "s1", slow)
        engine.start(wid)
        time.sleep(0.05)
        assert engine.cancel(wid)
        wf = engine.get(wid)
        assert wf.state == WorkflowState.CANCELLED

    def test_cancel_terminal_fails(self, engine):
        wid = engine.create("done", [{"step_id": "s1"}])
        engine.start(wid)
        time.sleep(0.3)
        assert not engine.cancel(wid)

    def test_cancel_unknown(self, engine):
        assert not engine.cancel("nonexistent")


class TestWorkflowResume:
    def test_resume_failed_workflow(self, engine):
        attempts = [0]

        def flaky_then_ok(meta):
            attempts[0] += 1
            if attempts[0] == 1:
                raise ValueError("first fail")
            return {"ok": True}

        wid = engine.create("resume", [{"step_id": "s1", "max_retries": 0}])
        engine.register_step_handler(wid, "s1", flaky_then_ok)
        engine.start(wid)
        time.sleep(0.3)
        wf = engine.get(wid)
        assert wf.state == WorkflowState.PARTIAL
        engine.register_step_handler(wid, "s1", flaky_then_ok)
        assert engine.resume(wid)
        time.sleep(0.3)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.COMPLETED
        assert wf.state == WorkflowState.COMPLETED


class TestWorkflowPersistence:
    def test_saves_to_disk(self, engine):
        wid = engine.create("persist", [{"step_id": "s1"}])
        path = engine._persist_dir / f"{wid}.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["name"] == "persist"

    def test_recover_restores(self, engine):
        wid = engine.create("restore", [{"step_id": "s1"}])
        persist_dir = engine._persist_dir
        e2 = WorkflowEngine(persist_dir=str(persist_dir.parent))
        count = e2.recover()
        assert count >= 1
        assert e2.get(wid) is not None

    def test_recover_running_becomes_pending(self, engine):
        wid = engine.create("running", [{"step_id": "s1"}])
        wf = engine.get(wid)
        wf.state = WorkflowState.RUNNING
        wf.steps["s1"].state = StepState.RUNNING
        engine._save(wf)
        persist_dir = engine._persist_dir
        e2 = WorkflowEngine(persist_dir=str(persist_dir.parent))
        e2.recover()
        recovered = e2.get(wid)
        assert recovered is not None
        assert recovered.state == WorkflowState.PENDING
        assert recovered.steps["s1"].state == StepState.PENDING

    def test_recover_completed_skipped(self, engine):
        wid = engine.create("done", [{"step_id": "s1"}])
        engine.start(wid)
        time.sleep(0.2)
        persist_dir = engine._persist_dir
        e2 = WorkflowEngine(persist_dir=str(persist_dir.parent))
        count = e2.recover()
        assert count == 0


class TestWorkflowList:
    def test_list_all(self, engine):
        w1 = engine.create("a", [])
        w2 = engine.create("b", [])
        assert len(engine.list_all()) == 2

    def test_list_by_state(self, engine):
        w1 = engine.create("a", [{"step_id": "s1"}])
        engine.start(w1)
        time.sleep(0.2)
        completed = engine.list_by_state(WorkflowState.COMPLETED)
        assert len(completed) >= 1

    def test_get_unknown(self, engine):
        assert engine.get("nonexistent") is None


class TestWorkflowEdgeCases:
    def test_register_handler_unknown_workflow(self, engine):
        with pytest.raises(ValueError, match="not found"):
            engine.register_step_handler("nonexistent", "s1", lambda m: {})

    def test_register_handler_unknown_step(self, engine):
        wid = engine.create("test", [{"step_id": "s1"}])
        with pytest.raises(ValueError, match="not found"):
            engine.register_step_handler(wid, "s2", lambda m: {})

    def test_resume_unknown(self, engine):
        assert not engine.resume("nonexistent")

    def test_resume_invalid_state(self, engine):
        wid = engine.create("test", [{"step_id": "s1"}])
        assert not engine.resume(wid)

    def test_step_timeout(self, engine):
        def slow(meta):
            import time
            time.sleep(0.5)
            return {}
        wid = engine.create("slow", [{"step_id": "s1", "timeout_s": 0.1}])
        engine.register_step_handler(wid, "s1", slow)
        engine.start(wid)
        time.sleep(0.3)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.FAILED

    def test_step_sync_no_timeout(self, engine):
        results = []
        def handler(meta):
            results.append("done")
            return {"ok": True}
        wid = engine.create("sync", [{"step_id": "s1", "timeout_s": 0}])
        engine.register_step_handler(wid, "s1", handler)
        engine.start(wid)
        time.sleep(0.2)
        wf = engine.get(wid)
        assert wf.steps["s1"].state == StepState.COMPLETED
        assert results == ["done"]

    def test_delete_workflow_file(self, engine):
        wid = engine.create("test", [{"step_id": "s1"}])
        wf = engine.get(wid)
        p = engine._path_for(wf)
        assert p.exists()
        engine._delete(wf)
        assert not p.exists()

    def test_delete_missing_file(self, engine):
        wf = Workflow(workflow_id="fake", name="fake", steps={})
        engine._delete(wf)

    def test_workflow_property(self, engine):
        wid = engine.create("test", [{"step_id": "s1"}])
        assert isinstance(engine.workflows, dict)
        assert wid in engine.workflows

    def test_execute_ready_workflow_vanished(self, engine):
        wid = engine.create("test", [{"step_id": "s1"}])
        wf = engine.get(wid)
        engine.start(wid)
        time.sleep(0.2)
        recovered = engine.get(wid)
        assert recovered.state == WorkflowState.COMPLETED
