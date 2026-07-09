import json
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from mindmargin.core.scheduler import (
    Scheduler,
    Schedule,
    ScheduleState,
    parse_cron,
    cron_matches,
    next_cron_match,
)


@pytest.fixture
def scheduler():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = Scheduler(persist_dir=tmpdir)
        yield s


class TestCronParsing:
    def test_parse_every_minute(self):
        f = parse_cron("* * * * *")
        assert 0 in f["minute"]
        assert 1 in f["minute"]

    def test_parse_specific_minute(self):
        f = parse_cron("30 * * * *")
        assert 30 in f["minute"]
        assert 0 not in f["minute"]

    def test_parse_range(self):
        f = parse_cron("* 9-17 * * *")
        for h in range(9, 18):
            assert h in f["hour"]
        assert 8 not in f["hour"]
        assert 18 not in f["hour"]

    def test_parse_step(self):
        f = parse_cron("*/15 * * * *")
        assert 0 in f["minute"]
        assert 15 in f["minute"]
        assert 30 in f["minute"]
        assert 45 in f["minute"]
        assert 10 not in f["minute"]

    def test_parse_list(self):
        f = parse_cron("0,30 * * * *")
        assert 0 in f["minute"]
        assert 30 in f["minute"]
        assert 15 not in f["minute"]

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            parse_cron("invalid")


class TestCronMatching:
    def test_match_exact(self):
        f = parse_cron("30 14 * * *")
        dt = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
        assert cron_matches(f, dt)

    def test_no_match(self):
        f = parse_cron("0 * * * *")
        dt = datetime(2026, 1, 1, 14, 15, tzinfo=timezone.utc)
        assert not cron_matches(f, dt)

    def test_dow_match(self):
        f = parse_cron("0 0 * * 0")
        dt = datetime(2026, 1, 4, 0, 0, tzinfo=timezone.utc)
        assert cron_matches(f, dt)

    def test_month_match(self):
        f = parse_cron("0 0 1 1 *")
        dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert cron_matches(f, dt)


class TestNextCronMatch:
    def test_next_match_same_day(self):
        f = parse_cron("30 * * * *")
        after = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        nxt = next_cron_match(f, after)
        assert nxt is not None
        assert nxt.minute == 30
        assert nxt.hour == 10

    def test_next_match_next_hour(self):
        f = parse_cron("0 * * * *")
        after = datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)
        nxt = next_cron_match(f, after)
        assert nxt is not None
        assert nxt.minute == 0
        assert nxt.hour == 11

    def test_next_match_next_day(self):
        f = parse_cron("0 0 * * *")
        after = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        nxt = next_cron_match(f, after)
        assert nxt is not None
        assert nxt.hour == 0
        assert nxt.day == 2


class TestSchedulerRegister:
    def test_register_cron(self, scheduler):
        sid = scheduler.register("daily", lambda: None, cron="0 0 * * *")
        assert sid.startswith("sched_daily_")
        sched = scheduler.get(sid)
        assert sched.name == "daily"
        assert sched.cron == "0 0 * * *"
        assert sched.state == ScheduleState.ACTIVE

    def test_register_interval(self, scheduler):
        sid = scheduler.register("every10", lambda: None, interval_s=10)
        sched = scheduler.get(sid)
        assert sched.interval_s == 10

    def test_register_neither_cron_nor_interval(self, scheduler):
        with pytest.raises(ValueError):
            scheduler.register("bad", lambda: None)

    def test_register_with_dependencies(self, scheduler):
        sid1 = scheduler.register("a", lambda: None, interval_s=10)
        sid2 = scheduler.register("b", lambda: None, interval_s=10, dependencies=[sid1])
        sched = scheduler.get(sid2)
        assert sid1 in sched.dependencies

    def test_register_with_timeout(self, scheduler):
        sid = scheduler.register("quick", lambda: None, interval_s=5, timeout_s=30)
        assert scheduler.get(sid).timeout_s == 30


class TestSchedulerPauseResume:
    def test_pause(self, scheduler):
        sid = scheduler.register("t", lambda: None, interval_s=10)
        assert scheduler.pause(sid)
        assert scheduler.get(sid).state == ScheduleState.PAUSED

    def test_resume(self, scheduler):
        sid = scheduler.register("t", lambda: None, interval_s=10)
        scheduler.pause(sid)
        assert scheduler.resume(sid)
        assert scheduler.get(sid).state == ScheduleState.ACTIVE

    def test_pause_not_active(self, scheduler):
        sid = scheduler.register("t", lambda: None, interval_s=10)
        scheduler.pause(sid)
        assert not scheduler.pause(sid)

    def test_pause_unknown(self, scheduler):
        assert not scheduler.pause("nonexistent")

    def test_disable(self, scheduler):
        sid = scheduler.register("t", lambda: None, interval_s=10)
        assert scheduler.disable(sid)
        assert scheduler.get(sid).state == ScheduleState.DISABLED


class TestSchedulerList:
    def test_list_all(self, scheduler):
        scheduler.register("a", lambda: None, interval_s=10)
        scheduler.register("b", lambda: None, interval_s=20)
        assert len(scheduler.list_all()) == 2

    def test_list_by_state(self, scheduler):
        sid = scheduler.register("a", lambda: None, interval_s=10)
        scheduler.register("b", lambda: None, interval_s=20)
        scheduler.pause(sid)
        active = scheduler.list_by_state(ScheduleState.ACTIVE)
        paused = scheduler.list_by_state(ScheduleState.PAUSED)
        assert len(active) == 1
        assert len(paused) == 1


