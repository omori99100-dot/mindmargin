import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StorageObject:
    key: str
    size: int = 0
    content_type: str = ""
    version: str = ""
    last_modified: str = ""
    checksum: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "size": self.size,
            "content_type": self.content_type,
            "version": self.version,
            "last_modified": self.last_modified,
            "checksum": self.checksum,
        }


class StorageConnector:
    def __init__(self):
        self._backend = self._select_backend()

    def _select_backend(self):
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        if sm.is_configured("S3_BUCKET"):
            return S3Storage()
        return LocalStorage()

    def upload(self, local_path: str, remote_key: str, content_type: str = "") -> StorageObject:
        return self._backend.upload(local_path, remote_key, content_type)

    def download(self, remote_key: str, local_path: str) -> bool:
        return self._backend.download(remote_key, local_path)

    def delete(self, remote_key: str) -> bool:
        return self._backend.delete(remote_key)

    def exists(self, remote_key: str) -> bool:
        return self._backend.exists(remote_key)

    def list_objects(self, prefix: str = "") -> list[StorageObject]:
        return self._backend.list_objects(prefix)

    def get_url(self, remote_key: str) -> str:
        return self._backend.get_url(remote_key)

    def get_info(self) -> dict:
        return self._backend.get_info()


class LocalStorage:
    def __init__(self):
        from mindmargin.config import settings
        self._root = Path(settings.storage.temp_root) / "storage" / "local"
        self._root.mkdir(parents=True, exist_ok=True)

    def upload(self, local_path: str, remote_key: str, content_type: str = "") -> StorageObject:
        src = Path(local_path)
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {local_path}")
        dest = self._root / remote_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(str(src), str(dest))
        return StorageObject(
            key=remote_key,
            size=dest.stat().st_size,
            content_type=content_type,
            last_modified=str(int(dest.stat().st_mtime)),
        )

    def download(self, remote_key: str, local_path: str) -> bool:
        src = self._root / remote_key
        if not src.exists():
            return False
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(str(src), str(dest))
        return True

    def delete(self, remote_key: str) -> bool:
        p = self._root / remote_key
        if p.exists():
            p.unlink()
            return True
        return False

    def exists(self, remote_key: str) -> bool:
        return (self._root / remote_key).exists()

    def list_objects(self, prefix: str = "") -> list[StorageObject]:
        objects = []
        base = self._root / prefix if prefix else self._root
        if base.exists():
            for f in base.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(self._root)
                    objects.append(StorageObject(
                        key=str(rel),
                        size=f.stat().st_size,
                        last_modified=str(int(f.stat().st_mtime)),
                    ))
        return objects

    def get_url(self, remote_key: str) -> str:
        return str(self._root / remote_key)

    def get_info(self) -> dict:
        objects = self.list_objects()
        total_size = sum(o.size for o in objects)
        return {
            "backend": "local",
            "root": str(self._root),
            "total_objects": len(objects),
            "total_size_bytes": total_size,
        }


class S3Storage:
    def __init__(self):
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        self._bucket = sm.get("S3_BUCKET") or ""
        self._endpoint = sm.get("S3_ENDPOINT")
        self._access_key = sm.get("S3_ACCESS_KEY") or ""
        self._secret_key = sm.get("S3_SECRET_KEY") or ""

    def _get_client(self):
        import boto3
        kwargs = {"aws_access_key_id": self._access_key, "aws_secret_access_key": self._secret_key}
        if self._endpoint:
            kwargs["endpoint_url"] = self._endpoint
        return boto3.client("s3", **kwargs)

    def upload(self, local_path: str, remote_key: str, content_type: str = "") -> StorageObject:
        client = self._get_client()
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        client.upload_file(local_path, self._bucket, remote_key, ExtraArgs=extra)
        head = client.head_object(Bucket=self._bucket, Key=remote_key)
        return StorageObject(
            key=remote_key,
            size=head.get("ContentLength", 0),
            content_type=content_type or head.get("ContentType", ""),
            last_modified=str(head.get("LastModified", "")),
        )

    def download(self, remote_key: str, local_path: str) -> bool:
        try:
            client = self._get_client()
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            client.download_file(self._bucket, remote_key, local_path)
            return True
        except Exception as e:
            logger.warning("S3 download failed: %s", e)
            return False

    def delete(self, remote_key: str) -> bool:
        try:
            client = self._get_client()
            client.delete_object(Bucket=self._bucket, Key=remote_key)
            return True
        except Exception:
            return False

    def exists(self, remote_key: str) -> bool:
        try:
            client = self._get_client()
            client.head_object(Bucket=self._bucket, Key=remote_key)
            return True
        except Exception:
            return False

    def list_objects(self, prefix: str = "") -> list[StorageObject]:
        try:
            client = self._get_client()
            resp = client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
            objects = []
            for obj in resp.get("Contents", []):
                objects.append(StorageObject(
                    key=obj["Key"],
                    size=obj.get("Size", 0),
                    last_modified=str(obj.get("LastModified", "")),
                ))
            return objects
        except Exception:
            return []

    def get_url(self, remote_key: str) -> str:
        return f"s3://{self._bucket}/{remote_key}"

    def get_info(self) -> dict:
        return {
            "backend": "s3",
            "bucket": self._bucket,
            "endpoint": self._endpoint or "aws-default",
        }
