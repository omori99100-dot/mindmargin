import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import (
    RevenueEntry, CostEntry, RevenueType, ForecastResult,
    ForecastPoint, ForecastWindow, utcnow,
)

logger = logging.getLogger(__name__)

FORECAST_WINDOWS = {
    ForecastWindow.DAYS_30: 30,
    ForecastWindow.DAYS_90: 90,
    ForecastWindow.DAYS_180: 180,
    ForecastWindow.DAYS_365: 365,
}


class ForecastEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._forecast_dir = root / "business" / "forecasts"
        self._forecast_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, forecast_id: str) -> Path:
        return self._forecast_dir / f"{forecast_id}.json"

    def _save(self, forecast: ForecastResult):
        path = self._path_for(forecast.forecast_id)
        path.write_text(json.dumps(forecast.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def generate_forecast(self, revenue_entries: list[RevenueEntry],
                          cost_entries: list[CostEntry],
                          window: ForecastWindow = ForecastWindow.DAYS_30,
                          growth_rate: float = 0.05,
                          subscriber_count: int = 0,
                          avg_views_per_video: int = 0,
                          rpm: float = 0.0) -> ForecastResult:
        days = FORECAST_WINDOWS[window]
        forecast_id = f"fc_{uuid.uuid4().hex[:10]}"

        daily_revenue = self._compute_daily_revenue(revenue_entries)
        daily_costs = self._compute_daily_costs(cost_entries)

        points = []
        now = datetime.now(timezone.utc)
        cumulative_revenue = 0.0
        cumulative_expenses = 0.0
        current_subs = subscriber_count
        current_views_per_video = avg_views_per_video

        for day in range(days):
            date = (now + timedelta(days=day)).strftime("%Y-%m-%d")
            day_revenue = daily_revenue * (1 + growth_rate) ** day
            day_cost = daily_costs
            cumulative_revenue += day_revenue
            cumulative_expenses += day_cost

            current_subs = int(current_subs * (1 + growth_rate * 0.1))
            current_views = int(current_views_per_video * (1 + growth_rate * 0.05) ** day)
            day_roi = ((day_revenue - day_cost) / max(day_cost, 1)) * 100

            confidence = max(0.9 - (day * 0.01), 0.3)

            points.append(ForecastPoint(
                date=date,
                revenue=round(day_revenue, 2),
                subscribers=current_subs,
                views=current_views,
                expenses=round(day_cost, 2),
                roi=round(day_roi, 1),
                confidence=round(confidence, 2),
            ).to_dict())

        total_revenue = sum(p["revenue"] for p in points)
        total_expenses = sum(p["expenses"] for p in points)
        total_profit = total_revenue - total_expenses
        overall_roi = ((total_revenue - total_expenses) / max(total_expenses, 1)) * 100

        summary = {
            "total_revenue": round(total_revenue, 2),
            "total_expenses": round(total_expenses, 2),
            "total_profit": round(total_profit, 2),
            "overall_roi": round(overall_roi, 1),
            "final_subscribers": current_subs,
            "avg_daily_revenue": round(total_revenue / days, 2),
            "avg_daily_expenses": round(total_expenses / days, 2),
            "growth_rate": growth_rate,
        }

        forecast = ForecastResult(
            forecast_id=forecast_id,
            window=window.value,
            generated_at=utcnow(),
            points=points,
            summary=summary,
            assumptions=[
                f"Growth rate: {growth_rate:.1%}",
                f"Starting subscribers: {subscriber_count}",
                f"Starting views/video: {avg_views_per_video}",
                f"RPM: ${rpm:.2f}",
            ],
        )
        self._save(forecast)
        logger.info("Forecast %s generated for %s window", forecast_id, window.value)
        return forecast

    def get_forecast(self, forecast_id: str) -> Optional[ForecastResult]:
        path = self._path_for(forecast_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ForecastResult.from_dict(data)
        except Exception:
            return None

    def list_forecasts(self, limit: int = 20) -> list[ForecastResult]:
        results = []
        for p in sorted(self._forecast_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append(ForecastResult.from_dict(data))
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results

    def _compute_daily_revenue(self, entries: list[RevenueEntry]) -> float:
        if not entries:
            return 10.0
        total = sum(e.amount for e in entries)
        dates = set()
        for e in entries:
            if e.date:
                dates.add(e.date[:10])
        days = max(len(dates), 1)
        return total / days

    def _compute_daily_costs(self, entries: list[CostEntry]) -> float:
        if not entries:
            return 5.0
        recurring = sum(e.amount for e in entries if e.is_recurring)
        one_time = sum(e.amount for e in entries if not e.is_recurring)
        return recurring / 30 + one_time / 90
