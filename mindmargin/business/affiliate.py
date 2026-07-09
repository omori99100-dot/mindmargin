import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import utcnow

logger = logging.getLogger(__name__)


class AffiliateManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "business" / "affiliate"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, aid: str) -> Path:
        return self._dir / f"{aid}.json"

    def _save(self, data: dict):
        aid = data.get("affiliate_id", "")
        path = self._path_for(aid)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_affiliate_program(self, program_name: str, commission_rate: float,
                                  cookie_days: int = 30,
                                  products: list[str] = None) -> dict:
        program = {
            "affiliate_id": f"aff_{uuid.uuid4().hex[:10]}",
            "program_name": program_name,
            "commission_rate": commission_rate,
            "cookie_days": cookie_days,
            "products": products or [],
            "status": "active",
            "total_clicks": 0,
            "total_conversions": 0,
            "total_revenue": 0.0,
            "total_commission": 0.0,
            "links": [],
            "metadata": {},
            "created_at": utcnow(),
        }
        self._save(program)
        return program

    def get_program(self, aid: str) -> Optional[dict]:
        path = self._path_for(aid)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_programs(self, status: Optional[str] = None,
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

    def record_click(self, aid: str, link_url: str = "") -> bool:
        program = self.get_program(aid)
        if not program:
            return False
        program["total_clicks"] = program.get("total_clicks", 0) + 1
        if link_url:
            program.setdefault("links", []).append({"url": link_url, "clicks": 1, "date": utcnow()[:10]})
        self._save(program)
        return True

    def record_conversion(self, aid: str, revenue: float) -> bool:
        program = self.get_program(aid)
        if not program:
            return False
        program["total_conversions"] = program.get("total_conversions", 0) + 1
        program["total_revenue"] = program.get("total_revenue", 0) + revenue
        commission = revenue * program.get("commission_rate", 0.1)
        program["total_commission"] = program.get("total_commission", 0) + commission
        self._save(program)
        return True

    def get_ctr(self, aid: str) -> float:
        program = self.get_program(aid)
        if not program or program.get("total_clicks", 0) == 0:
            return 0.0
        return round((program["total_conversions"] / program["total_clicks"]) * 100, 2)

    def get_total_revenue(self) -> float:
        programs = self.list_programs()
        return round(sum(p.get("total_revenue", 0) for p in programs), 2)

    def get_total_commission(self) -> float:
        programs = self.list_programs()
        return round(sum(p.get("total_commission", 0) for p in programs), 2)
