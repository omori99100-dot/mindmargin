import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional

from mindmargin.executive.brain import Brain
from mindmargin.executive.executor import ExecutiveExecutor
from mindmargin.executive.memory import ExecutiveMemory
from mindmargin.executive.observer import PlatformSnapshot
from mindmargin.executive.planner import ActionPlan, Planner
from mindmargin.executive.policy import PolicyEngine, PolicyType

logger = logging.getLogger(__name__)

DEFAULT_LOOP_INTERVAL_S = 300
SLEEP_INTERVAL_S = 30


class ExecutiveAgent:
    def __init__(self, policy_type: Optional[PolicyType] = None,
                 loop_interval_s: int = DEFAULT_LOOP_INTERVAL_S):
        self._memory = ExecutiveMemory()
        self._policy_engine = PolicyEngine()
        if policy_type:
            self._policy_engine.set_policy(policy_type)
        self._brain = Brain(memory=self._memory, policy_engine=self._policy_engine)
        self._executor = ExecutiveExecutor()
        self._planner = Planner()
        self._loop_interval_s = loop_interval_s
        self._running = False
        self._cycle_count = 0
        self._last_snapshot: Optional[PlatformSnapshot] = None
        self._last_plan: Optional[ActionPlan] = None
        self._last_decision = None
        self._thread: Optional[threading.Thread] = None

    @property
    def memory(self) -> ExecutiveMemory:
        return self._memory

    @property
    def brain(self) -> Brain:
        return self._brain

    @property
    def executor(self) -> ExecutiveExecutor:
        return self._executor

    @property
    def policy_engine(self) -> PolicyEngine:
        return self._policy_engine

    def run_once(self) -> dict:
        self._cycle_count += 1
        cycle_start = datetime.now(timezone.utc).isoformat()
        logger.info("Executive cycle %d starting", self._cycle_count)

        snapshot, plan, decision = self._brain.think()
        self._last_snapshot = snapshot
        self._last_plan = plan
        self._last_decision = decision

        executed = []
        if decision:
            action = self._planner.pick_top_action(plan)
            if action:
                result = self._executor.execute(action)
                executed.append(result.to_dict())
                self._brain.record_outcome(
                    action.action_type.value,
                    result.status == "completed",
                    result.result,
                )

        # Execute medium/low priority actions if critical cleared
        for action in plan.actions[1:3]:
            if action.priority.value in ("medium", "low"):
                result = self._executor.execute(action)
                executed.append(result.to_dict())
                self._brain.record_outcome(
                    action.action_type.value,
                    result.status == "completed",
                    result.result,
                )

        cycle_end = datetime.now(timezone.utc).isoformat()

        return {
            "status": "completed",
            "cycle": self._cycle_count,
            "started_at": cycle_start,
            "completed_at": cycle_end,
            "problems": snapshot.problems,
            "opportunities": snapshot.opportunities,
            "decision": decision.to_dict() if decision else None,
            "actions_executed": executed,
            "total_actions": len(plan.actions),
        }

    def start_loop(self):
        if self._running:
            logger.warning("Executive loop already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="executive-loop")
        self._thread.start()
        logger.info("Executive loop started (interval=%ds)", self._loop_interval_s)

    def stop_loop(self, timeout_s: float = 10.0):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_s)
        logger.info("Executive loop stopped")

    def _loop(self):
        while self._running:
            try:
                self.run_once()
            except Exception as e:
                logger.error("Executive cycle failed: %s", e)
            for _ in range(self._loop_interval_s):
                if not self._running:
                    break
                time.sleep(min(SLEEP_INTERVAL_S, self._loop_interval_s))

    def get_status(self) -> dict:
        config = self._policy_engine.get_config()
        memory_stats = self._memory.to_dict()
        history = self._executor.get_history(limit=10)
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "policy": config.policy_type.value,
            "policy_config": config.to_dict(),
            "memory": memory_stats,
            "last_snapshot": self._last_snapshot.to_dict() if self._last_snapshot else None,
            "last_plan": self._last_plan.to_dict() if self._last_plan else None,
            "last_decision": self._last_decision.to_dict() if self._last_decision else None,
            "recent_executions": [e.to_dict() for e in history],
        }

    def get_plan(self) -> dict:
        if self._last_plan:
            return self._last_plan.to_dict()
        return {"actions": [], "snapshot_summary": "No plan generated yet", "generated_at": ""}

    def get_history(self, limit: int = 50) -> list[dict]:
        return [e.to_dict() for e in self._executor.get_history(limit=limit)]

    def get_memory(self) -> dict:
        return self._memory.to_dict()

    def get_policy(self) -> dict:
        config = self._policy_engine.get_config()
        return config.to_dict()

    def set_policy(self, policy_type: str) -> dict:
        pt = PolicyType(policy_type)
        config = self._policy_engine.set_policy(pt)
        return {"status": "ok", "policy": config.to_dict()}
