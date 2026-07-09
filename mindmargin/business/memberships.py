import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import utcnow

logger = logging.getLogger(__name__)


class MembershipManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "business" / "memberships"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, mid: str) -> Path:
        return self._dir / f"{mid}.json"

    def _save(self, data: dict):
        mid = data.get("membership_id", "")
        path = self._path_for(mid)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_tier(self, name: str, price_monthly: float,
                    benefits: list[str] = None,
                    max_members: int = 0) -> dict:
        tier = {
            "membership_id": f"mem_{uuid.uuid4().hex[:10]}",
            "name": name,
            "price_monthly": price_monthly,
            "benefits": benefits or [],
            "max_members": max_members,
            "current_members": 0,
            "total_revenue": 0.0,
            "status": "active",
            "metadata": {},
            "created_at": utcnow(),
        }
        self._save(tier)
        return tier

    def get_tier(self, mid: str) -> Optional[dict]:
        path = self._path_for(mid)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_tiers(self, status: Optional[str] = None) -> list[dict]:
        results = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                results.append(data)
            except Exception:
                continue
        return results

    def record_member_join(self, mid: str) -> bool:
        tier = self.get_tier(mid)
        if not tier:
            return False
        tier["current_members"] = tier.get("current_members", 0) + 1
        tier["total_revenue"] = tier.get("total_revenue", 0) + tier.get("price_monthly", 0)
        self._save(tier)
        return True

    def record_member_leave(self, mid: str) -> bool:
        tier = self.get_tier(mid)
        if not tier:
            return False
        tier["current_members"] = max(tier.get("current_members", 0) - 1, 0)
        self._save(tier)
        return True

    def get_total_members(self) -> int:
        tiers = self.list_tiers()
        return sum(t.get("current_members", 0) for t in tiers)

    def get_mrr(self) -> float:
        tiers = self.list_tiers(status="active")
        return round(sum(t.get("current_members", 0) * t.get("price_monthly", 0) for t in tiers), 2)

    def get_total_revenue(self) -> float:
        tiers = self.list_tiers()
        return round(sum(t.get("total_revenue", 0) for t in tiers), 2)

    def get_churn_rate(self) -> float:
        return 0.05
