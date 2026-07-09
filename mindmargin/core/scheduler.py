import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from mindmargin.config import settings
from mindmargin.core.events import publish
from mindmargin.core.hardening import utcnow, utcnow_ts

logger = logging.getLogger(__name__)


class ScheduleState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    COMPLETED = "completed"


@dataclass
class Schedule:
    schedule_id: str
    name: str
    cron: str = ""
    interval_s: float = 0
    state: ScheduleState = ScheduleState.ACTIVE
    last_run_at: str = ""
    next_run_at: str = ""
    created_at: str = ""
    total_runs: int = 0
    failed_runs: int = 0
    timeout_s: float = 300
    catch_up: bool = True
    dependencies: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def parse_cron(expr: str) -> dict:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr}")
    fields = ["minute", "hour", "day_of_month", "month", "day_of_week"]
    result = {}
    for field_name, part in zip(fields, parts):
        result[field_name] = _parse_cron_field(part, field_name)
    return result


def _parse_cron_field(part: str, field_name: str) -> set[int]:
    ranges = {
        "minute": (0, 59),
        "hour": (0, 23),
        "day_of_month": (1, 31),
        "month": (1, 12),
        "day_of_week": (0, 6),
    }
    lo, hi = ranges[field_name]
    values: set[int] = set()
    for segment in part.split(","):
        if "/" in segment:
            base, step = segment.split("/")
            step = int(step)
            if base == "*":
                base_lo, base_hi = lo, hi
            elif "-" in base:
                base_lo, base_hi = (int(x) for x in base.split("-"))
            else:
                base_lo, base_hi = int(base), hi
            values.update(range(base_lo, base_hi + 1, step))
        elif "-" in segment:
            a, b = (int(x) for x in segment.split("-"))
            values.update(range(a, b + 1))
        elif segment == "*":
            values.update(range(lo, hi + 1))
        else:
            values.add(int(segment))
    return values


def _py_dow_to_cron(py_dow: int) -> int:
    return (py_dow + 1) % 7


def cron_matches(cron_fields: dict, dt: Optional[datetime] = None) -> bool:
    if dt is None:
        dt = datetime.now(timezone.utc)
    for field_name, value in [
        ("minute", dt.minute),
        ("hour", dt.hour),
        ("day_of_month", dt.day),
        ("month", dt.month),
        ("day_of_week", _py_dow_to_cron(dt.weekday())),
    ]:
        if value not in cron_fields.get(field_name, {value}):
            return False
    return True


def next_cron_match(cron_fields: dict, after: Optional[datetime] = None) -> Optional[datetime]:
    dt = (after or datetime.now(timezone.utc)) + timedelta(minutes=1)
    dt = dt.replace(second=0, microsecond=0)
    for _ in range(525600):
        if cron_matches(cron_fields, dt):
            return dt
        dt += timedelta(minutes=1)
    return None


