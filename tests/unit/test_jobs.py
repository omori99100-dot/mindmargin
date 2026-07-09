"""Tests for core/jobs.py — Background Job System."""

import time
from unittest.mock import patch

import pytest

from mindmargin.core.jobs import Job, JobError, run_job, _job_dir, PENDING, RUNNING, \
    COMPLETED, FAILED, CANCELLED, PAUSED


@pytest.fixture
def mock_base(tmp_path):
    with patch("mindmargin.core.jobs._safe_base", return_value=tmp_path):
        yield tmp_path


def test_create_job(mock_base):
    job = Job("job_test_001", "pipeline", {"topic": "test"})
    assert job.job_id == "job_test_001"
    assert job.job_type == "pipeline"
    assert job.state == PENDING
    assert not job.is_terminal


def test_job_lifecycle(mock_base):
    job = Job("job_lifecycle", "test")
    assert job.state == PENDING

    job.start()
    assert job.state == RUNNING

    job.complete({"status": "ok"})
    assert job.state == COMPLETED
    assert job.is_terminal


def test_job_fail(mock_base):
    job = Job("job_fail", "test")
    job.start()
    job.fail("error occurred")
    assert job.state == FAILED
    assert job.is_terminal


def test_job_cancel(mock_base):
    job = Job("job_cancel", "test")
    job.start()
    job.cancel()
    assert job.state == CANCELLED
    assert job.is_terminal


def test_job_pause_resume(mock_base):
    job = Job("job_pause", "test")
    job.start()
    job.pause()
    assert job.state == PAUSED
    job.resume()
    assert job.state == RUNNING


def test_job_transition_errors(mock_base):
    job = Job("job_trans", "test")
    # Cannot cancel a PENDING job (it needs to be started first - actually cancel works on non-terminal)
    # Actually let me check if we can cancel pending:
    job.cancel()
    assert job.state == CANCELLED

    # Cannot cancel again
    with pytest.raises(JobError):
        job.cancel()

    # Cannot resume from cancelled
    with pytest.raises(JobError):
        job.resume()


def test_job_retry(mock_base):
    job = Job("job_retry", "test", {"max_retries": 3})
    job.start()
    job.fail("temp error")
    assert job.state == FAILED

    job.retry()
    assert job.state == "RETRYING"
    assert job.to_dict()["retry_count"] == 1


def test_job_persistence(mock_base):
    job1 = Job("job_persist", "test")
    job1.start()
    job1.update_meta("progress", 50)

    job2 = Job.load("job_persist")
    assert job2 is not None
    assert job2.state == RUNNING
    assert job2.to_dict()["metadata"]["progress"] == 50


def test_load_nonexistent(mock_base):
    job = Job.load("nonexistent_job")
    assert job is None


def test_list_jobs(mock_base):
    Job("job_a", "type_a").start()
    Job("job_b", "type_b").start()
    Job("job_c", "type_c").start()

    jobs = Job.list_jobs(10)
    assert len(jobs) == 3


def test_count_by_state(mock_base):
    Job("job_1", "test").start()
    j2 = Job("job_2", "test")
    j2.start()
    j2.complete({})
    j3 = Job("job_3", "test")
    j3.start()
    j3.fail("err")

    counts = Job.count_by_state()
    assert counts.get(RUNNING, 0) == 1
    assert counts.get(COMPLETED, 0) == 1
    assert counts.get(FAILED, 0) == 1


def test_run_job_background(mock_base):
    def dummy_fn(job):
        time.sleep(0.05)
        return {"result": "done"}

    job = run_job("pipeline", dummy_fn, {"max_retries": 1})
    assert job.job_id.startswith("job_")
    # Job may be PENDING or already RUNNING — both are valid
    assert job.state in (PENDING, "RUNNING")

    time.sleep(0.2)
    reloaded = Job.load(job.job_id)
    assert reloaded.state == COMPLETED
    assert reloaded.to_dict()["result"]["result"] == "done"


def test_job_to_dict(mock_base):
    job = Job("job_dict", "test", {"key": "val"})
    d = job.to_dict()
    assert d["job_id"] == "job_dict"
    assert d["job_type"] == "test"
    assert d["params"]["key"] == "val"
    assert "created_at" in d


def test_job_update_meta(mock_base):
    job = Job("job_meta", "test")
    job.update_meta("progress", 75)
    job.update_meta("status_text", "rendering")
    assert job.to_dict()["metadata"]["progress"] == 75
    assert job.to_dict()["metadata"]["status_text"] == "rendering"


class TestJobEdgeCases:
    def test_is_running(self, mock_base):
        job = Job("job_run", "test")
        assert not job.is_running
        job.start()
        assert job.is_running

    def test_is_paused(self, mock_base):
        job = Job("job_pau", "test")
        assert not job.is_paused
        job.start()
        job.pause()
        assert job.is_paused

    def test_can_transition(self, mock_base):
        pending = Job("job_ct1", "test")
        assert pending.can_transition
        pending.start()
        pending.complete({})
        assert not pending.can_transition

    def test_start_invalid_state(self, mock_base):
        job = Job("job_start_bad", "test")
        job.start()
        with pytest.raises(JobError, match="Cannot start"):
            job.start()

    def test_pause_invalid_state(self, mock_base):
        job = Job("job_pause_bad", "test")
        with pytest.raises(JobError, match="Cannot pause"):
            job.pause()

    def test_retry_invalid_state(self, mock_base):
        job = Job("job_retry_bad", "test")
        with pytest.raises(JobError, match="Cannot retry"):
            job.retry()

    def test_load_corrupt_json(self, mock_base):
        jdir = _job_dir()
        jdir.mkdir(parents=True, exist_ok=True)
        (jdir / "corrupt_job.json").write_text("not json")
        job = Job.load("corrupt_job")
        assert job is None

    def test_list_jobs_skips_corrupt(self, mock_base):
        Job("job_list_ok", "test").start()
        bad_file = _job_dir() / "bad_list_job.json"
        bad_file.write_text("not json")
        jobs = Job.list_jobs(10)
        assert len(jobs) == 1

    def test_count_by_state_skips_corrupt(self, mock_base):
        Job("job_count_ok", "test").start()
        bad_file = _job_dir() / "bad_count_job.json"
        bad_file.write_text("not json")
        counts = Job.count_by_state()
        assert counts.get(RUNNING, 0) >= 1

    def test_load_corrupt_internal(self, mock_base):
        job = Job("job_load_int", "test")
        path = job._path
        path.write_text("not json")
        data = job._load()
        assert data == {}
