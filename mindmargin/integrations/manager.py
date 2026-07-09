import asyncio
import logging
import random
import time
from typing import Any, Optional

from mindmargin.integrations.anthropic_provider import AnthropicProvider
from mindmargin.integrations.gemini_provider import GeminiProvider
from mindmargin.integrations.ollama_provider import OllamaProvider
from mindmargin.integrations.openai_provider import OpenAIProvider
from mindmargin.integrations.provider import LLMProvider
from mindmargin.integrations.tracking import get_tracker

logger = logging.getLogger(__name__)

ROUTING_POLICIES = ("default", "cheapest", "fastest", "highest_quality", "manual")


class ProviderManager:
    def __init__(self, settings=None):
        self._providers: dict[str, LLMProvider] = {}
        self._latency_history: dict[str, list[float]] = {}
        self._policy: str = "default"
        self._default_provider: str = "ollama"
        self._max_retries: int = 2
        self._retry_delay_s: float = 1.0
        if settings is not None:
            self._policy = getattr(settings.llm, "routing_policy", "default")
            self._default_provider = getattr(settings.llm, "default_provider", "ollama")

    # ── Registration ──

    def register(self, name: str, provider: LLMProvider):
        self._providers[name] = provider
        logger.info("Registered LLM provider '%s' (%s/%s)", name, provider.provider_name, provider.model_name)

    def register_builtin(self, settings=None) -> int:
        count = 0
        self.register("ollama", OllamaProvider())
        count += 1
        oa = OpenAIProvider()
        if oa._has_key:
            self.register("openai", oa)
            count += 1
        an = AnthropicProvider()
        if an._has_key:
            self.register("anthropic", an)
            count += 1
        gm = GeminiProvider()
        if gm._has_key:
            self.register("gemini", gm)
            count += 1
        logger.info("Registered %d built-in LLM providers", count)
        return count

    # ── Access ──

    def get(self, name: Optional[str] = None) -> LLMProvider:
        if name:
            prov = self._providers.get(name)
            if not prov:
                raise ValueError(f"Provider '{name}' not registered. Available: {list(self._providers.keys())}")
            return prov
        return self._providers.get(self._default_provider)

    @property
    def available(self) -> list[str]:
        return list(self._providers.keys())

    # ── Routing ──

    def set_policy(self, policy: str):
        if policy not in ROUTING_POLICIES:
            raise ValueError(f"Unknown routing policy '{policy}'. Choose from {ROUTING_POLICIES}")
        self._policy = policy
        logger.info("Routing policy set to '%s'", policy)

    def get_policy(self) -> str:
        return self._policy

    def set_default(self, name: str):
        if name not in self._providers:
            raise ValueError(f"Provider '{name}' not registered")
        self._default_provider = name
        logger.info("Default provider set to '%s'", name)

    async def select(self, task: str = "", prefer: Optional[str] = None) -> LLMProvider:
        if prefer:
            return self.get(prefer)
        policy = self._policy
        if policy == "manual":
            return self.get(self._default_provider)
        if policy == "cheapest":
            return await self._select_cheapest()
        if policy == "fastest":
            return await self._select_fastest()
        if policy == "highest_quality":
            return await self._select_highest_quality()
        return self.get(self._default_provider)

    async def _select_cheapest(self) -> LLMProvider:
        priority = ["ollama", "openai", "gemini", "anthropic"]
        for name in priority:
            if name in self._providers:
                prov = self._providers[name]
                if await prov.health_check():
                    return prov
        return self.get(self._default_provider)

    async def _select_fastest(self) -> LLMProvider:
        best = self.get(self._default_provider)
        best_lat = float("inf")
        for name, prov in self._providers.items():
            history = self._latency_history.get(name, [])
            avg = sum(history) / len(history) if history else float("inf")
            if avg < best_lat:
                best_lat = avg
                best = prov
        return best

    async def _select_highest_quality(self) -> LLMProvider:
        priority = ["anthropic", "openai", "gemini", "ollama"]
        for name in priority:
            if name in self._providers:
                prov = self._providers[name]
                if await prov.health_check():
                    return prov
        return self.get(self._default_provider)

    # ── Execution with retry and failover ──

    async def with_retry(self, provider_name: str, method: str,
                         **kwargs) -> Any:
        provider = self.get(provider_name)
        last_error = None
        for attempt in range(1, self._max_retries + 1):
            try:
                fn = getattr(provider, method, None)
                if fn is None:
                    raise AttributeError(f"Provider '{provider_name}' has no method '{method}'")
                if asyncio.iscoroutinefunction(fn):
                    return await fn(**kwargs)
                return fn(**kwargs)
            except Exception as e:
                last_error = e
                logger.warning("Retry %d/%d for %s.%s: %s",
                               attempt, self._max_retries, provider_name, method, e)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay_s)
        raise last_error  # type: ignore[misc]

    async def with_failover(self, method: str,
                            task: str = "",
                            prefer: Optional[str] = None,
                            **kwargs) -> tuple[str, Any]:
        candidates = []
        if prefer and prefer in self._providers:
            candidates.append(prefer)
        policy_order = [self._default_provider]
        for name in self._providers:
            if name not in policy_order:
                policy_order.append(name)
        for name in policy_order:
            if name not in candidates:
                candidates.append(name)

        last_error = None
        for name in candidates:
            for attempt in range(1, self._max_retries + 1):
                try:
                    provider = self.get(name)
                    fn = getattr(provider, method, None)
                    if fn is None:
                        raise AttributeError(f"Provider '{name}' has no method '{method}'")
                    if asyncio.iscoroutinefunction(fn):
                        result = await fn(**kwargs)
                    else:
                        result = fn(**kwargs)
                    if result is not None and result != "":
                        self._record_latency(name, kwargs)
                        return name, result
                    logger.info("Provider '%s' returned empty, trying next", name)
                    break
                except Exception as e:
                    last_error = e
                    logger.warning("Failover attempt %s/%s: %s", name, attempt, e)
                    await asyncio.sleep(self._retry_delay_s)
        logger.error("All providers failed for %s", method)
        raise last_error or RuntimeError(f"All providers failed for method '{method}'")

    def _record_latency(self, name: str, kwargs: dict):
        pass

    # ── Health ──

    async def health_check(self, name: Optional[str] = None) -> dict[str, bool]:
        results: dict[str, bool] = {}
        targets = {name: self._providers[name]} if name else self._providers
        for n, prov in targets.items():
            try:
                results[n] = await prov.health_check()
            except Exception:
                results[n] = False
        return results

    async def wait_for_healthy(self, name: str, timeout_s: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ok = await self.health_check(name)
            if ok.get(name, False):
                return True
            await asyncio.sleep(0.5)
        return False

    # ── Model capability detection ──

    def supports(self, capability: str, provider_name: Optional[str] = None) -> bool:
        provider = self.get(provider_name)
        model = provider.model_name.lower()
        if capability == "streaming":
            return True
        if capability == "json_mode":
            return "gpt-4" in model or "gpt-3.5" in model or "claude-3" in model or "gemini" in model
        if capability == "vision":
            return "vision" in model or "gpt-4o" in model or "claude-3-5" in model or "gemini-1.5" in model
        if capability == "function_calling":
            return "gpt-4" in model or "gpt-3.5" in model or "claude-3" in model or "gemini" in model
        return False


def create_default_manager(settings=None) -> ProviderManager:
    mgr = ProviderManager(settings)
    mgr.register_builtin(settings)
    return mgr
