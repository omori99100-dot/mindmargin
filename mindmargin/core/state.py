"""Pipeline state machine with persistent JSON files."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.core.storage import _safe_base

logger = logging.getLogger(__name__)

# ── State constants ──

CREATED = "CREATED"
RESEARCHING = "RESEARCHING"
SCRIPTING = "SCRIPTING"
VOICE_GENERATION = "VOICE_GENERATION"
THUMBNAIL_GENERATION = "THUMBNAIL_GENERATION"
EDITING = "EDITING"
MERGING = "MERGING"
METADATA = "METADATA"
PUBLISHING = "PUBLISHING"
PUBLISHED = "PUBLISHED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

_ALL_STATES = [
    CREATED, RESEARCHING, SCRIPTING, VOICE_GENERATION,
    THUMBNAIL_GENERATION, EDITING, MERGING, METADATA,
    PUBLISHING, PUBLISHED, COMPLETED, FAILED, CANCELLED,
]

TERMINAL_STATES = {COMPLETED, FAILED, CANCELLED, PUBLISHED}


class PipelineState:
    """Persistent pipeline state machine.

    Stores state in ``pipeline_state/{pipeline_id}.json`` under the output root.
    """

    def __init__(self, pipeline_id: str, topic: str = ""):
        self.pipeline_id = pipeline_id
        self.topic = topic
        self._base_dir = _safe_base() / "pipeline_state"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._base_dir / f"{pipeline_id}.json"
        self._data = self._load()

    # ── Public API ──

    @property
    def state(self) -> str:
        return self._data.get("state", CREATED)

    @state.setter
    def state(self, new_state: str):
        if new_state not in _ALL_STATES:
            raise ValueError(f"Invalid pipeline state: {new_state}")
        self._data["state"] = new_state
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        logger.debug(f"Pipeline {self.pipeline_id}: {new_state}")

    def set_metadata(self, key: str, value: object):
        self._data.setdefault("metadata", {})[key] = value
        self._save()

    def get_metadata(self, key: str, default: object = None) -> object:
        return self._data.get("metadata", {}).get(key, default)

    @property
    def started_at(self) -> Optional[str]:
        return self._data.get("started_at")

    @property
    def updated_at(self) -> Optional[str]:
        return self._data.get("updated_at")

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_cancelled(self) -> bool:
        return self.state == CANCELLED

    @property
    def current_clip(self) -> str:
        return self._data.get("current_clip", "")

    @current_clip.setter
    def current_clip(self, clip_name: str):
        self._data["current_clip"] = clip_name
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def mark_started(self):
        now = datetime.utcnow().isoformat()
        self._data["started_at"] = now
        self._data["updated_at"] = now
        self._data["state"] = CREATED
        self._data["topic"] = self.topic
        self._save()

    def mark_failed(self, error: str = ""):
        self.state = FAILED
        if error:
            self.set_metadata("error", error)

    def mark_cancelled(self, reason: str = ""):
        self.state = CANCELLED
        if reason:
            self.set_metadata("cancel_reason", reason)

    @classmethod
    def list_unfinished(cls) -> list["PipelineState"]:
        """List all pipelines that are not in a terminal state."""
        base_dir = _safe_base() / "pipeline_state"
        if not base_dir.exists():
            return []
        unfinished = []
        for p in sorted(base_dir.glob("*.json")):
            state = cls(p.stem)
            if not state.is_terminal:
                unfinished.append(state)
        return unfinished

    @classmethod
    def all_pipelines(cls) -> list[dict]:
        """Return all known pipeline states as dicts."""
        base_dir = _safe_base() / "pipeline_state"
        if not base_dir.exists():
            return []
        results = []
        for p in sorted(base_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append(data)
            except (json.JSONDecodeError, Exception):
                pass
        return results

    def to_dict(self) -> dict:
        return dict(self._data)

    # ── Internals ──

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Corrupt state file {self._path}: {e}")
        return {"pipeline_id": self.pipeline_id, "topic": self.topic,
                "state": CREATED, "started_at": "", "updated_at": "",
                "metadata": {}}

    def _save(self):
        self._path.write_text(
            json.dumps(self._data, indent=2, default=str), encoding="utf-8")
