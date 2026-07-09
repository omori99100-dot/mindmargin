import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

COST_PER_1K_TOKENS = {
    "ollama": {"input": 0.0, "output": 0.0},
    "openai/gpt-4o": {"input": 0.0025, "output": 0.01},
    "openai/gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "openai/gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "anthropic/claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "anthropic/claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
    "anthropic/claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    "gemini/gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    "gemini/gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
    "gemini/gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
}

FALLBACK_COST = {"input": 0.001, "output": 0.002}


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def compute_cost(provider_model: str, input_tokens: int, output_tokens: int) -> float:
    rates = COST_PER_1K_TOKENS.get(provider_model)
    if rates is None:
        prefix = provider_model.split("/")[0]
        rates = COST_PER_1K_TOKENS.get(prefix, FALLBACK_COST)
    return (input_tokens / 1000) * rates["input"] + (output_tokens / 1000) * rates["output"]


@dataclass
class CallRecord:
    provider: str
    model: str
    task: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost: float
    success: bool
    cached: bool = False


class UsageTracker:
    def __init__(self):
        self._records: list[CallRecord] = []

    def record(self, provider: str, model: str, task: str,
               input_tokens: int, output_tokens: int,
               latency_ms: float, success: bool = True,
               cached: bool = False):
        cost = compute_cost(f"{provider}/{model}", input_tokens, output_tokens)
        rec = CallRecord(
            provider=provider, model=model, task=task,
            input_tokens=input_tokens, output_tokens=output_tokens,
            latency_ms=latency_ms, cost=cost, success=success, cached=cached,
        )
        self._records.append(rec)
        logger.debug(
            "LLM call | provider=%s model=%s task=%s "
            "in_tok=%d out_tok=%d latency=%.0fms cost=%.6f success=%s",
            provider, model, task, input_tokens, output_tokens,
            latency_ms, cost, success,
        )

    def summary(self) -> dict:
        if not self._records:
            return {"total_calls": 0, "total_cost": 0.0, "total_tokens": 0}
        total_cost = sum(r.cost for r in self._records)
        total_tokens = sum(r.input_tokens + r.output_tokens for r in self._records)
        total_latency = sum(r.latency_ms for r in self._records)
        successes = sum(1 for r in self._records if r.success)
        by_provider: dict[str, dict] = {}
        for r in self._records:
            p = by_provider.setdefault(r.provider, {"calls": 0, "cost": 0.0, "tokens": 0, "latency_ms": 0.0})
            p["calls"] += 1
            p["cost"] += r.cost
            p["tokens"] += r.input_tokens + r.output_tokens
            p["latency_ms"] += r.latency_ms
        return {
            "total_calls": len(self._records),
            "total_cost": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_latency_ms": round(total_latency, 1),
            "avg_latency_ms": round(total_latency / len(self._records), 1) if self._records else 0,
            "successes": successes,
            "failures": len(self._records) - successes,
            "by_provider": by_provider,
        }

    def by_task(self, task: str) -> list[CallRecord]:
        return [r for r in self._records if r.task == task]

    def reset(self):
        self._records.clear()


_global_tracker = UsageTracker()


def get_tracker() -> UsageTracker:
    return _global_tracker
