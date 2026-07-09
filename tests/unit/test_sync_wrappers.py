"""Test sync wrapper methods."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from mindmargin.integrations.provider import LLMProvider
class ConcreteLLMProvider(LLMProvider):
    """Concrete implementation for testing sync wrappers."""

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def model_name(self) -> str:
        return "test-model"

    async def generate(self, prompt: str, system=None, temperature=None, max_tokens=None, task: str = "") -> str:
        return ""

    async def generate_stream(self, prompt: str, system=None, temperature=None, max_tokens=None, task: str = "") -> AsyncMock:
        yield ""

    async def chat(self, messages, temperature=None, max_tokens=None) -> str:
        return ""

    async def health_check(self) -> bool:
        return True
class TestSyncWrappers:
    """Test synchronous wrapper methods."""

    def test_generate_json_sync_calls_async(self):
        """Test generate_json_sync calls async method."""
        provider = ConcreteLLMProvider()
        provider.generate_json = AsyncMock(return_value={"test": "data"})

        result = provider.generate_json_sync("prompt", system="system")

        provider.generate_json.assert_called_once_with(
            "prompt", system="system", temperature=None, task=""
        )
        assert result == {"test": "data"}

    def test_generate_json_sync_returns_empty_on_exception(self):
        """Test generate_json_sync returns {} when async fails."""
        provider = ConcreteLLMProvider()
        provider.generate_json = AsyncMock(side_effect=Exception("LLM error"))

        result = provider.generate_json_sync("prompt")

        assert result == {}

    def test_generate_section_sync_calls_async(self):
        """Test generate_section_sync calls async method."""
        provider = ConcreteLLMProvider()
        provider.generate_section = AsyncMock(return_value="section content")

        result = provider.generate_section_sync("prompt", "hook", system="system")

        provider.generate_section.assert_called_once_with(
            "prompt", "hook", system="system", temperature=None
        )
        assert result == "section content"

    def test_generate_section_sync_returns_empty_on_exception(self):
        """Test generate_section_sync returns '' when async fails."""
        provider = ConcreteLLMProvider()
        provider.generate_section = AsyncMock(side_effect=Exception("LLM error"))

        result = provider.generate_section_sync("prompt", "hook")

        assert result == ""
