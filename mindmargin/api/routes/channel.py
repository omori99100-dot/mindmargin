from fastapi import APIRouter

from mindmargin.api.schemas import (
    CalendarResponse,
    ChannelStatusResponse,
    ContentAdvanceRequest,
    ContentAdvanceResponse,
    ContentListResponse,
    DailyCycleResponse,
    GovernanceRuleResponse,
    GovernanceToggleResponse,
    ErrorResponse,
)
from mindmargin.channel.manager import ChannelManager

router = APIRouter(prefix="/api/v1/channel", tags=["channel"])


@router.get("/status", response_model=ChannelStatusResponse)
def channel_status():
    mgr = ChannelManager()
    report = mgr.get_status()
    return ChannelStatusResponse(
        status=report.status,
        active_content=report.active_content,
        published_today=report.published_today,
        scheduled_count=report.scheduled_count,
        health_score=report.health_score,
        total_items=report.total_items,
        state_breakdown=report.state_breakdown,
        recent_items=report.recent_items,
        calendar_7day=report.calendar_7day,
        calendar_30day=report.calendar_30day,
        calendar_90day=report.calendar_90day,
        governance_rules_active=report.governance_rules_active,
        format_balance=report.format_balance,
    )


@router.get("/calendar", response_model=CalendarResponse)
def channel_calendar(days: int = 30):
    mgr = ChannelManager()
    entries = mgr.get_calendar(days)
    return CalendarResponse(
        entries=[e.to_dict() for e in entries],
        total=len(entries),
        days=days,
    )


@router.get("/content", response_model=ContentListResponse)
def channel_content(content_id: str = "", state: str = ""):
    mgr = ChannelManager()
    items = mgr.get_content(content_id=content_id or None, state=state or None)
    return ContentListResponse(items=items, total=len(items))


@router.post("/content/{content_id}/advance", response_model=ContentAdvanceResponse)
def channel_advance(content_id: str, req: ContentAdvanceRequest):
    mgr = ChannelManager()
    item = mgr.get_content(content_id=content_id)
    if not item:
        return ContentAdvanceResponse(content_id=content_id, status="failed", new_state="not_found")
    prev = item[0].get("state", "")
    ok = mgr.advance_content(content_id, req.target_state)
    return ContentAdvanceResponse(
        content_id=content_id,
        status="ok" if ok else "failed",
        previous_state=prev,
        new_state=req.target_state if ok else prev,
    )


@router.get("/governance", response_model=GovernanceRuleResponse)
def channel_governance():
    mgr = ChannelManager()
    rules = mgr.get_governance_rules()
    return GovernanceRuleResponse(rules=rules, total=len(rules))


@router.post("/governance/{rule_id}/toggle", response_model=GovernanceToggleResponse)
def channel_governance_toggle(rule_id: str):
    mgr = ChannelManager()
    result = mgr.toggle_governance_rule(rule_id)
    if result is None:
        return GovernanceToggleResponse(rule_id=rule_id, enabled=False, status="not_found")
    return GovernanceToggleResponse(rule_id=rule_id, enabled=result, status="ok")


@router.post("/daily-cycle", response_model=DailyCycleResponse)
def channel_daily_cycle():
    mgr = ChannelManager()
    result = mgr.run_daily_cycle()
    return DailyCycleResponse(
        status=result.get("status", "failed"),
        started_at=result.get("started_at", ""),
        completed_at=result.get("completed_at", ""),
        steps=result.get("steps", {}),
    )
