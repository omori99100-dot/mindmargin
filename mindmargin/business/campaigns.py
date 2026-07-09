import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import (
    Campaign, CampaignType, CampaignStatus, utcnow,
)

logger = logging.getLogger(__name__)


class CampaignManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "business" / "campaigns"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, cid: str) -> Path:
        return self._dir / f"{cid}.json"

    def _save(self, campaign: Campaign):
        path = self._path_for(campaign.campaign_id)
        path.write_text(json.dumps(campaign.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def create_campaign(self, campaign_type: CampaignType, name: str,
                        budget: float = 0.0, start_date: str = "",
                        end_date: str = "", target_audience: str = "") -> Campaign:
        campaign = Campaign(
            campaign_id=f"camp_{uuid.uuid4().hex[:10]}",
            campaign_type=campaign_type,
            name=name,
            status=CampaignStatus.PLANNED,
            budget=budget,
            start_date=start_date or utcnow()[:10],
            end_date=end_date,
            target_audience=target_audience,
        )
        self._save(campaign)
        return campaign

    def get_campaign(self, cid: str) -> Optional[Campaign]:
        path = self._path_for(cid)
        if not path.exists():
            return None
        try:
            return Campaign.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def list_campaigns(self, status: Optional[CampaignStatus] = None,
                       campaign_type: Optional[CampaignType] = None,
                       limit: int = 100) -> list[Campaign]:
        results = []
        for p in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                c = Campaign.from_dict(json.loads(p.read_text(encoding="utf-8")))
                if status and c.status != status:
                    continue
                if campaign_type and c.campaign_type != campaign_type:
                    continue
                results.append(c)
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results

    def update_campaign(self, cid: str, updates: dict) -> Optional[Campaign]:
        c = self.get_campaign(cid)
        if not c:
            return None
        for k, v in updates.items():
            if hasattr(c, k):
                setattr(c, k, v)
        self._save(c)
        return c

    def record_spend(self, cid: str, amount: float) -> bool:
        c = self.get_campaign(cid)
        if not c:
            return False
        c.spent += amount
        self._save(c)
        return True

    def record_revenue(self, cid: str, amount: float) -> bool:
        c = self.get_campaign(cid)
        if not c:
            return False
        c.revenue += amount
        self._save(c)
        return True

    def start_campaign(self, cid: str) -> Optional[Campaign]:
        return self.update_campaign(cid, {"status": CampaignStatus.ACTIVE})

    def pause_campaign(self, cid: str) -> Optional[Campaign]:
        return self.update_campaign(cid, {"status": CampaignStatus.PAUSED})

    def complete_campaign(self, cid: str) -> Optional[Campaign]:
        return self.update_campaign(cid, {"status": CampaignStatus.COMPLETED})

    def cancel_campaign(self, cid: str) -> Optional[Campaign]:
        return self.update_campaign(cid, {"status": CampaignStatus.CANCELLED})

    def get_total_budget(self) -> float:
        campaigns = self.list_campaigns()
        return round(sum(c.budget for c in campaigns), 2)

    def get_total_spent(self) -> float:
        campaigns = self.list_campaigns()
        return round(sum(c.spent for c in campaigns), 2)

    def get_total_revenue(self) -> float:
        campaigns = self.list_campaigns()
        return round(sum(c.revenue for c in campaigns), 2)

    def get_overall_roi(self) -> float:
        total_spent = self.get_total_spent()
        total_revenue = self.get_total_revenue()
        if total_spent <= 0:
            return 0.0
        return round(((total_revenue - total_spent) / total_spent) * 100, 1)

    def get_active_campaigns(self) -> list[Campaign]:
        return self.list_campaigns(status=CampaignStatus.ACTIVE)
