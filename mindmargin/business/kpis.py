import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import KPIRecord, utcnow

logger = logging.getLogger(__name__)


class KPIEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._kpi_dir = root / "business" / "kpis"
        self._kpi_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, kpi_id: str) -> Path:
        return self._kpi_dir / f"{kpi_id}.json"

    def _save(self, kpi: KPIRecord):
        path = self._path_for(kpi.kpi_id)
        path.write_text(json.dumps(kpi.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def record_kpi(self, name: str, value: float, previous_value: float = 0.0,
                   target_value: float = 0.0, unit: str = "", category: str = "",
                   period: str = "") -> KPIRecord:
        kpi_id = f"kpi_{uuid.uuid4().hex[:10]}"
        kpi = KPIRecord(
            kpi_id=kpi_id,
            name=name,
            value=value,
            previous_value=previous_value,
            target_value=target_value,
            unit=unit,
            category=category,
            period=period,
            timestamp=utcnow(),
        )
        self._save(kpi)
        return kpi

    def get_kpi(self, kpi_id: str) -> Optional[KPIRecord]:
        path = self._path_for(kpi_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return KPIRecord.from_dict(data)
        except Exception:
            return None

    def list_kpis(self, category: Optional[str] = None,
                  name: Optional[str] = None, limit: int = 100) -> list[KPIRecord]:
        results = []
        for p in self._kpi_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                kpi = KPIRecord.from_dict(data)
                if category and kpi.category != category:
                    continue
                if name and kpi.name != name:
                    continue
                results.append(kpi)
            except Exception:
                continue
        results.sort(key=lambda k: k.timestamp, reverse=True)
        return results[:limit]

    def get_latest_kpi(self, name: str) -> Optional[KPIRecord]:
        kpis = self.list_kpis(name=name, limit=1)
        return kpis[0] if kpis else None

    def get_kpi_trend(self, name: str, limit: int = 30) -> list[KPIRecord]:
        return self.list_kpis(name=name, limit=limit)

    def compute_rpm(self, total_revenue: float, total_views: int) -> float:
        if total_views == 0:
            return 0.0
        return round((total_revenue / total_views) * 1000, 2)

    def compute_cpm(self, ad_revenue: float, impressions: int) -> float:
        if impressions == 0:
            return 0.0
        return round((ad_revenue / impressions) * 1000, 2)

    def compute_ctr(self, clicks: int, impressions: int) -> float:
        if impressions == 0:
            return 0.0
        return round((clicks / impressions) * 100, 2)

    def compute_conversion_rate(self, conversions: int, total_visitors: int) -> float:
        if total_visitors == 0:
            return 0.0
        return round((conversions / total_visitors) * 100, 2)

    def compute_ltv(self, avg_revenue_per_user: float, avg_lifetime_months: float) -> float:
        return round(avg_revenue_per_user * avg_lifetime_months, 2)

    def compute_engagement_rate(self, likes: int, comments: int, shares: int, views: int) -> float:
        if views == 0:
            return 0.0
        return round(((likes + comments + shares) / views) * 100, 2)

    def get_kpi_summary(self) -> dict:
        all_kpis = self.list_kpis(limit=500)
        by_category: dict[str, list] = {}
        for kpi in all_kpis:
            by_category.setdefault(kpi.category or "general", []).append(kpi.to_dict())
        return {
            "total_kpis": len(all_kpis),
            "categories": list(by_category.keys()),
            "kpis_by_category": {k: len(v) for k, v in by_category.items()},
        }
