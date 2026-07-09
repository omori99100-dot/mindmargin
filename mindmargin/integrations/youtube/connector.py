import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

QUOTA_DAILY_LIMIT = 10000
QUOTA_UPLOAD_LIMIT = 50
QUOTA_COST_PER_UPLOAD = 1600


@dataclass
class UploadRecord:
    video_id: str = ""
    title: str = ""
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    file_path: str = ""
    file_size: int = 0
    thumbnail_path: str = ""
    privacy: str = "private"
    playlist_id: str = ""
    duration_s: float = 0.0
    quota_cost: int = QUOTA_COST_PER_UPLOAD

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "thumbnail_path": self.thumbnail_path,
            "privacy": self.privacy,
            "playlist_id": self.playlist_id,
            "duration_s": round(self.duration_s, 2),
            "quota_cost": self.quota_cost,
        }


@dataclass
class QuotaUsage:
    date: str = ""
    used: int = 0
    limit: int = QUOTA_DAILY_LIMIT
    uploads: int = 0
    upload_limit: int = QUOTA_UPLOAD_LIMIT
    cost_per_upload: int = QUOTA_COST_PER_UPLOAD

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def upload_remaining(self) -> int:
        return max(0, self.upload_limit - self.uploads)

    @property
    def pct_used(self) -> float:
        return (self.used / self.limit * 100) if self.limit > 0 else 0

    def can_upload(self) -> bool:
        return self.remaining >= self.cost_per_upload and self.uploads < self.upload_limit

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "uploads": self.uploads,
            "upload_limit": self.upload_limit,
            "upload_remaining": self.upload_remaining,
            "pct_used": round(self.pct_used, 1),
            "can_upload": self.can_upload(),
        }


class YouTubeConnector:
    def __init__(self, persist_dir: str = ""):
        from mindmargin.config import settings as _settings
        root = Path(persist_dir or _settings.storage.temp_root)
        self._yt_dir = root / "integrations" / "youtube"
        self._yt_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = self._yt_dir / "upload_history.json"
        self._quota_path = self._yt_dir / "quota.json"
        self._records: list[UploadRecord] = self._load_history()
        self._quota: QuotaUsage = self._load_quota()

    def _load_history(self) -> list[UploadRecord]:
        if self._history_path.exists():
            try:
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                return [UploadRecord(**r) for r in data]
            except Exception as e:
                logger.warning("Failed to load upload history: %s", e)
        return []

    def _save_history(self):
        records = [r.to_dict() for r in self._records[-500:]]
        self._history_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    def _load_quota(self) -> QuotaUsage:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._quota_path.exists():
            try:
                data = json.loads(self._quota_path.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    return QuotaUsage(**data)
            except Exception as e:
                logger.warning("Failed to load quota: %s", e)
        return QuotaUsage(date=today)

    def _save_quota(self):
        self._quota_path.write_text(json.dumps(self._quota.to_dict(), indent=2), encoding="utf-8")

    def get_quota(self) -> QuotaUsage:
        return self._quota

    def get_status(self) -> dict:
        return {
            "quota": self._quota.to_dict(),
            "total_uploads": len(self._records),
            "recent_uploads": [r.to_dict() for r in self._records[-10:]],
            "authenticated": self._check_auth(),
        }

    def _check_auth(self) -> bool:
        try:
            from mindmargin.integrations.secrets.manager import SecretManager
            sm = SecretManager()
            return sm.is_configured("YOUTUBE_CLIENT_ID") and sm.is_configured("YOUTUBE_REFRESH_TOKEN")
        except Exception:
            return False

    def upload_video(self, file_path: str, title: str, description: str = "",
                     tags: list[str] = None, category_id: str = "27",
                     privacy: str = "private", playlist_id: str = "",
                     thumbnail_path: str = "") -> dict:
        if not self._quota.can_upload():
            return {"status": "failed", "error": "Quota exhausted"}

        record = UploadRecord(
            title=title,
            status="uploading",
            started_at=datetime.now(timezone.utc).isoformat(),
            file_path=file_path,
            file_size=Path(file_path).stat().st_size if Path(file_path).exists() else 0,
            thumbnail_path=thumbnail_path,
            privacy=privacy,
            playlist_id=playlist_id,
        )

        start = time.monotonic()
        try:
            result = self._do_upload(file_path, title, description, tags or [],
                                     category_id, privacy, playlist_id, thumbnail_path)
            record.video_id = result.get("video_id", "")
            record.status = "completed"
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.duration_s = time.monotonic() - start
            self._quota.used += QUOTA_COST_PER_UPLOAD
            self._quota.uploads += 1
            self._save_quota()
        except Exception as e:
            record.status = "failed"
            record.error = str(e)
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.duration_s = time.monotonic() - start
            logger.error("Upload failed: %s", e)

        self._records.append(record)
        self._save_history()
        return record.to_dict()

    def _do_upload(self, file_path: str, title: str, description: str,
                   tags: list[str], category_id: str, privacy: str,
                   playlist_id: str, thumbnail_path: str) -> dict:
        from mindmargin.integrations.youtube.client import YouTubeClient
        client = YouTubeClient()
        result = client.upload(
            file_path=file_path, title=title, description=description,
            tags=tags, category_id=category_id, privacy=privacy,
        )
        if result.get("video_id") and playlist_id:
            client.add_to_playlist(result["video_id"], playlist_id)
        if result.get("video_id") and thumbnail_path:
            client.set_thumbnail(result["video_id"], thumbnail_path)
        return result

    def update_metadata(self, video_id: str, title: str = "", description: str = "",
                        tags: list[str] = None) -> dict:
        try:
            from mindmargin.integrations.youtube.client import YouTubeClient
            client = YouTubeClient()
            return client.update_metadata(video_id, title, description, tags or [])
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def list_playlists(self) -> list[dict]:
        try:
            from mindmargin.integrations.youtube.client import YouTubeClient
            client = YouTubeClient()
            return client.list_playlists()
        except Exception as e:
            logger.warning("Failed to list playlists: %s", e)
            return []

    def get_video_stats(self, video_id: str) -> dict:
        try:
            from mindmargin.integrations.youtube.client import YouTubeClient
            client = YouTubeClient()
            return client.get_video_stats(video_id)
        except Exception as e:
            return {"error": str(e)}

    def post_comment(self, video_id: str, text: str) -> dict:
        try:
            from mindmargin.integrations.youtube.client import YouTubeClient
            client = YouTubeClient()
            return client.post_comment(video_id, text)
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def get_upload_history(self, limit: int = 50) -> list[dict]:
        return [r.to_dict() for r in self._records[-limit:]]

    def get_history(self, limit: int = 50) -> list[dict]:
        return self.get_upload_history(limit)
