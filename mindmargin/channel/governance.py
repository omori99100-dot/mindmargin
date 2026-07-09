import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from mindmargin.analytics.memory import get_execution_log, get_pipeline_history, is_successful_publish
from mindmargin.channel.models import (
    GovernanceResult,
    GovernanceRule,
    GovernanceRuleType,
    ContentItem,
)
from mindmargin.config import settings

logger = logging.getLogger(__name__)

GOVERNANCE_RULE_DEFAULTS: dict[GovernanceRuleType, dict] = {
    GovernanceRuleType.MAX_DAILY_UPLOADS: {"max": 2},
    GovernanceRuleType.MIN_SPACING_HOURS: {"hours": 24},
    GovernanceRuleType.AVOID_SIMILAR_TITLES: {"threshold": 0.7},
    GovernanceRuleType.AVOID_REPEATED_KEYWORDS: {"keywords": []},
    GovernanceRuleType.EXPERIMENT_COOLDOWN: {"days": 7},
    GovernanceRuleType.CHANNEL_HEALTH_MIN: {"min_score": 4.0},
    GovernanceRuleType.MAX_SHORTS_PERCENT: {"max_pct": 40},
    GovernanceRuleType.MIN_CATEGORY_ROTATION: {"min_categories": 3},
}


class GovernanceEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._rules_dir = root / "channel" / "governance"
        self._rules_dir.mkdir(parents=True, exist_ok=True)
        self._rules: dict[str, GovernanceRule] = {}
        self._load_rules()

    def _rules_path(self) -> Path:
        return self._rules_dir / "rules.json"

    def _load_rules(self):
        p = self._rules_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for d in data:
                    rule = GovernanceRule.from_dict(d)
                    self._rules[rule.rule_id] = rule
            except Exception as e:
                logger.warning("Failed to load governance rules: %s", e)
        if not self._rules:
            self._seed_defaults()

    def _save_rules(self):
        self._rules_path().write_text(
            json.dumps([r.to_dict() for r in self._rules.values()], indent=2),
            encoding="utf-8",
        )

    def _seed_defaults(self):
        for rtype, config in GOVERNANCE_RULE_DEFAULTS.items():
            rule = GovernanceRule(
                rule_id=f"rule_{rtype.value}",
                rule_type=rtype,
                name=rtype.value.replace("_", " ").title(),
                enabled=True,
                config=dict(config),
                description=f"Built-in rule: {rtype.value}",
            )
            self._rules[rule.rule_id] = rule
        self._save_rules()

    def get_rules(self) -> list[GovernanceRule]:
        return list(self._rules.values())

    def get_rule(self, rule_id: str) -> Optional[GovernanceRule]:
        return self._rules.get(rule_id)

    def add_rule(self, rule: GovernanceRule):
        self._rules[rule.rule_id] = rule
        self._save_rules()

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._save_rules()
            return True
        return False

    def toggle_rule(self, rule_id: str) -> Optional[bool]:
        rule = self._rules.get(rule_id)
        if not rule:
            return None
        rule.enabled = not rule.enabled
        self._save_rules()
        return rule.enabled

    def evaluate(self, item: ContentItem) -> GovernanceResult:
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            result = self._check_rule(rule, item)
            if not result.allowed:
                return result
        return GovernanceResult(allowed=True)

    def evaluate_many(self, items: list[ContentItem]) -> list[ContentItem]:
        allowed = []
        for item in items:
            result = self.evaluate(item)
            if result.allowed:
                allowed.append(item)
            else:
                logger.info("Governance blocked '%s': %s", item.topic, result.reason)
        return allowed

    def evaluate_calendar_entry(self, topic: str, fmt: str) -> GovernanceResult:
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            result = self._check_calendar_rule(rule, topic, fmt)
            if not result.allowed:
                return result
        return GovernanceResult(allowed=True)

    def _check_rule(self, rule: GovernanceRule, item: ContentItem) -> GovernanceResult:
        rtype = rule.rule_type
        if rtype == GovernanceRuleType.CHANNEL_HEALTH_MIN:
            return self._check_channel_health(rule)
        if rtype == GovernanceRuleType.EXPERIMENT_COOLDOWN:
            return self._check_experiment_cooldown(rule, item)
        return GovernanceResult(allowed=True)

    def _check_calendar_rule(self, rule: GovernanceRule, topic: str, fmt: str) -> GovernanceResult:
        rtype = rule.rule_type
        if rtype == GovernanceRuleType.MAX_DAILY_UPLOADS:
            return self._check_max_daily(rule)
        if rtype == GovernanceRuleType.MIN_SPACING_HOURS:
            return self._check_min_spacing(rule)
        if rtype == GovernanceRuleType.AVOID_SIMILAR_TITLES:
            return self._check_similar_titles(rule, topic)
        if rtype == GovernanceRuleType.AVOID_REPEATED_KEYWORDS:
            return self._check_repeated_keywords(rule, topic)
        if rtype == GovernanceRuleType.MAX_SHORTS_PERCENT:
            return self._check_shorts_percent(rule, fmt)
        if rtype == GovernanceRuleType.CHANNEL_HEALTH_MIN:
            return self._check_channel_health(rule)
        if rtype == GovernanceRuleType.EXPERIMENT_COOLDOWN:
            return self._check_experiment_cooldown_topic(rule)
        return GovernanceResult(allowed=True)

    def _check_max_daily(self, rule: GovernanceRule) -> GovernanceResult:
        max_uploads = rule.config.get("max", 2)
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            count = 0
            for log in get_execution_log(100):
                if log.get("executed_at", "").startswith(today) and is_successful_publish(log):
                    count += 1
            if count >= max_uploads:
                return GovernanceResult(
                    allowed=False, rule_id=rule.rule_id,
                    rule_name=rule.name,
                    reason=f"Max daily uploads ({max_uploads}) reached ({count} today)",
                    details={"count": count, "max": max_uploads},
                )
        except Exception as e:
            logger.warning("Max daily check failed: %s", e)
        return GovernanceResult(allowed=True)

    def _check_min_spacing(self, rule: GovernanceRule) -> GovernanceResult:
        min_hours = rule.config.get("hours", 24)
        try:
            logs = get_execution_log(5)
            if logs:
                last_time = logs[0].get("executed_at", "")
                if last_time:
                    last_dt = datetime.fromisoformat(last_time)
                    elapsed = datetime.now(timezone.utc) - last_dt
                    if elapsed.total_seconds() < min_hours * 3600:
                        remaining = int(min_hours * 3600 - elapsed.total_seconds())
                        return GovernanceResult(
                            allowed=False, rule_id=rule.rule_id,
                            rule_name=rule.name,
                            reason=f"Last publish was {int(elapsed.total_seconds() / 3600)}h ago, need {min_hours}h spacing",
                            details={"elapsed_hours": round(elapsed.total_seconds() / 3600, 1), "min_hours": min_hours},
                        )
        except Exception as e:
            logger.warning("Min spacing check failed: %s", e)
        return GovernanceResult(allowed=True)

    def _check_similar_titles(self, rule: GovernanceRule, topic: str) -> GovernanceResult:
        threshold = rule.config.get("threshold", 0.7)
        lower = topic.lower()
        try:
            for pipe in get_pipeline_history(50):
                existing = (pipe.get("topic") or "").lower()
                if existing and self._text_similarity(lower, existing) >= threshold:
                    return GovernanceResult(
                        allowed=False, rule_id=rule.rule_id,
                        rule_name=rule.name,
                        reason=f"Similar to existing: '{pipe.get('topic')}'",
                        details={"existing": pipe.get("topic"), "new": topic},
                    )
        except Exception as e:
            logger.warning("Similar titles check failed: %s", e)
        return GovernanceResult(allowed=True)

    def _check_repeated_keywords(self, rule: GovernanceRule, topic: str) -> GovernanceResult:
        blocked_keywords = rule.config.get("keywords", [])
        lower = topic.lower()
        for kw in blocked_keywords:
            if kw.lower() in lower:
                return GovernanceResult(
                    allowed=False, rule_id=rule.rule_id,
                    rule_name=rule.name,
                    reason=f"Contains blocked keyword: '{kw}'",
                    details={"keyword": kw, "topic": topic},
                )
        try:
            for pipe in get_pipeline_history(50):
                existing = (pipe.get("topic") or "").lower()
                if existing and self._keyword_overlap(lower, existing) > 0.5:
                    return GovernanceResult(
                        allowed=False, rule_id=rule.rule_id,
                        rule_name=rule.name,
                        reason=f"High keyword overlap with '{pipe.get('topic')}'",
                        details={"existing": pipe.get("topic"), "overlap": self._keyword_overlap(lower, existing)},
                    )
        except Exception as e:
            logger.warning("Repeated keywords check failed: %s", e)
        return GovernanceResult(allowed=True)

    def _check_shorts_percent(self, rule: GovernanceRule, fmt: str) -> GovernanceResult:
        max_pct = rule.config.get("max_pct", 40)
        if fmt != "short":
            return GovernanceResult(allowed=True)
        try:
            from mindmargin.channel.lifecycle import ContentLifecycle
            lc = ContentLifecycle()
            all_items = lc.list_all()
            active = [i for i in all_items if i.state.value not in ("archived",)]
            if active:
                shorts = sum(1 for i in active if i.format.value == "short")
                pct = shorts / len(active) * 100
                if pct >= max_pct:
                    return GovernanceResult(
                        allowed=False, rule_id=rule.rule_id,
                        rule_name=rule.name,
                        reason=f"Shorts {pct:.0f}% exceeds max {max_pct}%",
                        details={"current_pct": round(pct, 1), "max_pct": max_pct},
                    )
        except Exception as e:
            logger.warning("Shorts percent check failed: %s", e)
        return GovernanceResult(allowed=True)

    def _check_channel_health(self, rule: GovernanceRule) -> GovernanceResult:
        min_score = rule.config.get("min_score", 4.0)
        try:
            from mindmargin.analytics.channel_brain import assess_channel_health
            health = assess_channel_health()
            score = health.get("overall_score", 10)
            if score < min_score:
                return GovernanceResult(
                    allowed=False, rule_id=rule.rule_id,
                    rule_name=rule.name,
                    reason=f"Channel health {score:.1f} below minimum {min_score}",
                    details={"score": score, "min_score": min_score, "health": health},
                )
        except Exception as e:
            logger.warning("Channel health check failed: %s", e)
        return GovernanceResult(allowed=True)

    def _check_experiment_cooldown(self, rule: GovernanceRule, item: ContentItem) -> GovernanceResult:
        days = rule.config.get("days", 7)
        try:
            from mindmargin.analytics.memory import _get_db
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = _get_db()
            rows = conn.execute(
                "SELECT COUNT(*) as cnt FROM execution_log "
                "WHERE topic = ? AND executed_at >= ? AND pipeline_status != 'completed'",
                (item.topic, cutoff),
            ).fetchone()
            if rows and rows["cnt"] > 0:
                return GovernanceResult(
                    allowed=False, rule_id=rule.rule_id,
                    rule_name=rule.name,
                    reason=f"Experiment cooldown active for '{item.topic}' ({days}d)",
                    details={"topic": item.topic, "cooldown_days": days},
                )
        except Exception as e:
            logger.warning("Experiment cooldown check failed: %s", e)
        return GovernanceResult(allowed=True)

    def _check_experiment_cooldown_topic(self, rule: GovernanceRule) -> GovernanceResult:
        return GovernanceResult(allowed=True)

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    @staticmethod
    def _keyword_overlap(a: str, b: str) -> float:
        return GovernanceEngine._text_similarity(a, b)
