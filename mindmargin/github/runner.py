import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RunnerInfo:
    runner_id: int = 0
    name: str = ""
    status: str = "online"
    os: str = ""
    labels: list[str] = field(default_factory=list)
    busy: bool = False
    current_job: str = ""
    last_heartbeat: str = ""
    total_runs: int = 0
    failed_runs: int = 0

    def to_dict(self) -> dict:
        return {
            "runner_id": self.runner_id,
            "name": self.name,
            "status": self.status,
            "os": self.os,
            "labels": self.labels,
            "busy": self.busy,
            "current_job": self.current_job,
            "last_heartbeat": self.last_heartbeat,
            "total_runs": self.total_runs,
            "failed_runs": self.failed_runs,
        }


@dataclass
class RunnerPool:
    total_runners: int = 0
    available_runners: int = 0
    busy_runners: int = 0
    offline_runners: int = 0
    avg_queue_time_s: float = 0.0
    avg_job_duration_s: float = 0.0
    runners: list[RunnerInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_runners": self.total_runners,
            "available_runners": self.available_runners,
            "busy_runners": self.busy_runners,
            "offline_runners": self.offline_runners,
            "avg_queue_time_s": round(self.avg_queue_time_s, 2),
            "avg_job_duration_s": round(self.avg_job_duration_s, 2),
            "runners": [r.to_dict() for r in self.runners],
        }


class RunnerManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._run_dir = root / "github" / "runners"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._runners: dict[int, RunnerInfo] = {}
        self._lock = threading.RLock()
        self._queue_times: list[float] = []
        self._job_durations: list[float] = []
        self._load()

    def _load(self):
        state_path = self._run_dir / "runners.json"
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                for rd in data:
                    runner = RunnerInfo(**rd)
                    self._runners[runner.runner_id] = runner
            except Exception:
                pass

    def _save(self):
        state_path = self._run_dir / "runners.json"
        state_path.write_text(
            json.dumps([r.to_dict() for r in self._runners.values()], indent=2),
            encoding="utf-8",
        )

    def update_runner(self, runner_id: int, name: str = "", status: str = "",
                      busy: bool = False, os: str = "", labels: list[str] = None):
        with self._lock:
            if runner_id not in self._runners:
                self._runners[runner_id] = RunnerInfo(runner_id=runner_id)
            runner = self._runners[runner_id]
            if name:
                runner.name = name
            if status:
                runner.status = status
            runner.busy = busy
            if os:
                runner.os = os
            if labels is not None:
                runner.labels = labels
            runner.last_heartbeat = datetime.now(timezone.utc).isoformat()
            self._save()

    def record_job_start(self, runner_id: int, job_name: str):
        with self._lock:
            if runner_id in self._runners:
                runner = self._runners[runner_id]
                runner.busy = True
                runner.current_job = job_name
                runner.total_runs += 1
                self._save()

    def record_job_complete(self, runner_id: int, success: bool):
        with self._lock:
            if runner_id in self._runners:
                runner = self._runners[runner_id]
                runner.busy = False
                runner.current_job = ""
                if not success:
                    runner.failed_runs += 1
                self._save()

    def record_queue_time(self, queue_s: float):
        with self._lock:
            self._queue_times.append(queue_s)
            if len(self._queue_times) > 1000:
                self._queue_times = self._queue_times[-500:]

    def record_job_duration(self, duration_s: float):
        with self._lock:
            self._job_durations.append(duration_s)
            if len(self._job_durations) > 1000:
                self._job_durations = self._job_durations[-500:]

    def get_pool_status(self) -> RunnerPool:
        with self._lock:
            runners = list(self._runners.values())
            total = len(runners)
            available = sum(1 for r in runners if r.status == "online" and not r.busy)
            busy = sum(1 for r in runners if r.busy)
            offline = sum(1 for r in runners if r.status != "online")

            avg_queue = (sum(self._queue_times) / len(self._queue_times)) if self._queue_times else 0
            avg_duration = (sum(self._job_durations) / len(self._job_durations)) if self._job_durations else 0

        return RunnerPool(
            total_runners=total,
            available_runners=available,
            busy_runners=busy,
            offline_runners=offline,
            avg_queue_time_s=avg_queue,
            avg_job_duration_s=avg_duration,
            runners=runners,
        )

    def get_runner(self, runner_id: int) -> Optional[RunnerInfo]:
        with self._lock:
            return self._runners.get(runner_id)

    def list_runners(self, status: str = "") -> list[RunnerInfo]:
        with self._lock:
            runners = list(self._runners.values())
        if status:
            runners = [r for r in runners if r.status == status]
        return runners

    def get_availability_score(self) -> float:
        pool = self.get_pool_status()
        if pool.total_runners == 0:
            return 0.0
        return pool.available_runners / pool.total_runners

    def get_stats(self) -> dict:
        pool = self.get_pool_status()
        return {
            "pool": pool.to_dict(),
            "availability_score": round(self.get_availability_score(), 2),
            "avg_queue_time_s": pool.avg_queue_time_s,
            "avg_job_duration_s": pool.avg_job_duration_s,
        }