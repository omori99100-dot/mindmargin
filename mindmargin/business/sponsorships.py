import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import utcnow

logger = logging.getLogger(__name__)


class SponsorshipManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "business" / "sponsorships"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, sid: str) -> Path:
        return self._dir / f"{sid}.json"

    def _save(self, data: dict):
        sid = data.get("sponsorship_id", "")
        path = self._path_for(sid)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_sponsorship(self, sponsor_name: str, deal_value: float,
                           deliverables: list[str] = None,
                           start_date: str = "", end_date: str = "",
                           content_count: int = 0) -> dict:
        sponsorship = {
            "sponsorship_id": f"spon_{uuid.uuid4().hex[:10]}",
            "sponsor_name": sponsor_name,
            "deal_value": deal_value,
            "deliverables": deliverables or [],
            "start_date": start_date or utcnow()[:10],
            "end_date": end_date,
            "content_count": content_count,
            "status": "active",
            "payments_received": 0.0,
            "content_delivered": 0,
            "metadata": {},
            "created_at": utcnow(),
        }
        self._save(sponsorship)
        return sponsorship

    def get_sponsorship(self, sid: str) -> Optional[dict]:
        path = self._path_for(sid)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_sponsorships(self, status: Optional[str] = None,
                          limit: int = 100) -> list[dict]:
        results = []
        for p in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                results.append(data)
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results

    def update_sponsorship(self, sid: str, updates: dict) -> Optional[dict]:
        s = self.get_sponsorship(sid)
        if not s:
            return None
        s.update(updates)
        self._save(s)
        return s

    def record_payment(self, sid: str, amount: float) -> bool:
        s = self.get_sponsorship(sid)
        if not s:
            return False
        s["payments_received"] = s.get("payments_received", 0) + amount
        self._save(s)
        return True

    def record_delivery(self, sid: str) -> bool:
        s = self.get_sponsorship(sid)
        if not s:
            return False
        s["content_delivered"] = s.get("content_delivered", 0) + 1
        self._save(s)
        return True

    def get_total_value(self, status: Optional[str] = None) -> float:
        sponsorships = self.list_sponsorships(status=status)
        return round(sum(s.get("deal_value", 0) for s in sponsorships), 2)

    def get_total_received(self) -> float:
        sponsorships = self.list_sponsorships()
        return round(sum(s.get("payments_received", 0) for s in sponsorships), 2)
