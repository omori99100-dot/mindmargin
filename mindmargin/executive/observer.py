import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PlatformSnapshot:
    timestamp: str = ""
    channel_health: float = 10.0
    active_content: int = 0
    scheduled_count: int = 0
    published_today: int = 0
    pending_workflows: int = 0
    running_workflows: int = 0
    failed_workflows: int = 0
    pending_queue: int = 0
    running_queue: int = 0
    failed_queue: int = 0
    scheduler_active: int = 0
    scheduler_paused: int = 0
    experiments_active: int = 0
    experiments_completed: int = 0
    avg_provider_health: float = 1.0
    providers_status: dict = field(default_factory=dict)
    analytics_summary: dict = field(default_factory=dict)
    opportunities_count: int = 0
    top_opportunity: str = ""
    drift_status: str = ""
    problems: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Observer:
    def observe_channel(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.channel.manager import ChannelManager
            mgr = ChannelManager()
            report = mgr.get_status()
            snapshot.channel_health = report.health_score
            snapshot.active_content = report.active_content
            snapshot.scheduled_count = report.scheduled_count
            snapshot.published_today = report.published_today
        except Exception as e:
            logger.warning("Channel observation failed: %s", e)
        return snapshot

    def observe_workflows(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.core.workflows import WorkflowEngine
            engine = WorkflowEngine()
            all_wf = engine.list_all()
            states = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
            for wf in all_wf:
                if isinstance(wf, dict):
                    s = wf.get("state", "")
                else:
                    s = wf.state.value if hasattr(wf.state, 'value') else str(wf.state)
                if s in states:
                    states[s] += 1
            snapshot.pending_workflows = states["pending"]
            snapshot.running_workflows = states["running"]
            snapshot.failed_workflows = states["failed"]
        except Exception as e:
            logger.warning("Workflow observation failed: %s", e)
        return snapshot

    def observe_queue(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.core.queue import Queue
            q = Queue()
            stats = q.stats()
            snapshot.pending_queue = stats.get("pending", 0)
            snapshot.running_queue = stats.get("running", 0)
            snapshot.failed_queue = stats.get("dlq", 0)
        except Exception as e:
            logger.warning("Queue observation failed: %s", e)
        return snapshot

    def observe_scheduler(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.core.scheduler import Scheduler
            sched = Scheduler()
            schedules = sched.list_all()
            for s in schedules:
                if isinstance(s, dict):
                    state_val = s.get("state", "")
                else:
                    state_val = s.state.value if hasattr(s.state, 'value') else str(s.state)
                if state_val == "active":
                    snapshot.scheduler_active += 1
                elif state_val == "paused":
                    snapshot.scheduler_paused += 1
        except Exception as e:
            logger.warning("Scheduler observation failed: %s", e)
        return snapshot

    def observe_experiments(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.analytics.memory import get_active_ab_tests
            active = get_active_ab_tests()
            snapshot.experiments_active = len(active)
        except Exception as e:
            logger.warning("Experiments observation failed: %s", e)
        return snapshot

    def observe_analytics(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.analytics.memory import get_pipeline_stats
            stats = get_pipeline_stats()
            snapshot.analytics_summary = {
                "total_pipelines": stats.get("total_pipelines", 0),
                "published_videos": stats.get("published_videos", 0),
                "total_views": stats.get("total_views", 0),
                "total_likes": stats.get("total_likes", 0),
            }
        except Exception as e:
            logger.warning("Analytics observation failed: %s", e)
        return snapshot

    def observe_opportunities(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.analytics.memory import get_top_opportunities
            opps = get_top_opportunities(n=10)
            snapshot.opportunities_count = len(opps)
            if opps:
                snapshot.top_opportunity = opps[0].get("topic", "")
        except Exception as e:
            logger.warning("Opportunities observation failed: %s", e)
        return snapshot

    def observe_providers(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        try:
            from mindmargin.integrations.manager import ProviderManager
            pm = ProviderManager()
            providers = pm.list_providers()
            healthy = 0
            for name in providers:
                try:
                    is_ok = pm.health_check(name)
                    snapshot.providers_status[name] = "healthy" if is_ok else "unhealthy"
                    if is_ok:
                        healthy += 1
                except Exception:
                    snapshot.providers_status[name] = "error"
            snapshot.avg_provider_health = healthy / max(len(providers), 1)
        except Exception as e:
            logger.warning("Provider observation failed: %s", e)
        return snapshot

    def observe_all(self) -> PlatformSnapshot:
        snapshot = PlatformSnapshot(timestamp=datetime.now(timezone.utc).isoformat())
        snapshot = self.observe_channel(snapshot)
        snapshot = self.observe_workflows(snapshot)
        snapshot = self.observe_queue(snapshot)
        snapshot = self.observe_scheduler(snapshot)
        snapshot = self.observe_experiments(snapshot)
        snapshot = self.observe_analytics(snapshot)
        snapshot = self.observe_opportunities(snapshot)
        snapshot = self.observe_providers(snapshot)
        snapshot = self._detect_problems(snapshot)
        snapshot = self._detect_opportunities(snapshot)
        return snapshot

    def _detect_problems(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        if snapshot.channel_health < 5.0:
            snapshot.problems.append(f"Channel health critical: {snapshot.channel_health:.1f}/10")
        if snapshot.failed_workflows > 3:
            snapshot.problems.append(f"High workflow failures: {snapshot.failed_workflows}")
        if snapshot.failed_queue > 5:
            snapshot.problems.append(f"Queue dead letters piling up: {snapshot.failed_queue}")
        if snapshot.avg_provider_health < 0.5:
            snapshot.problems.append(f"Provider health degraded: {snapshot.avg_provider_health:.0%}")
        if snapshot.published_today == 0 and snapshot.active_content > 0:
            snapshot.problems.append("Content queued but nothing published today")
        return snapshot

    def _detect_opportunities(self, snapshot: PlatformSnapshot) -> PlatformSnapshot:
        if snapshot.opportunities_count > 5:
            snapshot.opportunities.append(f"Rich opportunity pool: {snapshot.opportunities_count} topics")
        if snapshot.channel_health >= 8.0:
            snapshot.opportunities.append(f"Strong channel health ({snapshot.channel_health:.1f}) — safe to publish")
        if snapshot.experiments_active == 0:
            snapshot.opportunities.append("No active experiments — run A/B test cycle")
        if snapshot.scheduled_count == 0 and snapshot.active_content > 2:
            snapshot.opportunities.append("Content ready but nothing scheduled")
        return snapshot
