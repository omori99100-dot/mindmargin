import time
from datetime import datetime
from typing import Optional


class Timer:
    """Execution timer per agent / per pipeline."""

    def __init__(self):
        self._start: Optional[float] = None
        self._laps: list[dict] = []
        self._current_label: Optional[str] = None

    def start(self, label: str = ""):
        now = time.time()
        self._start = now
        self._current_label = label
        self._laps.append({
            "label": label or "start",
            "timestamp": datetime.utcnow().isoformat(),
            "elapsed_s": 0.0,
        })

    def lap(self, label: str) -> dict:
        now = time.time()
        elapsed = now - self._start if self._start else 0.0
        entry = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat(),
            "elapsed_s": round(elapsed, 2),
        }
        self._laps.append(entry)
        self._current_label = label
        return entry

    def stop(self, label: str = "done") -> dict:
        entry = self.lap(label)
        self._start = None
        return entry

    @property
    def total_s(self) -> float:
        if len(self._laps) < 2:
            return 0.0
        return self._laps[-1]["elapsed_s"]

    def summary(self) -> str:
        if len(self._laps) < 2:
            return "no timing data"
        parts = []
        for i, lap in enumerate(self._laps):
            if i == 0:
                continue
            prev = self._laps[i - 1]
            delta = round(lap["elapsed_s"] - prev["elapsed_s"], 2)
            parts.append(f"{lap['label']}: {delta}s")
        return " | ".join(parts)
