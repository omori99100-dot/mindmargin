import json
import logging
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


class ArtifactType(str, Enum):
    SCRIPT = "script"
    VOICE = "voice"
    VIDEO = "video"
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"
    ANALYTICS = "analytics"
    LOGS = "logs"
    DECISION = "decision"
    EXPERIMENT = "experiment"
    WEEKLY_PLAN = "weekly_plan"
    REPORT = "report"
    CONFIG = "config"
    OTHER = "other"


@dataclass
class Artifact:
    artifact_id: str = ""
    name: str = ""
    artifact_type: ArtifactType = ArtifactType.OTHER
    file_path: str = ""
    size_bytes: int = 0
    checksum: str = ""
    version: int = 1
    parent_id: str = ""
    workflow_run_id: str = ""
    created_at: str = ""
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "artifact_type": self.artifact_type.value,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "version": self.version,
            "parent_id": self.parent_id,
            "workflow_run_id": self.workflow_run_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Artifact":
        d = dict(d)
        d["artifact_type"] = ArtifactType(d.get("artifact_type", "other"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ArtifactStore:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._base_dir = root / "github" / "artifacts"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._base_dir / "index.json"
        self._artifacts: dict[str, Artifact] = {}
        self._lock = threading.RLock()
        self._load_index()

    def _load_index(self):
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                for ad in data:
                    art = Artifact.from_dict(ad)
                    self._artifacts[art.artifact_id] = art
            except Exception as e:
                logger.warning("Failed to load artifact index: %s", e)

    def _save_index(self):
        data = [a.to_dict() for a in self._artifacts.values()]
        self._index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _compute_checksum(self, file_path: str) -> str:
        import hashlib
        h = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()[:16]
        except Exception:
            return ""

    def store(self, name: str, artifact_type: ArtifactType, source_path: str,
              workflow_run_id: str = "", tags: list[str] = None,
              metadata: dict = None) -> Artifact:
        aid = f"art_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        type_dir = self._base_dir / artifact_type.value
        type_dir.mkdir(parents=True, exist_ok=True)
        dest = type_dir / f"{aid}_{Path(source_path).name}"
        try:
            shutil.copy2(source_path, str(dest))
        except Exception as e:
            logger.error("Failed to copy artifact: %s", e)
            raise

        size = dest.stat().st_size
        checksum = self._compute_checksum(str(dest))

        artifact = Artifact(
            artifact_id=aid,
            name=name,
            artifact_type=artifact_type,
            file_path=str(dest),
            size_bytes=size,
            checksum=checksum,
            version=1,
            workflow_run_id=workflow_run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
            tags=tags or [],
        )

        with self._lock:
            self._artifacts[aid] = artifact
            self._save_index()

        logger.info("Artifact stored: %s (%s, %d bytes)", name, artifact_type.value, size)
        return artifact

    def store_version(self, parent_id: str, source_path: str) -> Optional[Artifact]:
        parent = self._artifacts.get(parent_id)
        if not parent:
            return None
        type_dir = self._base_dir / parent.artifact_type.value
        version = parent.version + 1
        aid = f"art_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        dest = type_dir / f"{aid}_v{version}_{Path(source_path).name}"
        try:
            shutil.copy2(source_path, str(dest))
        except Exception as e:
            logger.error("Failed to copy artifact version: %s", e)
            raise

        artifact = Artifact(
            artifact_id=aid,
            name=parent.name,
            artifact_type=parent.artifact_type,
            file_path=str(dest),
            size_bytes=dest.stat().st_size,
            checksum=self._compute_checksum(str(dest)),
            version=version,
            parent_id=parent_id,
            workflow_run_id=parent.workflow_run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=parent.metadata.copy(),
            tags=parent.tags.copy(),
        )

        with self._lock:
            self._artifacts[aid] = artifact
            self._save_index()

        return artifact

    def get(self, artifact_id: str) -> Optional[Artifact]:
        with self._lock:
            return self._artifacts.get(artifact_id)

    def list_artifacts(self, artifact_type: str = "", workflow_run_id: str = "",
                       tag: str = "", limit: int = 100) -> list[Artifact]:
        with self._lock:
            arts = list(self._artifacts.values())
        if artifact_type:
            arts = [a for a in arts if a.artifact_type.value == artifact_type]
        if workflow_run_id:
            arts = [a for a in arts if a.workflow_run_id == workflow_run_id]
        if tag:
            arts = [a for a in arts if tag in a.tags]
        arts.sort(key=lambda a: a.created_at, reverse=True)
        return arts[:limit]

    def list_versions(self, parent_id: str) -> list[Artifact]:
        with self._lock:
            versions = [a for a in self._artifacts.values() if a.parent_id == parent_id]
        parent = self._artifacts.get(parent_id)
        if parent:
            versions.append(parent)
        versions.sort(key=lambda a: a.version)
        return versions

    def delete(self, artifact_id: str) -> bool:
        with self._lock:
            art = self._artifacts.get(artifact_id)
            if not art:
                return False
            try:
                p = Path(art.file_path)
                if p.exists():
                    p.unlink()
            except Exception as e:
                logger.warning("Failed to delete artifact file: %s", e)
            del self._artifacts[artifact_id]
            self._save_index()
            return True

    def get_total_size(self) -> int:
        with self._lock:
            return sum(a.size_bytes for a in self._artifacts.values())

    def get_stats(self) -> dict:
        with self._lock:
            by_type = {}
            for a in self._artifacts.values():
                t = a.artifact_type.value
                by_type[t] = by_type.get(t, 0) + 1
            return {
                "total_artifacts": len(self._artifacts),
                "total_size_bytes": self.get_total_size(),
                "by_type": by_type,
            }

    def cleanup_old(self, max_age_days: int = 30) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        removed = 0
        with self._lock:
            to_remove = []
            for aid, art in self._artifacts.items():
                if art.created_at and art.created_at < cutoff:
                    to_remove.append(aid)
            for aid in to_remove:
                art = self._artifacts.pop(aid)
                try:
                    p = Path(art.file_path)
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
                removed += 1
            if removed:
                self._save_index()
        return removed
