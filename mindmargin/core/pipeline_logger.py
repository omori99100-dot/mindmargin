"""Structured JSON logging for pipeline events."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from mindmargin.core.storage import _safe_base

logger = logging.getLogger(__name__)


class PipelineLogger:
    """Append-only JSON log writer per pipeline.

    Writes to ``logs/pipeline/{pipeline_id}.jsonl`` — one JSON object per line.
    """

    def __init__(self, pipeline_id: str):
        self.pipeline_id = pipeline_id
        self._base_dir = _safe_base() / "logs" / "pipeline"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._base_dir / f"{pipeline_id}.jsonl"

    def log(self, event: str, stage: str = "",
            status: str = "info", duration: Optional[float] = None,
            metadata: Optional[dict] = None):
        """Append a structured log entry."""
        entry: dict[str, object] = {
            "timestamp": datetime.utcnow().isoformat(),
            "pipeline_id": self.pipeline_id,
            "event": event,
            "stage": stage,
            "status": status,
        }
        if duration is not None:
            entry["duration"] = round(duration, 3)
        if metadata:
            entry.update(metadata)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def clip_rendered(self, clip_name: str, duration: float,
                      encoder: str = "", retry: int = 0):
        self.log("clip_rendered", stage="editing", status="success",
                 duration=duration,
                 metadata={"clip": clip_name, "encoder": encoder, "retry": retry})

    def stage_started(self, stage: str):
        self.log("stage_started", stage=stage, status="started")

    def stage_completed(self, stage: str, duration: float):
        self.log("stage_completed", stage=stage, status="success",
                 duration=duration)

    def stage_failed(self, stage: str, error: str):
        self.log("stage_failed", stage=stage, status="failed",
                 metadata={"error": error})

    def cache_hit(self, key: str, resource: str):
        self.log("cache_hit", stage="cache", status="info",
                 metadata={"key": key, "resource": resource})

    def cache_miss(self, key: str, resource: str):
        self.log("cache_miss", stage="cache", status="info",
                 metadata={"key": key, "resource": resource})

    def publish_attempt(self, status: str, video_id: str = "",
                        error: str = ""):
        meta = {"video_id": video_id}
        if error:
            meta["error"] = error
        self.log("publish_attempt", stage="publishing", status=status,
                 metadata=meta)

    def read_entries(self, limit: int = 100) -> list[dict]:
        """Read recent log entries (newest first)."""
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        entries = []
        for line in reversed(lines[-limit:]):
            try:
                entries.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                pass
        return entries