class Scheduler:
    def __init__(self, persist_dir: str = ""):
        self._schedules: dict[str, Schedule] = {}
        self._handlers: dict[str, Callable] = {}
        self._handler_names: dict[str, str] = {}
        self._lock = threading.RLock()
        self._running = False
        self._worker: Optional[threading.Thread] = None
        self._cron_fields: dict[str, dict] = {}
        root = Path(persist_dir or settings.storage.temp_root)
        self._persist_dir = root / "scheduler"
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._event_handlers: list = []

    def register(self, name: str, handler: Callable, cron: str = "",
                 interval_s: float = 0, timeout_s: float = 300,
                 catch_up: bool = True, dependencies: Optional[list[str]] = None):
        if not cron and interval_s <= 0:
            raise ValueError("Either cron or interval_s must be set")
        sid = f"sched_{name}_{int(utcnow_ts())}"
        sched = Schedule(
            schedule_id=sid,
            name=name,
            cron=cron,
            interval_s=interval_s,
            timeout_s=timeout_s,
            catch_up=catch_up,
            dependencies=dependencies or [],
            created_at=utcnow(),
        )
        if cron:
            self._cron_fields[sid] = parse_cron(cron)
            sched.next_run_at = self._compute_next_cron(sid)
        else:
            sched.next_run_at = utcnow()
        with self._lock:
            self._schedules[sid] = sched
            self._handlers[sid] = handler
            self._handler_names[sid] = name
            self._save(sched)
        publish("scheduler.registered", data={"schedule_id": sid, "name": name},
                source="scheduler")
        return sid

    def register_handler_for(self, schedule_id: str, handler: Callable):
        with self._lock:
            self._handlers[schedule_id] = handler
            sched = self._schedules.get(schedule_id)
            if sched:
                self._handler_names[schedule_id] = sched.name

    def _compute_next_cron(self, sid: str) -> str:
        fields = self._cron_fields.get(sid)
        if not fields:
            return ""
        after = datetime.now(timezone.utc)
        for s in self._schedules.values():
            if s.schedule_id == sid and s.last_run_at:
                try:
                    after = datetime.fromisoformat(s.last_run_at)
                except ValueError:
                    pass
        nxt = next_cron_match(fields, after)
        return nxt.isoformat() if nxt else ""

    def start(self):
        self._running = True
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        logger.info("Scheduler started")

    def stop(self, timeout_s: float = 5.0):
        self._running = False
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=timeout_s)
        logger.info("Scheduler stopped")

    def pause(self, schedule_id: str) -> bool:
        with self._lock:
            s = self._schedules.get(schedule_id)
            if not s or s.state != ScheduleState.ACTIVE:
                return False
            s.state = ScheduleState.PAUSED
            self._save(s)
        publish("scheduler.paused", data={"schedule_id": schedule_id}, source="scheduler")
        return True

    def resume(self, schedule_id: str) -> bool:
        with self._lock:
            s = self._schedules.get(schedule_id)
            if not s or s.state != ScheduleState.PAUSED:
                return False
            s.state = ScheduleState.ACTIVE
            s.next_run_at = self._compute_next_cron(schedule_id) if s.cron else utcnow()
            self._save(s)
        publish("scheduler.resumed", data={"schedule_id": schedule_id}, source="scheduler")
        return True

    def disable(self, schedule_id: str) -> bool:
        with self._lock:
            s = self._schedules.get(schedule_id)
            if not s:
                return False
            s.state = ScheduleState.DISABLED
            self._save(s)
        return True

    def get(self, schedule_id: str) -> Optional[Schedule]:
        with self._lock:
            s = self._schedules.get(schedule_id)
            if s:
                return Schedule(**s.__dict__)
            return None

    def list_all(self) -> list[Schedule]:
        with self._lock:
            return [Schedule(**s.__dict__) for s in self._schedules.values()]

    def list_by_state(self, state: ScheduleState) -> list[Schedule]:
        return [s for s in self.list_all() if s.state == state]

    def _loop(self):
        while self._running:
            now = datetime.now(timezone.utc)
            to_run: list[tuple[str, Schedule]] = []
            with self._lock:
                for sid, sched in list(self._schedules.items()):
                    if sched.state != ScheduleState.ACTIVE:
                        continue
                    if sched.next_run_at and now >= datetime.fromisoformat(sched.next_run_at):
                        if self._dependencies_met(sched):
                            to_run.append((sid, sched))
            for sid, sched in to_run:
                self._execute(sid)
            time.sleep(10)

    def _dependencies_met(self, sched: Schedule) -> bool:
        for dep_id in sched.dependencies:
            dep = self._schedules.get(dep_id)
            if dep and dep.state != ScheduleState.COMPLETED:
                return False
        return True

    def _execute(self, schedule_id: str):
        handler = self._handlers.get(schedule_id)
        sched = self._schedules.get(schedule_id)
        if not handler or not sched:
            return

        def _run_handler():
            exc_info = [None]

            def _target():
                try:
                    handler()
                except Exception as e:
                    exc_info[0] = e

            if sched.timeout_s > 0:
                t = threading.Thread(target=_target, daemon=True)
                t.start()
                t.join(timeout=sched.timeout_s)
                if t.is_alive():
                    exc_info[0] = TimeoutError(f"Schedule '{sched.name}' timed out")
            else:
                _target()

            if exc_info[0]:
                raise exc_info[0]

        def _run():
            try:
                _run_handler()
                with self._lock:
                    sched.last_run_at = utcnow()
                    sched.total_runs += 1
                    sched.next_run_at = self._compute_next_cron(schedule_id) if sched.cron else (
                        (datetime.now(timezone.utc) + timedelta(seconds=sched.interval_s)).isoformat()
                    )
                    self._save(sched)
                publish("scheduler.executed", data={"schedule_id": schedule_id, "name": sched.name},
                        source="scheduler")
            except Exception as e:
                logger.error("Schedule '%s' failed: %s", sched.name, e)
                with self._lock:
                    sched.failed_runs += 1
                    self._save(sched)
                publish("scheduler.failed", data={"schedule_id": schedule_id, "error": str(e)},
                        source="scheduler")

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def detect_missed(self) -> list[dict]:
        missed = []
        now = datetime.now(timezone.utc)
        with self._lock:
            for sid, sched in list(self._schedules.items()):
                if sched.state != ScheduleState.ACTIVE or not sched.next_run_at:
                    continue
                try:
                    next_time = datetime.fromisoformat(sched.next_run_at)
                    if now > next_time + timedelta(minutes=5):
                        missed.append({
                            "schedule_id": sid,
                            "name": sched.name,
                            "scheduled_at": sched.next_run_at,
                            "catch_up": sched.catch_up,
                        })
                except ValueError:
                    continue
        return missed

    def catch_up(self, schedule_id: str) -> bool:
        sched = self._schedules.get(schedule_id)
        if not sched or not sched.catch_up:
            return False
        self._execute(schedule_id)
        return True

    def _path_for(self, sched: Schedule) -> Path:
        return self._persist_dir / f"{sched.schedule_id}.json"

    def _save(self, sched: Schedule):
        self._path_for(sched).write_text(
            json.dumps({
                "schedule_id": sched.schedule_id,
                "name": sched.name,
                "cron": sched.cron,
                "interval_s": sched.interval_s,
                "state": sched.state.value,
                "last_run_at": sched.last_run_at,
                "next_run_at": sched.next_run_at,
                "created_at": sched.created_at,
                "total_runs": sched.total_runs,
                "failed_runs": sched.failed_runs,
                "timeout_s": sched.timeout_s,
                "catch_up": sched.catch_up,
                "dependencies": sched.dependencies,
                "metadata": sched.metadata,
            }, indent=2),
            encoding="utf-8",
        )

    def recover(self) -> int:
        count = 0
        missing_handlers = []
        for f in sorted(self._persist_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                sched = Schedule(
                    schedule_id=d["schedule_id"],
                    name=d.get("name", ""),
                    cron=d.get("cron", ""),
                    interval_s=d.get("interval_s", 0),
                    state=ScheduleState(d.get("state", "active")),
                    last_run_at=d.get("last_run_at", ""),
                    next_run_at=d.get("next_run_at", ""),
                    created_at=d.get("created_at", ""),
                    total_runs=d.get("total_runs", 0),
                    failed_runs=d.get("failed_runs", 0),
                    timeout_s=d.get("timeout_s", 300),
                    catch_up=d.get("catch_up", True),
                    dependencies=d.get("dependencies", []),
                    metadata=d.get("metadata", {}),
                )
                if sched.state not in (ScheduleState.DISABLED, ScheduleState.COMPLETED):
                    self._schedules[sched.schedule_id] = sched
                    if sched.cron:
                        self._cron_fields[sched.schedule_id] = parse_cron(sched.cron)
                    if sched.schedule_id not in self._handlers:
                        missing_handlers.append(sched.name)
                        sched.state = ScheduleState.PAUSED
                    count += 1
            except Exception as e:
                logger.warning("Failed to recover schedule %s: %s", f.name, e)
        if missing_handlers:
            logger.warning("Recovered schedules with missing handlers (paused): %s", missing_handlers)
        return count
