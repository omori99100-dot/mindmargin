"""Unit tests for mindmargin.github modules."""

import pytest
from pathlib import Path


# ── State Tests ──

class TestWorkflowRunState:
    def test_terminal_states(self):
        from mindmargin.github.state import WorkflowRunState
        assert WorkflowRunState.COMPLETED.is_terminal
        assert WorkflowRunState.FAILED.is_terminal
        assert WorkflowRunState.CANCELLED.is_terminal
        assert WorkflowRunState.TIMED_OUT.is_terminal
        assert not WorkflowRunState.IN_PROGRESS.is_terminal
        assert not WorkflowRunState.QUEUED.is_terminal

    def test_success_and_failure(self):
        from mindmargin.github.state import WorkflowRunState
        assert WorkflowRunState.COMPLETED.is_success
        assert not WorkflowRunState.FAILED.is_success
        assert WorkflowRunState.FAILED.is_failure
        assert WorkflowRunState.TIMED_OUT.is_failure
        assert not WorkflowRunState.COMPLETED.is_failure


class TestJobState:
    def test_terminal(self):
        from mindmargin.github.state import JobState
        assert JobState.COMPLETED.is_terminal
        assert JobState.FAILED.is_terminal
        assert not JobState.IN_PROGRESS.is_terminal


class TestWorkflowRun:
    def test_create_and_serialize(self):
        from mindmargin.github.state import WorkflowRun, WorkflowRunState
        run = WorkflowRun(run_id="r1", workflow_name="test", state=WorkflowRunState.QUEUED)
        d = run.to_dict()
        assert d["run_id"] == "r1"
        assert d["state"] == "queued"

    def test_roundtrip(self):
        from mindmargin.github.state import WorkflowRun, WorkflowRunState, JobRun, JobState
        run = WorkflowRun(run_id="r2", workflow_name="test", state=WorkflowRunState.IN_PROGRESS)
        run.jobs["j1"] = JobRun(job_id="j1", name="build", state=JobState.COMPLETED)
        d = run.to_dict()
        run2 = WorkflowRun.from_dict(d)
        assert run2.run_id == "r2"
        assert "j1" in run2.jobs
        assert run2.jobs["j1"].state == JobState.COMPLETED


class TestRunStateStore:
    def test_save_and_get(self, tmp_path):
        from mindmargin.github.state import RunStateStore, WorkflowRun, WorkflowRunState
        store = RunStateStore(persist_dir=str(tmp_path))
        run = WorkflowRun(run_id="test_run", workflow_name="test", state=WorkflowRunState.PENDING)
        store.save(run)
        got = store.get("test_run")
        assert got is not None
        assert got.run_id == "test_run"

    def test_list_runs(self, tmp_path):
        from mindmargin.github.state import RunStateStore, WorkflowRun, WorkflowRunState
        store = RunStateStore(persist_dir=str(tmp_path))
        for i in range(5):
            run = WorkflowRun(run_id=f"run_{i}", workflow_name="test", state=WorkflowRunState.COMPLETED)
            store.save(run)
        runs = store.list_runs(workflow_name="test")
        assert len(runs) == 5

    def test_count_by_state(self, tmp_path):
        from mindmargin.github.state import RunStateStore, WorkflowRun, WorkflowRunState
        store = RunStateStore(persist_dir=str(tmp_path))
        store.save(WorkflowRun(run_id="r1", workflow_name="t", state=WorkflowRunState.COMPLETED))
        store.save(WorkflowRun(run_id="r2", workflow_name="t", state=WorkflowRunState.FAILED))
        counts = store.count_by_state()
        assert counts.get("completed") == 1
        assert counts.get("failed") == 1

    def test_delete(self, tmp_path):
        from mindmargin.github.state import RunStateStore, WorkflowRun, WorkflowRunState
        store = RunStateStore(persist_dir=str(tmp_path))
        store.save(WorkflowRun(run_id="del", workflow_name="t", state=WorkflowRunState.PENDING))
        assert store.delete("del") is True
        assert store.get("del") is None
        assert store.delete("del") is False


# ── Workflow Tests ──

