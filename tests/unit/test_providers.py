"""Tests for all LLM provider implementations."""

import json
import pytest
from unittest.mock import ANY, AsyncMock, MagicMock, patch


# â”€â”€ Helpers â”€â”€

@pytest.fixture(autouse=True)
def _reset_tracker():
    from mindmargin.integrations.tracking import get_tracker
    get_tracker().reset()


# â”€â”€ OllamaProvider â”€â”€

class TestOllamaProvider:
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_success(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "Hello world"}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(base_url="http://localhost:11434", model="llama3")
        result = await provider.generate("test prompt", task="test")
        assert result == "Hello world"

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_failure_returns_empty(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(base_url="http://localhost:11434", model="llama3")
        result = await provider.generate("test prompt", task="test")
        assert result == ""

    @pytest.mark.anyio
    async def test_generate_stream(self):
        from mindmargin.integrations.ollama_provider import OllamaProvider

        class FakeStreamCtx:
            def raise_for_status(self):
                pass
            async def aiter_lines(self):
                yield '{"response": "Hel", "done": false}'
                yield '{"response": "lo", "done": true}'
            async def __aenter__(self):
                return self
            async def __aexit__(self, *excinfo):
                pass

        class FakeClient:
            @staticmethod
            def stream(*a, **kw):
                return FakeStreamCtx()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *excinfo):
                pass

        import httpx
        orig = httpx.AsyncClient
        httpx.AsyncClient = lambda *a, **kw: FakeClient()
        try:
            provider = OllamaProvider(base_url="http://localhost:11434", model="llama3")
            chunks = []
            async for chunk in provider.generate_stream("hi", task="test"):
                chunks.append(chunk)
            assert chunks == ["Hel", "lo"]
        finally:
            httpx.AsyncClient = orig

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_chat(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "Hi there"}}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(base_url="http://localhost:11434", model="llama3")
        result = await provider.chat([{"role": "user", "content": "hello"}])
        assert result == "Hi there"

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_health_check_ok(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(base_url="http://localhost:11434", model="llama3")
        assert await provider.health_check() is True

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_health_check_fail(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.side_effect = Exception("fail")
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(base_url="http://localhost:11434", model="llama3")
        assert await provider.health_check() is False

    def test_provider_name(self):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        p = OllamaProvider(model="llama3")
        assert p.provider_name == "ollama"

    def test_model_name(self):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        p = OllamaProvider(model="llama3:70b")
        assert p.model_name == "llama3:70b"

    def test_reset_context(self):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        p = OllamaProvider(model="llama3")
        p._conversation = [{"role": "user", "content": "hello"}]
        p.reset_context()
        assert p._conversation == []


# â”€â”€ OpenAIProvider â”€â”€

class TestOpenAIProvider:
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"}, clear=True)
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_success(self, mock_client_class):
        from mindmargin.integrations.openai_provider import OpenAIProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello from OpenAI"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4o-mini")
        result = await provider.generate("test", task="test")
        assert result == "Hello from OpenAI"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"}, clear=True)
    @pytest.mark.anyio
    async def test_generate_stream(self):
        from mindmargin.integrations.openai_provider import OpenAIProvider

        class FakeStreamCtx:
            def raise_for_status(self):
                pass
            async def aiter_lines(self):
                yield 'data: {"choices":[{"delta":{"content":"Hel"}}]}'
                yield 'data: {"choices":[{"delta":{"content":"lo"}}]}'
                yield "data: [DONE]"
            async def __aenter__(self):
                return self
            async def __aexit__(self, *excinfo):
                pass

        class FakeClient:
            @staticmethod
            def stream(*a, **kw):
                return FakeStreamCtx()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *excinfo):
                pass

        import httpx
        orig = httpx.AsyncClient
        httpx.AsyncClient = lambda *a, **kw: FakeClient()
        try:
            provider = OpenAIProvider(model="gpt-4o-mini")
            chunks = []
            async for chunk in provider.generate_stream("hi", task="test"):
                chunks.append(chunk)
            assert chunks == ["Hel", "lo"]
        finally:
            httpx.AsyncClient = orig

    @patch.dict("os.environ", clear=True)
    def test_no_api_key_returns_empty(self):
        from mindmargin.integrations.openai_provider import OpenAIProvider
        provider = OpenAIProvider(model="gpt-4o-mini")
        assert provider._has_key is False

    @patch.dict("os.environ", clear=True)
    @pytest.mark.anyio
    async def test_generate_without_key_returns_empty(self):
        from mindmargin.integrations.openai_provider import OpenAIProvider
        provider = OpenAIProvider(model="gpt-4o-mini")
        result = await provider.generate("test", task="test")
        assert result == ""

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"}, clear=True)
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_health_check(self, mock_client_class):
        from mindmargin.integrations.openai_provider import OpenAIProvider
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4o-mini")
        assert await provider.health_check() is True

    def test_provider_name(self):
        from mindmargin.integrations.openai_provider import OpenAIProvider
        p = OpenAIProvider()
        assert p.provider_name == "openai"


