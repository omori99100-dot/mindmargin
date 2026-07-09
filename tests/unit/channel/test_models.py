import pytest
from mindmargin.channel.models import (
    CONTENT_STATE_TRANSITIONS,
    CalendarEntry,
    ChannelReport,
    ContentFormat,
    ContentItem,
    ContentState,
    GovernanceResult,
    GovernanceRule,
    GovernanceRuleType,
)


class TestContentFormat:
    def test_enum_values(self):
        assert ContentFormat.SHORT.value == "short"
        assert ContentFormat.LONG.value == "long"


class TestContentState:
    def test_enum_values(self):
        assert ContentState.PLANNED.value == "planned"
        assert ContentState.PUBLISHED.value == "published"
        assert ContentState.ARCHIVED.value == "archived"

    def test_all_states_have_transitions(self):
        for state in ContentState:
            assert state in CONTENT_STATE_TRANSITIONS


class TestContentItem:
    def test_create_basic(self):
        item = ContentItem(
            content_id="c001",
            topic="Test topic",
            format=ContentFormat.SHORT,
            category="tech",
            state=ContentState.PLANNED,
        )
        assert item.content_id == "c001"
        assert item.state == ContentState.PLANNED
        assert item.priority == 5

    def test_to_dict(self):
        item = ContentItem(
            content_id="c002",
            topic="Python tips",
            format=ContentFormat.LONG,
            category="programming",
            state=ContentState.PLANNED,
            confidence=0.85,
            opportunity_score=72.5,
        )
        d = item.to_dict()
        assert d["content_id"] == "c002"
        assert d["format"] == "long"
        assert d["state"] == "planned"
        assert d["confidence"] == 0.85

    def test_is_published(self):
        item = ContentItem("c003", "A", ContentFormat.SHORT, "cat", state=ContentState.PUBLISHED)
        assert item.is_published is True

    def test_not_published(self):
        item = ContentItem("c004", "B", ContentFormat.LONG, "cat", state=ContentState.PLANNED)
        assert item.is_published is False

    def test_can_transition_to_valid(self):
        item = ContentItem("c005", "C", ContentFormat.SHORT, "cat", state=ContentState.PLANNED)
        assert item.can_transition_to(ContentState.RESEARCHING) is True

    def test_can_transition_to_invalid(self):
        item = ContentItem("c006", "D", ContentFormat.LONG, "cat", state=ContentState.PLANNED)
        assert item.can_transition_to(ContentState.PUBLISHED) is False

    def test_planned_cannot_transition_to_planned(self):
        item = ContentItem("c007", "E", ContentFormat.SHORT, "cat", state=ContentState.PLANNED)
        assert item.can_transition_to(ContentState.PLANNED) is False

    def test_full_construction(self):
        item = ContentItem(
            content_id="c008",
            topic="Full test",
            format=ContentFormat.LONG,
            category="education",
            state=ContentState.REVIEWING,
            priority=8,
            confidence=0.9,
            opportunity_score=95.0,
            estimated_publish_at="2026-07-10T12:00:00",
            workflow_id="wf_001",
            pipeline_id="pipe_001",
            video_id="vid_001",
            playlist_ids=["pl_001", "pl_002"],
            series_id="series_a",
            asset_requirements=["voiceover", "b-roll"],
        )
        d = item.to_dict()
        assert d["workflow_id"] == "wf_001"
        assert d["pipeline_id"] == "pipe_001"
        assert len(d["playlist_ids"]) == 2
        assert "voiceover" in d["asset_requirements"]

    def test_from_dict_roundtrip(self):
        item = ContentItem(
            content_id="c009",
            topic="Roundtrip",
            format=ContentFormat.SHORT,
            category="news",
            state=ContentState.WRITING,
        )
        d = item.to_dict()
        restored = ContentItem.from_dict(d)
        assert restored.content_id == "c009"
        assert restored.state == ContentState.WRITING
        assert restored.format == ContentFormat.SHORT

    def test_is_published_analyzing(self):
        item = ContentItem("c010", "X", ContentFormat.LONG, "cat", state=ContentState.ANALYZING)
        assert item.is_published is True


class TestCalendarEntry:
    def test_create_entry(self):
        entry = CalendarEntry(
            topic="Test",
            format=ContentFormat.SHORT,
            priority=5,
            publish_time="2026-07-04T14:00:00",
            estimated_confidence=0.8,
            estimated_opportunity=65.0,
            content_id="c001",
        )
        assert entry.topic == "Test"
        assert entry.content_id == "c001"

    def test_to_dict(self):
        entry = CalendarEntry(
            topic="Test",
            format=ContentFormat.LONG,
            priority=5,
            publish_time="2026-07-05T10:00:00",
            estimated_confidence=0.75,
            estimated_opportunity=50.0,
        )
        d = entry.to_dict()
        assert d["format"] == "long"
        assert d["publish_time"] == "2026-07-05T10:00:00"


class TestGovernanceRule:
    def test_create_rule(self):
        rule = GovernanceRule(
            rule_id="rule_001",
            rule_type=GovernanceRuleType.MAX_DAILY_UPLOADS,
            name="Max Daily Uploads",
            enabled=True,
            config={"max": 2},
        )
        assert rule.rule_id == "rule_001"
        assert rule.enabled is True
        assert rule.config["max"] == 2

    def test_to_dict(self):
        rule = GovernanceRule(
            rule_id="rule_002",
            rule_type=GovernanceRuleType.MIN_SPACING_HOURS,
            name="Min Spacing Hours",
            enabled=True,
            config={"hours": 24},
        )
        d = rule.to_dict()
        assert d["rule_type"] == "min_spacing_hours"
        assert d["config"]["hours"] == 24

    def test_disabled_rule(self):
        rule = GovernanceRule(
            rule_id="rule_003",
            rule_type=GovernanceRuleType.MANUAL_LOCK,
            name="Manual Lock",
            enabled=False,
        )
        assert rule.enabled is False

    def test_from_dict(self):
        d = {
            "rule_id": "rule_004",
            "rule_type": "max_daily_uploads",
            "name": "Max Daily Uploads",
            "enabled": True,
            "config": {"max": 3},
        }
        rule = GovernanceRule.from_dict(d)
        assert rule.rule_id == "rule_004"
        assert rule.rule_type == GovernanceRuleType.MAX_DAILY_UPLOADS
        assert rule.config["max"] == 3


class TestGovernanceResult:
    def test_allowed(self):
        result = GovernanceResult(allowed=True)
        assert result.allowed is True

    def test_blocked(self):
        result = GovernanceResult(allowed=False, reason="Max daily uploads exceeded")
        assert result.allowed is False
        assert "Max daily uploads" in result.reason


class TestChannelReport:
    def test_create_report(self):
        report = ChannelReport(
            status="operational",
            active_content=5,
            published_today=2,
            scheduled_count=3,
            health_score=8.5,
            total_items=20,
            state_breakdown={"planned": 5, "published": 10},
            recent_items=[],
            calendar_7day=7,
            calendar_30day=30,
            calendar_90day=90,
            governance_rules_active=5,
            format_balance={"short": 10, "long": 10},
        )
        assert report.status == "operational"
        assert report.active_content == 5
        assert report.governance_rules_active == 5
