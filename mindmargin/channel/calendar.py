import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import CalendarEntry, ContentFormat, ContentItem, ContentState

logger = logging.getLogger(__name__)

DEFAULT_CADENCE = {
    ContentFormat.SHORT: timedelta(hours=24),
    ContentFormat.LONG: timedelta(hours=72),
}

DEFAULT_PUBLISH_HOUR = 14


class PublishingCalendar:
    def __init__(self, lifecycle: Optional[ContentLifecycle] = None):
        self._lifecycle = lifecycle or ContentLifecycle()

    def generate(self, days: int = 30) -> list[CalendarEntry]:
        planned = self._lifecycle.list_by_states([ContentState.PLANNED, ContentState.RESEARCHING])
        if not planned:
            return []
        planned.sort(key=lambda x: (x.priority, x.opportunity_score), reverse=True)
        entries: list[CalendarEntry] = []
        cursor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        format_last: dict[str, datetime] = {}
        daily_count: dict[str, int] = {}
        for item in planned:
            if len(entries) >= days:
                break
            cadence = DEFAULT_CADENCE.get(item.format, timedelta(hours=72))
            last = format_last.get(item.format.value, cursor - cadence)
            next_slot = last + cadence
            if next_slot < cursor:
                next_slot = cursor
            day_key = next_slot.strftime("%Y-%m-%d")
            daily_count[day_key] = daily_count.get(day_key, 0) + 1
            if daily_count[day_key] > 2:
                next_slot += timedelta(hours=12)
                day_key = next_slot.strftime("%Y-%m-%d")
                daily_count[day_key] = daily_count.get(day_key, 0) + 1
            scheduled_time = next_slot.replace(hour=DEFAULT_PUBLISH_HOUR, minute=0)
            if scheduled_time < next_slot:
                scheduled_time += timedelta(days=1)
            format_last[item.format.value] = scheduled_time
            entry = CalendarEntry(
                topic=item.topic,
                format=item.format,
                priority=item.priority,
                publish_time=scheduled_time.isoformat(),
                estimated_confidence=item.confidence,
                estimated_opportunity=item.opportunity_score,
                required_assets=item.asset_requirements,
                workflow_id=item.workflow_id,
                category=item.category,
                content_id=item.content_id,
            )
            entries.append(entry)
        return entries

    def generate_7_day(self) -> list[CalendarEntry]:
        return self.generate(days=7)

    def generate_30_day(self) -> list[CalendarEntry]:
        return self.generate(days=30)

    def generate_90_day(self) -> list[CalendarEntry]:
        return self.generate(days=90)

    def get_upcoming(self, limit: int = 10) -> list[CalendarEntry]:
        now = datetime.now(timezone.utc)
        scheduled = self._lifecycle.list_by_state(ContentState.SCHEDULED)
        entries: list[CalendarEntry] = []
        for item in scheduled:
            if not item.estimated_publish_at:
                continue
            try:
                pub_time = datetime.fromisoformat(item.estimated_publish_at)
            except ValueError:
                continue
            if pub_time > now:
                entries.append(CalendarEntry(
                    topic=item.topic,
                    format=item.format,
                    priority=item.priority,
                    publish_time=item.estimated_publish_at,
                    estimated_confidence=item.confidence,
                    estimated_opportunity=item.opportunity_score,
                    required_assets=item.asset_requirements,
                    workflow_id=item.workflow_id,
                    category=item.category,
                    content_id=item.content_id,
                ))
        entries.sort(key=lambda e: e.publish_time)
        return entries[:limit]

    def get_published_recent(self, days: int = 7) -> list[CalendarEntry]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        published = self._lifecycle.list_by_states([
            ContentState.PUBLISHED, ContentState.ANALYZING, ContentState.LEARNING,
        ])
        entries: list[CalendarEntry] = []
        for item in published:
            if item.published_at:
                try:
                    pub_time = datetime.fromisoformat(item.published_at)
                except ValueError:
                    continue
                if pub_time >= cutoff:
                    entries.append(CalendarEntry(
                        topic=item.topic,
                        format=item.format,
                        priority=item.priority,
                        publish_time=item.published_at,
                        estimated_confidence=item.confidence,
                        estimated_opportunity=item.opportunity_score,
                        category=item.category,
                        content_id=item.content_id,
                    ))
        entries.sort(key=lambda e: e.publish_time, reverse=True)
        return entries
