import logging
from typing import Callable, Optional

from mindmargin.core.workflows import WorkflowEngine

logger = logging.getLogger(__name__)


class OperationsOrchestrator:
    def __init__(self, engine: WorkflowEngine):
        self._engine = engine
        self._workflow_ids: dict[str, str] = {}

    @property
    def workflow_ids(self) -> dict[str, str]:
        return dict(self._workflow_ids)

    def _make_handler(self, job_func: Callable[[], dict], timeout_s: float = 300) -> Callable:
        def _handler(metadata: dict) -> dict:
            try:
                result = job_func()
                return result if isinstance(result, dict) else {"result": result}
            except Exception as e:
                logger.error("Operation handler failed: %s", e)
                raise
        return _handler

    def build_analytics_workflow(self, name: str = "daily_analytics") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_analytics", "name": "Daily Analytics Job", "max_retries": 2, "timeout_s": 1200},
        ])
        from mindmargin.jobs.daily_analytics import run_daily_job
        self._engine.register_step_handler(wid, "run_analytics", self._make_handler(run_daily_job, 1200))
        self._workflow_ids["analytics"] = wid
        return wid

    def build_intelligence_workflow(self, name: str = "daily_intelligence") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_intelligence", "name": "Daily Intelligence Job", "max_retries": 2, "timeout_s": 1800},
        ])
        from mindmargin.jobs.daily_intelligence import run_daily_intelligence_job
        self._engine.register_step_handler(wid, "run_intelligence", self._make_handler(run_daily_intelligence_job, 1800))
        self._workflow_ids["intelligence"] = wid
        return wid

    def build_executor_workflow(self, name: str = "decision_executor") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_executor", "name": "Decision Executor", "max_retries": 2, "timeout_s": 3600},
        ])
        from mindmargin.agents.decision_executor import execute_top_decision
        self._engine.register_step_handler(wid, "run_executor", self._make_handler(lambda: execute_top_decision(), 3600))
        self._workflow_ids["executor"] = wid
        return wid

    def build_feedback_workflow(self, name: str = "feedback_cycle") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_feedback", "name": "Feedback Cycle", "max_retries": 1, "timeout_s": 300},
        ])
        from mindmargin.intelligence.feedback_engine import run_feedback_cycle
        self._engine.register_step_handler(wid, "run_feedback", self._make_handler(run_feedback_cycle, 300))
        self._workflow_ids["feedback"] = wid
        return wid

    def build_experiment_workflow(self, name: str = "experiment_cycle") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_experiments", "name": "Experiment Cycle", "max_retries": 1, "timeout_s": 600},
        ])
        from mindmargin.intelligence.experiments import run_experiment_cycle
        self._engine.register_step_handler(wid, "run_experiments", self._make_handler(run_experiment_cycle, 600))
        self._workflow_ids["experiments"] = wid
        return wid

    def build_knowledge_graph_workflow(self, name: str = "knowledge_graph") -> str:
        wid = self._engine.create(name, [
            {"step_id": "build_graph", "name": "Knowledge Graph", "max_retries": 1, "timeout_s": 600},
        ])
        from mindmargin.intelligence.knowledge_graph import build_knowledge_graph
        self._engine.register_step_handler(wid, "build_graph", self._make_handler(build_knowledge_graph, 600))
        self._workflow_ids["knowledge_graph"] = wid
        return wid

    def build_forecast_workflow(self, name: str = "forecast") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_forecast", "name": "Forecast", "max_retries": 1, "timeout_s": 300},
        ])
        from mindmargin.intelligence.horizon import forecast_all
        self._engine.register_step_handler(wid, "run_forecast", self._make_handler(forecast_all, 300))
        self._workflow_ids["forecast"] = wid
        return wid

    def build_weekly_plan_workflow(self, name: str = "weekly_plan") -> str:
        wid = self._engine.create(name, [
            {"step_id": "plan_week", "name": "Weekly Plan", "max_retries": 1, "timeout_s": 300},
        ])
        from mindmargin.intelligence.planner import plan_week
        self._engine.register_step_handler(wid, "plan_week", self._make_handler(plan_week, 300))
        self._workflow_ids["weekly_plan"] = wid
        return wid

    def build_selection_workflow(self, name: str = "selection_pressure") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_selection", "name": "Selection Pressure", "max_retries": 1, "timeout_s": 600},
        ])
        from mindmargin.analytics.selection import run_selection_cycle
        self._engine.register_step_handler(wid, "run_selection", self._make_handler(lambda: run_selection_cycle(), 600))
        self._workflow_ids["selection"] = wid
        return wid

    def build_ab_rotation_workflow(self, name: str = "ab_rotation") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_ab", "name": "A/B Rotation", "max_retries": 1, "timeout_s": 300},
        ])
        from mindmargin.analytics.ab_testing import run_ab_rotation_cycle
        self._engine.register_step_handler(wid, "run_ab", self._make_handler(lambda: run_ab_rotation_cycle(dry_run=False), 300))
        self._workflow_ids["ab_rotation"] = wid
        return wid

    def build_distribution_workflow(self, name: str = "distribution") -> str:
        wid = self._engine.create(name, [
            {"step_id": "run_distribution", "name": "Distribution Agent", "max_retries": 1, "timeout_s": 600},
        ])
        from mindmargin.agents.distribution import DistributionAgent
        agent = DistributionAgent()
        self._engine.register_step_handler(wid, "run_distribution", self._make_handler(agent.run_all, 600))
        self._workflow_ids["distribution"] = wid
        return wid

    def register_all(self) -> dict[str, str]:
        self.build_analytics_workflow()
        self.build_intelligence_workflow()
        self.build_executor_workflow()
        self.build_feedback_workflow()
        self.build_experiment_workflow()
        self.build_knowledge_graph_workflow()
        self.build_forecast_workflow()
        self.build_weekly_plan_workflow()
        self.build_selection_workflow()
        self.build_ab_rotation_workflow()
        self.build_distribution_workflow()
        return self._workflow_ids


def register_operations(engine: WorkflowEngine) -> OperationsOrchestrator:
    orchestrator = OperationsOrchestrator(engine)
    orchestrator.register_all()
    return orchestrator