# â”€â”€ AnthropicProvider â”€â”€

class TestAnthropicProvider:
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True)
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_success(self, mock_client_class):
        from mindmargin.integrations.anthropic_provider import AnthropicProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Claude"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = AnthropicProvider(model="claude-3-5-sonnet-20241022")
        result = await provider.generate("test", task="test")
        assert result == "Hello from Claude"

    @patch.dict("os.environ", clear=True)
    @pytest.mark.anyio
    async def test_generate_without_key_returns_empty(self):
        from mindmargin.integrations.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider()
        result = await provider.generate("test", task="test")
        assert result == ""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True)
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_health_check(self, mock_client_class):
        from mindmargin.integrations.anthropic_provider import AnthropicProvider
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = AnthropicProvider()
        assert await provider.health_check() is True

    def test_provider_name(self):
        from mindmargin.integrations.anthropic_provider import AnthropicProvider
        p = AnthropicProvider()
        assert p.provider_name == "anthropic"


# â”€â”€ GeminiProvider â”€â”€

class TestGeminiProvider:
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-gemini-key"}, clear=True)
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_success(self, mock_client_class):
        from mindmargin.integrations.gemini_provider import GeminiProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = GeminiProvider(model="gemini-1.5-flash")
        result = await provider.generate("test", task="test")
        assert result == "Hello from Gemini"

    @patch.dict("os.environ", clear=True)
    @pytest.mark.anyio
    async def test_generate_without_key_returns_empty(self):
        from mindmargin.integrations.gemini_provider import GeminiProvider
        provider = GeminiProvider()
        result = await provider.generate("test", task="test")
        assert result == ""

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-gemini-key"}, clear=True)
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_health_check(self, mock_client_class):
        from mindmargin.integrations.gemini_provider import GeminiProvider
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = GeminiProvider()
        assert await provider.health_check() is True

    def test_provider_name(self):
        from mindmargin.integrations.gemini_provider import GeminiProvider
        p = GeminiProvider()
        assert p.provider_name == "gemini"


# â”€â”€ Backward compatibility: OllamaClient â”€â”€

class TestOllamaClientBackwardCompat:
    def test_ollama_client_is_ollama_provider(self):
        from mindmargin.integrations.ollama import OllamaClient
        from mindmargin.integrations.ollama_provider import OllamaProvider
        assert OllamaClient is OllamaProvider

    def test_can_instantiate_ollama_client(self):
        from mindmargin.integrations.ollama import OllamaClient
        client = OllamaClient(model="test-model")
        assert client.provider_name == "ollama"
        assert client.model_name == "test-model"


# â”€â”€ LLMProvider default methods â”€â”€

class TestProviderDefaults:
    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_json(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": '{"key": "value"}'}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        result = await provider.generate_json(
            'Return JSON: {"key": "value"}', task="test"
        )
        assert result == {"key": "value"}

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_json_from_markdown(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": '```json\n{"key": "value"}\n```'
        }
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        result = await provider.generate_json("test", task="test")
        assert result == {"key": "value"}

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_json_empty_fallback(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": ""}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        result = await provider.generate_json("test", task="test")
        assert result == {}

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_generate_section(self, mock_client_class):
        from mindmargin.integrations.ollama_provider import OllamaProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "section content"}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        result = await provider.generate_section(
            "write hook", "hook", temperature=0.7
        )
        assert result == "section content"

