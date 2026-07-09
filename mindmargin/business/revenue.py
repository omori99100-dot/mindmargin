import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import (
    RevenueEntry, RevenueType, utcnow,
)

logger = logging.getLogger(__name__)


class RevenueEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._revenue_dir = root / "business" / "revenue"
        self._revenue_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, entry_id: str) -> Path:
        return self._revenue_dir / f"{entry_id}.json"

    def _save(self, entry: RevenueEntry):
        path = self._path_for(entry.entry_id)
        path.write_text(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def record_revenue(self, revenue_type: RevenueType, amount: float,
                       source: str = "", description: str = "",
                       date: str = "") -> RevenueEntry:
        entry = RevenueEntry(
            entry_id=f"rev_{uuid.uuid4().hex[:10]}",
            revenue_type=revenue_type,
            amount=amount,
            date=date or utcnow()[:10],
            source=source,
            description=description,
        )
        self._save(entry)
        return entry

    def get_entry(self, entry_id: str) -> Optional[RevenueEntry]:
        path = self._path_for(entry_id)
        if not path.exists():
            return None
        try:
            return RevenueEntry.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def list_entries(self, revenue_type: Optional[RevenueType] = None,
                     start_date: str = "", end_date: str = "",
                     limit: int = 500) -> list[RevenueEntry]:
        results = []
        for p in sorted(self._revenue_dir.glob("*.json"), reverse=True):
            try:
                entry = RevenueEntry.from_dict(json.loads(p.read_text(encoding="utf-8")))
                if revenue_type and entry.revenue_type != revenue_type:
                    continue
                if start_date and entry.date < start_date:
                    continue
                if end_date and entry.date > end_date:
                    continue
                results.append(entry)
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results

    def get_total_revenue(self, start_date: str = "", end_date: str = "") -> float:
        entries = self.list_entries(start_date=start_date, end_date=end_date)
        return round(sum(e.amount for e in entries), 2)

    def get_revenue_by_type(self, start_date: str = "", end_date: str = "") -> dict[str, float]:
        entries = self.list_entries(start_date=start_date, end_date=end_date)
        by_type: dict[str, float] = {}
        for e in entries:
            t = e.revenue_type.value
            by_type[t] = by_type.get(t, 0) + e.amount
        return {k: round(v, 2) for k, v in by_type.items()}

    def get_revenue_by_source(self, start_date: str = "", end_date: str = "") -> dict[str, float]:
        entries = self.list_entries(start_date=start_date, end_date=end_date)
        by_source: dict[str, float] = {}
        for e in entries:
            s = e.source or "unknown"
            by_source[s] = by_source.get(s, 0) + e.amount
        return {k: round(v, 2) for k, v in by_source.items()}

    def get_monthly_revenue(self, months: int = 12) -> list[dict]:
        entries = self.list_entries(limit=2000)
        monthly: dict[str, float] = {}
        for e in entries:
            month_key = e.date[:7] if e.date else "unknown"
            monthly[month_key] = monthly.get(month_key, 0) + e.amount
        result = [{"month": k, "revenue": round(v, 2)} for k, v in sorted(monthly.items())]
        return result[-months:]

    def delete_entry(self, entry_id: str) -> bool:
        path = self._path_for(entry_id)
        if path.exists():
            path.unlink()
            return True
        return False
