import logging
from datetime import datetime, timezone
from typing import Optional

from mindmargin.channel.calendar import PublishingCalendar
from mindmargin.channel.governance import GovernanceEngine
from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import (
    CalendarEntry,
    ChannelReport,
    ContentFormat,
    ContentItem,
    ContentState,
)
from mindmargin.channel.publisher import ChannelPublisher
from mindmargin.channel.review import ContentReview
from mindmargin.channel.strategy import ChannelStrategy
from mindmargin.core.scheduler import Scheduler
from mindmargin.core.workflows import WorkflowEngine

logger = logging.getLogger(__name__)


class ChannelManager:
    def __init__(self, engine: Optional[WorkflowEngine] = None,
                 scheduler: Optional[Scheduler] = None):
        self._engine = engine or WorkflowEngine()
        self._scheduler = scheduler
        self._lifecycle = ContentLifecycle()
        self._strategy = ChannelStrategy(lifecycle=self._lifecycle)
        self._calendar = PublishingCalendar(lifecycle=self._lifecycle)
        self._governance = GovernanceEngine()
        self._publisher = ChannelPublisher(lifecycle=self._lifecycle, engine=self._engine)
        self._review = ContentReview(lifecycle=self._lifecycle)

    @property
    def lifecycle(self) -> ContentLifecycle:
        return self._lifecycle

    @property
    def strategy(self) -> ChannelStrategy:
        return self._strategy

    @property
    def calendar(self) -> PublishingCalendar:
        return self._calendar

    @property
    def governance(self) -> GovernanceEngine:
        return self._governance

    @property
    def publisher(self) -> ChannelPublisher:
        return self._publisher

    @property
    def review(self) -> ContentReview:
        return self._review

    def run_daily_cycle(self) -> dict:
        logger.info("=== Channel Manager Daily Cycle Starting ===")
        results = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps": {},
        }

        # Step 1: Refresh opportunities
        logger.info("Step 1/6: Refreshing intelligence opportunities...")
        try:
            from mindmargin.intelligence.scoring import run_opportunity_scoring
            scored = run_opportunity_scoring()
            results["steps"]["scoring"] = {"status": "completed", "candidates": len(scored)}
        except Exception as e:
            logger.warning("Scoring refresh failed: %s", e)
            results["steps"]["scoring"] = {"status": "failed", "error": str(e)}

        # Step 2: Build content plan from opportunities
        logger.info("Step 2/6: Building content plan...")
        try:
            opportunities = self._strategy.select_topics(limit=30)
            new_items = self._strategy.build_content_plan(opportunities)
            results["steps"]["planning"] = {"status": "completed", "new_items": len(new_items)}
        except Exception as e:
            logger.warning("Content planning failed: %s", e)
            results["steps"]["planning"] = {"status": "failed", "error": str(e)}

        # Step 3: Generate calendar
        logger.info("Step 3/6: Generating publishing calendar...")
        try:
            cal_7 = self._calendar.generate_7_day()
            cal_30 = self._calendar.generate_30_day()
            cal_90 = self._calendar.generate_90_day()
            results["steps"]["calendar"] = {
                "status": "completed",
                "7day": len(cal_7),
                "30day": len(cal_30),
                "90day": len(cal_90),
            }
        except Exception as e:
            logger.warning("Calendar generation failed: %s", e)
            results["steps"]["calendar"] = {"status": "failed", "error": str(e)}

        # Step 4: Governance check on planned items
        logger.info("Step 4/6: Running governance checks...")
        try:
            planned = self._lifecycle.list_by_state(ContentState.PLANNED)
            allowed = self._governance.evaluate_many(planned)
            blocked = len(planned) - len(allowed)
            results["steps"]["governance"] = {
                "status": "completed",
                "checked": len(planned),
                "allowed": len(allowed),
                "blocked": blocked,
            }
        except Exception as e:
            logger.warning("Governance check failed: %s", e)
            results["steps"]["governance"] = {"status": "failed", "error": str(e)}

        # Step 5: Review and advance ready items
        logger.info("Step 5/6: Reviewing production-ready items...")
        try:
            producing = self._lifecycle.list_by_state(ContentState.PRODUCING)
            reviewed = 0
            for item in producing:
                review_result = self._review.review_item(item.content_id)
                if review_result.get("status") == "approved":
                    self._lifecycle.transition_to(item.content_id, ContentState.REVIEWING)
                    reviewed += 1
            results["steps"]["review"] = {"status": "completed", "reviewed": reviewed}
        except Exception as e:
            logger.warning("Review step failed: %s", e)
            results["steps"]["review"] = {"status": "failed", "error": str(e)}

        # Step 6: Publish next scheduled item
        logger.info("Step 6/6: Publishing next scheduled item...")
        try:
            scheduled = self._lifecycle.list_by_state(ContentState.SCHEDULED)
            if not scheduled:
                # Try to advance from reviewing if nothing scheduled
                reviewing = self._lifecycle.list_by_state(ContentState.REVIEWING)
                if reviewing:
                    next_item = reviewing[0]
                    cal_entry = CalendarEntry(
                        topic=next_item.topic,
                        format=next_item.format,
                        priority=next_item.priority,
                        publish_time=datetime.now(timezone.utc).isoformat(),
                        estimated_confidence=next_item.confidence,
                        estimated_opportunity=next_item.opportunity_score,
                        content_id=next_item.content_id,
                    )
                    results["steps"]["publish"] = {"status": "scheduled", "topic": next_item.topic}
                else:
                    results["steps"]["publish"] = {"status": "skipped", "reason": "nothing_to_publish"}
            else:
                next_item = scheduled[0]
                gov_result = self._governance.evaluate(next_item)
                if gov_result.allowed:
                    pub_result = self._publisher.publish(next_item.content_id)
                    results["steps"]["publish"] = {
                        "status": pub_result.get("status", "completed"),
                        "topic": next_item.topic,
                        "content_id": next_item.content_id,
                    }
                else:
                    results["steps"]["publish"] = {
                        "status": "blocked",
                        "reason": gov_result.reason,
                        "topic": next_item.topic,
                    }
        except Exception as e:
            logger.warning("Publish step failed: %s", e)
            results["steps"]["publish"] = {"status": "failed", "error": str(e)}

        results["status"] = "completed"
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("=== Channel Manager Daily Cycle Complete ===")
        return results

    def get_status(self) -> ChannelReport:
        all_items = self._lifecycle.list_all()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        published_today = sum(
            1 for i in all_items
            if i.is_published and i.published_at and i.published_at.startswith(today)
        )
        scheduled = self._lifecycle.list_by_state(ContentState.SCHEDULED)
        active_states = [ContentState.PLANNED, ContentState.RESEARCHING, ContentState.WRITING,
                         ContentState.PRODUCING, ContentState.REVIEWING]
        active = [i for i in all_items if i.state in active_states]

        state_breakdown = self._lifecycle.count_by_state()
        format_count = {ContentFormat.SHORT.value: 0, ContentFormat.LONG.value: 0}
        for item in all_items:
            f = item.format.value
            format_count[f] = format_count.get(f, 0) + 1

        health_score = 10.0
        try:
            from mindmargin.analytics.channel_brain import assess_channel_health
            health = assess_channel_health()
            health_score = health.get("overall_score", 10)
        except Exception as e:
            logger.warning("Failed to get channel health: %s", e)

        cal_7 = self._calendar.generate_7_day()
        cal_30 = self._calendar.generate_30_day()
        cal_90 = self._calendar.generate_90_day()

        governance_rules = self._governance.get_rules()
        active_rules = sum(1 for r in governance_rules if r.enabled)

        recent = sorted(all_items, key=lambda i: i.updated_at, reverse=True)[:10]

        return ChannelReport(
            status="operational",
            active_content=len(active),
            published_today=published_today,
            scheduled_count=len(scheduled),
            health_score=health_score,
            total_items=len(all_items),
            state_breakdown=state_breakdown,
            recent_items=[i.to_dict() for i in recent],
            calendar_7day=len(cal_7),
            calendar_30day=len(cal_30),
            calendar_90day=len(cal_90),
            governance_rules_active=active_rules,
            format_balance=format_count,
        )

    def get_calendar(self, days: int = 30) -> list[CalendarEntry]:
        if days <= 7:
            return self._calendar.generate_7_day()
        elif days <= 30:
            return self._calendar.generate_30_day()
        else:
            return self._calendar.generate_90_day()

    def get_content(self, content_id: Optional[str] = None,
                    state: Optional[str] = None) -> list[dict]:
        if content_id:
            item = self._lifecycle.get(content_id)
            return [item.to_dict()] if item else []
        if state:
            try:
                cs = ContentState(state)
                return [i.to_dict() for i in self._lifecycle.list_by_state(cs)]
            except ValueError:
                pass
        return [i.to_dict() for i in self._lifecycle.list_all()]

    def advance_content(self, content_id: str, target_state: str) -> bool:
        try:
            cs = ContentState(target_state)
            return self._lifecycle.transition_to(content_id, cs)
        except ValueError:
            return False

    def get_governance_rules(self) -> list[dict]:
        return [r.to_dict() for r in self._governance.get_rules()]

    def toggle_governance_rule(self, rule_id: str) -> Optional[bool]:
        return self._governance.toggle_rule(rule_id)
