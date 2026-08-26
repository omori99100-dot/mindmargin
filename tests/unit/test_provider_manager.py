"""Tests for ProviderManager â€” registration, routing, failover, health checks."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def _reset_tracker():
    from mindmargin.integrations.tracking import get_tracker
    get_tracker().reset()


class TestProviderManagerRegistration:
    def test_register_and_get(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        prov = OllamaProvider(model="test-model")
        mgr.register("test", prov)
        assert mgr.get("test") is prov

    def test_get_unknown_raises(self):
        from mindmargin.integrations.manager import ProviderManager

        mgr = ProviderManager()
        with pytest.raises(ValueError, match="not registered"):
            mgr.get("nonexistent")

    def test_available(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        mgr.register("ollama", OllamaProvider())
        assert "ollama" in mgr.available

    def test_set_default(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        p1 = OllamaProvider(model="model-a")
        p2 = OllamaProvider(model="model-b")
        mgr.register("a", p1)
        mgr.register("b", p2)
        mgr.set_default("b")
        assert mgr.get() is p2

    def test_set_default_unknown_raises(self):
        from mindmargin.integrations.manager import ProviderManager

        mgr = ProviderManager()
        with pytest.raises(ValueError):
            mgr.set_default("nonexistent")


class TestProviderManagerRouting:
    def test_default_policy(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        mgr.register("ollama", OllamaProvider(model="default-model"))
        selected = mgr.get()
        assert selected.model_name == "default-model"

    def test_set_policy_valid(self):
        from mindmargin.integrations.manager import ProviderManager

        mgr = ProviderManager()
        mgr.set_policy("fastest")
        assert mgr.get_policy() == "fastest"

    def test_set_policy_invalid(self):
        from mindmargin.integrations.manager import ProviderManager

        mgr = ProviderManager()
        with pytest.raises(ValueError):
            mgr.set_policy("nonexistent")

    @pytest.mark.anyio
    async def test_select_with_prefer(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        p1 = OllamaProvider(model="model-a")
        p2 = OllamaProvider(model="model-b")
        mgr.register("a", p1)
        mgr.register("b", p2)
        selected = await mgr.select(prefer="b")
        assert selected is p2

    @pytest.mark.anyio
    async def test_select_manual_policy(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        p1 = OllamaProvider(model="model-a")
        p2 = OllamaProvider(model="model-b")
        mgr.register("a", p1)
        mgr.register("b", p2)
        mgr.set_default("a")
        mgr.set_policy("manual")
        selected = await mgr.select()
        assert selected is p1


class TestProviderManagerFailover:
    @pytest.mark.anyio
    async def test_with_retry_success(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        provider = OllamaProvider(model="llama3")
        mgr.register("ollama", provider)

        with patch.object(provider, "generate", new=AsyncMock(return_value="ok")):
            result = await mgr.with_retry("ollama", "generate", prompt="hi", task="test")
            assert result == "ok"

    @pytest.mark.anyio
    async def test_with_failover_falls_through(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        p1 = OllamaProvider(model="m1")
        p2 = OllamaProvider(model="m2")
        mgr.register("a", p1)
        mgr.register("b", p2)

        with patch.object(p1, "generate", new=AsyncMock(return_value="")):
            with patch.object(p2, "generate", new=AsyncMock(return_value="ok")):
                name, result = await mgr.with_failover("generate", task="test")
                assert result == "ok"
                assert name == "b"

    @pytest.mark.anyio
    async def test_per_call_failover_recovers_then_uses_primary_next_call(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider
        from mindmargin.integrations.gemini_provider import GeminiProvider

        mgr = ProviderManager()
        gemini = GeminiProvider(api_key="test-key")
        ollama = OllamaProvider(model="fallback")
        mgr.register("gemini", gemini)
        mgr.register("ollama", ollama)
        mgr.set_default("gemini")

        with patch.object(gemini, "generate", new=AsyncMock(side_effect=["", "primary-ok"])):
            with patch.object(ollama, "generate", new=AsyncMock(return_value="fallback-ok")):
                name1, result1 = await mgr.with_failover("generate", prompt="first", task="test")
                name2, result2 = await mgr.with_failover("generate", prompt="second", task="test")
                assert (name1, result1) == ("ollama", "fallback-ok")
                assert (name2, result2) == ("gemini", "primary-ok")


class TestProviderManagerHealth:
    @pytest.mark.anyio
    async def test_health_check_all(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        provider = OllamaProvider(model="llama3")
        mgr.register("ollama", provider)

        with patch.object(provider, "health_check", new=AsyncMock(return_value=True)):
            results = await mgr.health_check()
            assert results == {"ollama": True}

    @pytest.mark.anyio
    async def test_health_check_specific(self):
        from mindmargin.integrations.manager import ProviderManager
        from mindmargin.integrations.ollama_provider import OllamaProvider

        mgr = ProviderManager()
        p1 = OllamaProvider(model="m1")
        p2 = OllamaProvider(model="m2")
        mgr.register("a", p1)
        mgr.register("b", p2)

        with patch.object(p1, "health_check", new=AsyncMock(return_value=True)):
            with patch.object(p2, "health_check", new=AsyncMock(return_value=False)):
                results = await mgr.health_check("a")
                assert results == {"a": True}


class TestCreateDefaultManager:
    def test_creates_ollama_provider(self):
        from mindmargin.integrations.manager import create_default_manager

        mgr = create_default_manager()
        prov = mgr.get()
        assert prov.provider_name == "ollama"

    def test_ollama_is_available(self):
        from mindmargin.integrations.manager import create_default_manager

        mgr = create_default_manager()
        assert "ollama" in mgr.available

    def test_register_builtin_count(self):
        from mindmargin.integrations.manager import create_default_manager
        import os

        # Without API keys, only Ollama should register
        with patch.dict(os.environ, {}, clear=True):
            mgr = create_default_manager()
            assert len(mgr.available) >= 1
            assert mgr.get().provider_name == "ollama"

    def test_gemini_is_default_when_key_present(self):
        from mindmargin.integrations.manager import create_default_manager
        import os

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            mgr = create_default_manager()
            assert "gemini" in mgr.available
            assert mgr.get().provider_name == "gemini"