class TestWorkflowRegistry:
    def test_defaults_registered(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        defs = reg.list_all()
        assert len(defs) >= 5
        names = [d.name for d in defs]
        assert "Daily Content Pipeline" in names

    def test_get_by_id(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        defn = reg.get("daily_pipeline")
        assert defn is not None
        assert defn.name == "Daily Content Pipeline"

    def test_list_by_tag(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        analytics = reg.list_by_tag("analytics")
        assert len(analytics) >= 1

    def test_enable_disable(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        assert reg.disable("daily_pipeline") is True
        assert reg.get("daily_pipeline").enabled is False
        assert reg.enable("daily_pipeline") is True
        assert reg.get("daily_pipeline").enabled is True

    def test_select_workflow(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        selected = reg.select_workflow({"tag": "recovery"})
        assert selected is not None
        assert "recovery" in selected.tags

    def test_create_chain(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        chain = reg.create_chain("test_chain", ["analytics_only", "intelligence_cycle"])
        assert chain.chain_id.startswith("chain_")
        assert len(chain.workflow_ids) == 2

    def test_get_scheduled(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        scheduled = reg.get_scheduled_workflows()
        assert len(scheduled) >= 2
        assert all(d.cron for d in scheduled)

    def test_handler_registration(self):
        from mindmargin.github.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        handler = lambda x: {"status": "ok"}
        reg.register_handler("test_handler", handler)
        assert reg.get_handler("test_handler") is handler


# ── Artifact Tests ──

class TestArtifactStore:
    def test_store_and_get(self, tmp_path):
        from mindmargin.github.artifacts import ArtifactStore, ArtifactType
        store = ArtifactStore(persist_dir=str(tmp_path))
        src = tmp_path / "test.txt"
        src.write_text("content")
        art = store.store("test_artifact", ArtifactType.SCRIPT, str(src))
        assert art.artifact_id.startswith("art_")
        assert art.size_bytes == 7
        assert store.get(art.artifact_id) is not None

    def test_list_by_type(self, tmp_path):
        from mindmargin.github.artifacts import ArtifactStore, ArtifactType
        store = ArtifactStore(persist_dir=str(tmp_path))
        for i in range(3):
            src = tmp_path / f"f{i}.txt"
            src.write_text("x")
            store.store(f"art_{i}", ArtifactType.LOGS, str(src))
        arts = store.list_artifacts(artifact_type="logs")
        assert len(arts) == 3

    def test_stats(self, tmp_path):
        from mindmargin.github.artifacts import ArtifactStore, ArtifactType
        store = ArtifactStore(persist_dir=str(tmp_path))
        src = tmp_path / "stat.txt"
        src.write_bytes(b"\x00" * 100)
        store.store("stat_art", ArtifactType.VIDEO, str(src))
        stats = store.get_stats()
        assert stats["total_artifacts"] == 1
        assert stats["total_size_bytes"] == 100

    def test_delete(self, tmp_path):
        from mindmargin.github.artifacts import ArtifactStore, ArtifactType
        store = ArtifactStore(persist_dir=str(tmp_path))
        src = tmp_path / "del.txt"
        src.write_text("x")
        art = store.store("del_art", ArtifactType.SCRIPT, str(src))
        assert store.delete(art.artifact_id) is True
        assert store.get(art.artifact_id) is None


# ── Monitor Tests ──

class TestGitHubMonitor:
    def test_record_metric(self, tmp_path):
        from mindmargin.github.monitor import GitHubMonitor
        mon = GitHubMonitor(persist_dir=str(tmp_path))
        mon.record_metric("test.metric", 42.0, "count")
        metrics = mon.get_metrics("test.metric")
        assert len(metrics) == 1
        assert metrics[0]["value"] == 42.0

    def test_increment(self, tmp_path):
        from mindmargin.github.monitor import GitHubMonitor
        mon = GitHubMonitor(persist_dir=str(tmp_path))
        mon.increment("hits")
        mon.increment("hits")
        metrics = mon.get_metrics("hits")
        assert len(metrics) >= 1

    def test_alert(self, tmp_path):
        from mindmargin.github.monitor import GitHubMonitor
        mon = GitHubMonitor(persist_dir=str(tmp_path))
        mon.alert("warning", "test alert", source="test")
        alerts = mon.get_alerts("warning")
        assert len(alerts) == 1
        assert alerts[0]["message"] == "test alert"

    def test_health_report(self, tmp_path):
        from mindmargin.github.monitor import GitHubMonitor
        mon = GitHubMonitor(persist_dir=str(tmp_path))
        report = mon.get_health_report()
        assert report["status"] == "healthy"
        assert report["health_score"] == 100.0

    def test_health_degraded(self, tmp_path):
        from mindmargin.github.monitor import GitHubMonitor
        mon = GitHubMonitor(persist_dir=str(tmp_path))
        for _ in range(10):
            mon.alert("error", "err", source="test")
        report = mon.get_health_report()
        assert report["status"] == "degraded"

    def test_workflow_tracking(self, tmp_path):
        from mindmargin.github.monitor import GitHubMonitor
        mon = GitHubMonitor(persist_dir=str(tmp_path))
        mon.record_workflow_started("test_wf")
        mon.record_workflow_completed("test_wf", 10.5)
        summary = mon.get_summary()
        assert any("workflows.started" in k for k in summary["counters"])

    def test_clear(self, tmp_path):
        from mindmargin.github.monitor import GitHubMonitor
        mon = GitHubMonitor(persist_dir=str(tmp_path))
        mon.record_metric("m", 1.0)
        mon.clear()
        assert mon.get_metrics() == []


# ── Recovery Tests ──

class TestFailureClassifier:
    def test_classify_timeout(self):
        from mindmargin.github.recovery import FailureClassifier
        from mindmargin.github.state import WorkflowRun, WorkflowRunState, JobRun, JobState
        run = WorkflowRun(run_id="r", workflow_name="t", state=WorkflowRunState.FAILED)
        job = JobRun(job_id="j", name="j", state=JobState.FAILED, error="timeout exceeded")
        ft = FailureClassifier.classify(run, job)
        assert ft.value == "timeout"

    def test_classify_secret(self):
        from mindmargin.github.recovery import FailureClassifier
        from mindmargin.github.state import WorkflowRun, WorkflowRunState, JobRun, JobState
        run = WorkflowRun(run_id="r", workflow_name="t", state=WorkflowRunState.FAILED)
        job = JobRun(job_id="j", name="j", state=JobState.FAILED, error="unauthorized 401")
        ft = FailureClassifier.classify(run, job)
        assert ft.value == "secret_missing"

    def test_should_retry(self):
        from mindmargin.github.recovery import FailureClassifier
        from mindmargin.github.state import FailureType
        assert FailureClassifier.should_retry(FailureType.FLAKY, 0)
        assert not FailureClassifier.should_retry(FailureType.FLAKY, 5)
        assert not FailureClassifier.should_retry(FailureType.CODE_ERROR, 0)


class TestRecoveryEngine:
    def test_diagnose(self, tmp_path):
        from mindmargin.github.recovery import RecoveryEngine
        from mindmargin.github.state import WorkflowRun, WorkflowRunState, JobRun, JobState
        engine = RecoveryEngine(persist_dir=str(tmp_path))
        run = WorkflowRun(run_id="r1", workflow_name="t", state=WorkflowRunState.FAILED,
                         metadata={"error": "timeout exceeded"})
        run.jobs["j1"] = JobRun(job_id="j1", name="build", state=JobState.FAILED, error="timeout")
        diagnosis = engine.diagnose(run)
        assert diagnosis["overall_failure_type"] == "timeout"
        assert len(diagnosis["failed_jobs"]) == 1

    def test_get_actions(self, tmp_path):
        from mindmargin.github.recovery import RecoveryEngine
        engine = RecoveryEngine(persist_dir=str(tmp_path))
        actions = engine.get_actions()
        assert isinstance(actions, list)


# ── Secrets Tests ──

class TestSecretsValidator:
    def test_validate_secrets(self, tmp_path):
        from mindmargin.github.secrets import SecretsValidator
        validator = SecretsValidator(persist_dir=str(tmp_path))
        report = validator.validate_secrets()
        assert report.total_checks > 0
        assert report.passed >= 0

    def test_validate_env_vars(self, tmp_path):
        from mindmargin.github.secrets import SecretsValidator
        validator = SecretsValidator(persist_dir=str(tmp_path))
        results = validator.validate_env_vars()
        assert isinstance(results, list)
        assert len(results) >= 3

    def test_validate_all(self, tmp_path):
        from mindmargin.github.secrets import SecretsValidator
        validator = SecretsValidator(persist_dir=str(tmp_path))
        result = validator.validate_all()
        assert "secrets" in result
        assert "env_vars" in result
        assert "repository_config" in result

    def test_status(self, tmp_path):
        from mindmargin.github.secrets import SecretsValidator
        validator = SecretsValidator(persist_dir=str(tmp_path))
        status = validator.get_status()
        assert "total_validations" in status
        assert "required_count" in status


# ── Runner Tests ──

class TestRunnerManager:
    def test_update_runner(self, tmp_path):
        from mindmargin.github.runner import RunnerManager
        mgr = RunnerManager(persist_dir=str(tmp_path))
        mgr.update_runner(1, name="runner-1", status="online", os="linux")
        runner = mgr.get_runner(1)
        assert runner is not None
        assert runner.name == "runner-1"

    def test_pool_status(self, tmp_path):
        from mindmargin.github.runner import RunnerManager
        mgr = RunnerManager(persist_dir=str(tmp_path))
        mgr.update_runner(1, name="r1", status="online")
        mgr.update_runner(2, name="r2", status="online")
        pool = mgr.get_pool_status()
        assert pool.total_runners == 2

    def test_availability_score(self, tmp_path):
        from mindmargin.github.runner import RunnerManager
        mgr = RunnerManager(persist_dir=str(tmp_path))
        mgr.update_runner(1, name="r1", status="online")
        score = mgr.get_availability_score()
        assert score == 1.0


# ── Reports Tests ──

class TestReportGenerator:
    def test_workflow_report(self, tmp_path):
        from mindmargin.github.reports import ReportGenerator
        gen = ReportGenerator(persist_dir=str(tmp_path))
        report = gen.generate_workflow_report({
            "run_id": "r1", "workflow_name": "test",
            "state": "completed", "duration_s": 10.0,
            "jobs": {"j1": {"name": "build", "state": "completed"}},
        })
        assert report.report_type == "workflow"
        assert "test" in report.title

    def test_failure_report(self, tmp_path):
        from mindmargin.github.reports import ReportGenerator
        gen = ReportGenerator(persist_dir=str(tmp_path))
        report = gen.generate_failure_report({
            "workflow_name": "test", "overall_failure_type": "timeout",
            "failed_jobs": [{"job_name": "build", "failure_type": "timeout", "error": "timed out"}],
            "recommendation": "retry",
        })
        assert report.report_type == "failure"

    def test_list_reports(self, tmp_path):
        from mindmargin.github.reports import ReportGenerator
        gen = ReportGenerator(persist_dir=str(tmp_path))
        gen.generate_workflow_report({"run_id": "r1", "workflow_name": "t", "state": "ok", "jobs": {}})
        reports = gen.list_reports()
        assert len(reports) == 1


# ── Dispatcher Tests ──

class TestWorkflowDispatcher:
    def test_dispatch(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        from mindmargin.github.dispatcher import WorkflowDispatcher
        controller = GitHubController(persist_dir=str(tmp_path))
        dispatcher = WorkflowDispatcher(controller)
        result = dispatcher.dispatch("analytics_only")
        assert result.dispatched is True
        assert result.run_id != ""

    def test_dispatch_nonexistent(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        from mindmargin.github.dispatcher import WorkflowDispatcher
        controller = GitHubController(persist_dir=str(tmp_path))
        dispatcher = WorkflowDispatcher(controller)
        result = dispatcher.dispatch("nonexistent_workflow")
        assert result.dispatched is False

    def test_dispatch_log(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        from mindmargin.github.dispatcher import WorkflowDispatcher
        controller = GitHubController(persist_dir=str(tmp_path))
        dispatcher = WorkflowDispatcher(controller)
        dispatcher.dispatch("analytics_only")
        log = dispatcher.get_dispatch_log()
        assert len(log) >= 1

    def test_cron_matching(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        from mindmargin.github.dispatcher import WorkflowDispatcher
        controller = GitHubController(persist_dir=str(tmp_path))
        dispatcher = WorkflowDispatcher(controller)
        from datetime import datetime, timezone
        now = datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc)
        assert dispatcher._cron_matches_now("0 8 * * *", now)
        assert not dispatcher._cron_matches_now("0 9 * * *", now)


# ── Controller Tests ──

class TestGitHubController:
    def test_start_workflow(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController(persist_dir=str(tmp_path))
        result = ctrl.start_workflow("analytics_only")
        assert result["status"] == "started"
        assert "run_id" in result

    def test_start_nonexistent(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController(persist_dir=str(tmp_path))
        result = ctrl.start_workflow("no_such")
        assert result["status"] == "failed"

    def test_cancel_workflow(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController(persist_dir=str(tmp_path))
        start = ctrl.start_workflow("analytics_only")
        result = ctrl.cancel_workflow(start["run_id"])
        assert result["status"] == "cancelled"

    def test_get_status(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController(persist_dir=str(tmp_path))
        status = ctrl.get_status()
        assert status.total_runs == 0
        assert status.health_score == 100.0

    def test_update_policy(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController(persist_dir=str(tmp_path))
        policy = ctrl.update_policy(max_concurrent_workflows=5)
        assert policy["max_concurrent_workflows"] == 5

    def test_emergency_stop(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController(persist_dir=str(tmp_path))
        ctrl.update_policy(emergency_stop=True)
        result = ctrl.start_workflow("analytics_only")
        assert result["status"] == "blocked"

    def test_maintenance_mode(self, tmp_path):
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController(persist_dir=str(tmp_path))
        ctrl.update_policy(maintenance_mode=True)
        result = ctrl.start_workflow("analytics_only")
        assert result["status"] == "blocked"
