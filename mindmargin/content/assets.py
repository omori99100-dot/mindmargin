import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.content.models import (
    ContentAsset, AssetType, utcnow,
)

logger = logging.getLogger(__name__)


class AssetManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._assets_dir = root / "content" / "assets"
        self._assets_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, asset_id: str) -> Path:
        safe = asset_id.replace("/", "_").replace("\\", "_")
        for p in self._assets_dir.rglob(f"{safe}.json"):
            return p
        return self._assets_dir / f"{safe}.json"

    def _content_dir(self, content_id: str) -> Path:
        safe = content_id.replace("/", "_").replace("\\", "_")
        d = self._assets_dir / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create_asset(self, content_id: str, asset_type: AssetType,
                     path: str = "", data: dict = None,
                     metadata: dict = None) -> ContentAsset:
        asset_id = f"ast_{uuid.uuid4().hex[:12]}"
        checksum = ""
        if path:
            try:
                checksum = hashlib.md5(Path(path).read_bytes()).hexdigest()
            except Exception:
                pass
        asset = ContentAsset(
            asset_id=asset_id,
            content_id=content_id,
            asset_type=asset_type,
            path=path,
            data=data or {},
            checksum=checksum,
            created_at=utcnow(),
            updated_at=utcnow(),
            metadata=metadata or {},
        )
        self._save(asset)
        logger.info("AssetManager: created %s for content %s", asset_type.value, content_id)
        return asset

    def get_asset(self, asset_id: str) -> Optional[ContentAsset]:
        path = self._path_for(asset_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ContentAsset.from_dict(data)
        except Exception:
            return None

    def update_asset(self, asset: ContentAsset) -> ContentAsset:
        asset.updated_at = utcnow()
        if asset.path:
            try:
                import hashlib
                asset.checksum = hashlib.md5(Path(asset.path).read_bytes()).hexdigest()
            except Exception:
                pass
        self._save(asset)
        return asset

    def delete_asset(self, asset_id: str) -> bool:
        path = self._path_for(asset_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_assets(self, content_id: str,
                    asset_type: Optional[AssetType] = None) -> list[ContentAsset]:
        content_dir = self._content_dir(content_id)
        assets = []
        for p in content_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                asset = ContentAsset.from_dict(data)
                if asset.content_id != content_id:
                    continue
                if asset_type and asset.asset_type != asset_type:
                    continue
                assets.append(asset)
            except Exception:
                continue
        return assets

    def list_all_assets(self, asset_type: Optional[AssetType] = None,
                        limit: int = 500) -> list[ContentAsset]:
        assets = []
        for p in self._assets_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                asset = ContentAsset.from_dict(data)
                if asset_type and asset.asset_type != asset_type:
                    continue
                assets.append(asset)
                if len(assets) >= limit:
                    break
            except Exception:
                continue
        return assets

    def get_asset_stats(self) -> dict:
        stats = {"total": 0, "by_type": {}, "by_content": {}}
        for p in self._assets_dir.rglob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if "asset_type" not in data:
                    continue
                stats["total"] += 1
                atype = data.get("asset_type", "unknown")
                stats["by_type"][atype] = stats["by_type"].get(atype, 0) + 1
                cid = data.get("content_id", "")
                stats["by_content"][cid] = stats["by_content"].get(cid, 0) + 1
            except Exception:
                continue
        return stats

    def find_by_checksum(self, checksum: str) -> list[ContentAsset]:
        results = []
        for p in self._assets_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("checksum") == checksum:
                    results.append(ContentAsset.from_dict(data))
            except Exception:
                continue
        return results

    def get_latest_version(self, content_id: str, asset_type: AssetType) -> Optional[ContentAsset]:
        assets = self.list_assets(content_id, asset_type)
        if not assets:
            return None
        return max(assets, key=lambda a: a.version)

    def _save(self, asset: ContentAsset):
        content_dir = self._content_dir(asset.content_id)
        path = content_dir / f"{asset.asset_id}.json"
        path.write_text(json.dumps(asset.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


import hashlib