class TestSchedulerDependencies:
    def test_dependency_not_met_blocks_execution(self, scheduler):
        results = []

        def make_handler(val):
            def h():
                results.append(val)
            return h

        sid_dep = scheduler.register("dep", make_handler("dep"), interval_s=0.1)
        sid_main = scheduler.register("main", make_handler("main"), interval_s=0.1, dependencies=[sid_dep])
        scheduler.start()
        time.sleep(0.3)
        scheduler.stop()
        assert "dep" not in results or "main" not in results


class TestSchedulerPersistence:
    def test_saves_to_disk(self, scheduler):
        sid = scheduler.register("persist", lambda: None, cron="0 * * * *")
        path = scheduler._persist_dir / f"{sid}.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["name"] == "persist"

    def test_recover_restores_schedules(self, scheduler):
        scheduler.register("restore", lambda: None, interval_s=10)
        persist_dir = scheduler._persist_dir
        s2 = Scheduler(persist_dir=str(persist_dir.parent))
        count = s2.recover()
        assert count >= 1
        schedules = s2.list_all()
        names = [s.name for s in schedules]
        assert "restore" in names

    def test_recover_disabled_skipped(self, scheduler):
        sid = scheduler.register("disabled", lambda: None, interval_s=10)
        scheduler.disable(sid)
        persist_dir = scheduler._persist_dir
        s2 = Scheduler(persist_dir=str(persist_dir.parent))
        count = s2.recover()
        assert count == 0


class TestSchedulerExecute:
    def test_execute_handler(self, scheduler):
        executed = [False]

        def handler():
            executed[0] = True

        sid = scheduler.register("exec_test", handler, cron="*/5 * * * *")
        scheduler._execute(sid)
        time.sleep(0.1)
        sched = scheduler.get(sid)
        assert sched.total_runs == 1

    def test_execute_error_logged(self, scheduler):
        def broken():
            raise ValueError("boom")

        sid = scheduler.register("broken", broken, interval_s=0.1)
        scheduler._execute(sid)
        time.sleep(0.2)
        sched = scheduler.get(sid)
        assert sched.failed_runs == 1
        assert sched.total_runs == 0


class TestSchedulerDetectMissed:
    def test_detect_missed(self, scheduler):
        sid = scheduler.register("missed", lambda: None, cron="*/5 * * * *")
        scheduler._schedules[sid].next_run_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        missed = scheduler.detect_missed()
        assert len(missed) >= 1
        assert missed[0]["schedule_id"] == sid

    def test_catch_up(self, scheduler):
        executed = [False]

        def handler():
            executed[0] = True

        sid = scheduler.register("catchup_test", handler, interval_s=10, catch_up=True)
        assert scheduler.catch_up(sid)
        time.sleep(0.1)
        assert executed[0]


class TestSchedulerEdgeCases:
    def test_cron_range_with_step(self):
        f = parse_cron("* 1-10/2 * * *")
        assert 1 in f["hour"]
        assert 3 in f["hour"]
        assert 9 in f["hour"]
        assert 11 not in f["hour"]

    def test_cron_single_with_step(self):
        f = parse_cron("* 5/2 * * *")
        assert 5 in f["hour"]
        assert 7 in f["hour"]
        assert 23 in f["hour"]
        assert 3 not in f["hour"]

    def test_cron_matches_default_dt(self):
        f = parse_cron("* * * * *")
        assert cron_matches(f) is True

    def test_next_cron_no_match(self):
        f = parse_cron("0 0 30 2 *")
        nxt = next_cron_match(f, after=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc))
        assert nxt is None

    def test_compute_next_cron_no_fields(self, scheduler):
        result = scheduler._compute_next_cron("nonexistent")
        assert result == ""

    def test_compute_next_cron_invalid_last_run(self, scheduler):
        sid = scheduler.register("test", lambda: None, cron="0 * * * *")
        scheduler._schedules[sid].last_run_at = "not-a-date"
        result = scheduler._compute_next_cron(sid)
        assert result != ""

    def test_resume_not_paused(self, scheduler):
        sid = scheduler.register("test", lambda: None, interval_s=10)
        assert not scheduler.resume(sid)

    def test_resume_unknown(self, scheduler):
        assert not scheduler.resume("nonexistent")

    def test_disable_unknown(self, scheduler):
        assert not scheduler.disable("nonexistent")

    def test_get_unknown(self, scheduler):
        assert scheduler.get("nonexistent") is None

    def test_loop_skips_non_active(self, scheduler):
        sid = scheduler.register("test", lambda: None, interval_s=0.1)
        scheduler.pause(sid)
        scheduler._loop()
        sched = scheduler.get(sid)
        assert sched.total_runs == 0

    def test_execute_no_handler(self, scheduler):
        sid = scheduler.register("test", lambda: None, interval_s=10)
        scheduler._handlers.pop(sid, None)
        scheduler._execute(sid)

    def test_execute_timeout_branch(self, scheduler):
        def slow():
            import time
            time.sleep(0.5)
        sid = scheduler.register("slow", slow, interval_s=10, timeout_s=0.1)
        scheduler._execute(sid)
        time.sleep(0.3)
        sched = scheduler.get(sid)
        assert sched.failed_runs == 1

    def test_detect_missed_skips_non_active(self, scheduler):
        sid = scheduler.register("test", lambda: None, cron="*/5 * * * *")
        scheduler.pause(sid)
        scheduler._schedules[sid].next_run_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        missed = scheduler.detect_missed()
        assert len(missed) == 0

    def test_detect_missed_invalid_date(self, scheduler):
        sid = scheduler.register("test", lambda: None, cron="*/5 * * * *")
        scheduler._schedules[sid].next_run_at = "invalid-date"
        missed = scheduler.detect_missed()
        assert len(missed) == 0

    def test_catch_up_no_schedule(self, scheduler):
        assert not scheduler.catch_up("nonexistent")
