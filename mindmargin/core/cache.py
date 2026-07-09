"""Content-addressable asset cache with SHA-256 fingerprinting."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from mindmargin.core.storage import _safe_base

logger = logging.getLogger(__name__)


def hash_file(path: str | Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_text(text: str) -> str:
    """Return SHA-256 hex digest of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_dict(data: dict) -> str:
    """Return SHA-256 hex digest of a JSON-ordered dict."""
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


CACHE_VERSION = "1"


class AssetCache:
    """Content-based asset cache per pipeline.

    Stores checksums in ``asset_cache/{pipeline_id}.json``.
    """

    def __init__(self, pipeline_id: str):
        self.pipeline_id = pipeline_id
        self._base_dir = _safe_base() / "asset_cache"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._base_dir / f"{pipeline_id}.json"
        self._fingerprints: dict[str, str] = self._load()
        self._hits = 0
        self._misses = 0

    # ── Public API ──

    def check(self, key: str, current_hash: str) -> bool:
        """Return True if the cached hash matches *current_hash* (cache hit)."""
        cached = self._fingerprints.get(key)
        if cached == current_hash:
            self._hits += 1
            return True
        self._misses += 1
        return False

    def update(self, key: str, current_hash: str):
        self._fingerprints[key] = current_hash
        self._save()

    def check_file(self, key: str, path: str | Path) -> bool:
        """Convenience: hash file and check cache in one call."""
        if not Path(path).exists():
            self._misses += 1
            return False
        return self.check(key, hash_file(path))

    def update_file(self, key: str, path: str | Path):
        if Path(path).exists():
            self.update(key, hash_file(path))

    def check_text(self, key: str, text: str) -> bool:
        return self.check(key, hash_text(text))

    def update_text(self, key: str, text: str):
        self.update(key, hash_text(text))

    def invalidate(self, key: str):
        self._fingerprints.pop(key, None)
        self._save()

    def invalidate_all(self):
        self._fingerprints.clear()
        self._save()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "ratio": round(self._hits / total, 3) if total else 0.0,
        }

    @property
    def fingerprints(self) -> dict[str, str]:
        return dict(self._fingerprints)

    # ── Internals ──

    def _load(self) -> dict[str, str]:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                version = data.get("_version", "")
                if version != CACHE_VERSION:
                    logger.info(f"Cache version mismatch ({version} != {CACHE_VERSION}), clearing")
                    return {}
                return {k: v for k, v in data.items() if not k.startswith("_")}
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Corrupt cache {self._path}: {e}")
        return {}

    def _save(self):
        data = dict(self._fingerprints)
        data["_version"] = CACHE_VERSION
        self._path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8")
