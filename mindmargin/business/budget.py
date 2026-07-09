import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import CostEntry, BudgetAllocation, utcnow

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = ["api", "llm", "storage", "rendering", "operations", "marketing", "tools", "other"]


class BudgetManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "business" / "budget"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._costs_dir = self._dir / "costs"
        self._costs_dir.mkdir(parents=True, exist_ok=True)
        self._alloc_path = self._dir / "allocations.json"

    def record_cost(self, category: str, amount: float, description: str = "",
                    is_recurring: bool = False, date: str = "") -> CostEntry:
        entry = CostEntry(
            entry_id=f"cost_{uuid.uuid4().hex[:10]}",
            category=category,
            amount=amount,
            date=date or utcnow()[:10],
            description=description,
            is_recurring=is_recurring,
        )
        path = self._costs_dir / f"{entry.entry_id}.json"
        path.write_text(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return entry

    def list_costs(self, category: Optional[str] = None,
                   start_date: str = "", end_date: str = "",
                   limit: int = 500) -> list[CostEntry]:
        results = []
        for p in sorted(self._costs_dir.glob("*.json"), reverse=True):
            try:
                entry = CostEntry.from_dict(json.loads(p.read_text(encoding="utf-8")))
                if category and entry.category != category:
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

    def get_total_costs(self, start_date: str = "", end_date: str = "") -> float:
        costs = self.list_costs(start_date=start_date, end_date=end_date)
        return round(sum(c.amount for c in costs), 2)

    def get_costs_by_category(self, start_date: str = "", end_date: str = "") -> dict[str, float]:
        costs = self.list_costs(start_date=start_date, end_date=end_date)
        by_cat: dict[str, float] = {}
        for c in costs:
            by_cat[c.category] = by_cat.get(c.category, 0) + c.amount
        return {k: round(v, 2) for k, v in by_cat.items()}

    def get_monthly_costs(self, months: int = 12) -> list[dict]:
        costs = self.list_costs(limit=2000)
        monthly: dict[str, float] = {}
        for c in costs:
            month_key = c.date[:7] if c.date else "unknown"
            monthly[month_key] = monthly.get(month_key, 0) + c.amount
        result = [{"month": k, "costs": round(v, 2)} for k, v in sorted(monthly.items())]
        return result[-months:]

    def set_allocations(self, allocations: list[BudgetAllocation]):
        data = [a.to_dict() for a in allocations]
        self._alloc_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_allocations(self) -> list[BudgetAllocation]:
        if not self._alloc_path.exists():
            return [BudgetAllocation(category=cat, limit=1000) for cat in DEFAULT_CATEGORIES]
        try:
            data = json.loads(self._alloc_path.read_text(encoding="utf-8"))
            return [BudgetAllocation(**d) for d in data]
        except Exception:
            return []

    def update_allocation_spent(self, category: str, spent: float):
        allocs = self.get_allocations()
        for a in allocs:
            if a.category == category:
                a.spent = spent
                break
        self.set_allocations(allocs)

    def get_budget_summary(self) -> dict:
        allocs = self.get_allocations()
        total_limit = sum(a.limit for a in allocs)
        total_spent = sum(a.spent for a in allocs)
        return {
            "total_limit": total_limit,
            "total_spent": total_spent,
            "total_remaining": round(max(total_limit - total_spent, 0), 2),
            "utilization_pct": round((total_spent / max(total_limit, 1)) * 100, 1),
            "allocations": [a.to_dict() for a in allocs],
        }

    def delete_cost(self, entry_id: str) -> bool:
        path = self._costs_dir / f"{entry_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
