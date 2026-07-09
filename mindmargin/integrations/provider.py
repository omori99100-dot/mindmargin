import asyncio
import json
import logging
import re as _re
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Optional

from mindmargin.integrations.tracking import get_tracker, estimate_tokens

logger = logging.getLogger(__name__)

TOKEN_BUDGETS = {
    "hook": 512,
    "context": 1024,
    "historical_background": 1024,
    "growth_story": 1024,
    "critical_decisions": 1024,
    "main_mistakes": 1024,
    "collapse": 1024,
    "consequences": 1024,
    "lessons_learned": 768,
    "closing": 512,
    "title": 256,
    "seo": 1024,
    "research": 2048,
    "hook_gen": 1024,
    "quality": 1024,
    "scene_planning": 2048,
    "thumbnail_concepts": 1024,
    "production_report": 1024,
    "quality_scoring": 1024,
}


class LLMProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @abstractmethod
    async def generate(self, prompt: str, system: Optional[str] = None,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None,
                       task: str = "") -> str:
        ...

    @abstractmethod
    async def generate_stream(self, prompt: str,
                              system: Optional[str] = None,
                              temperature: Optional[float] = None,
                              max_tokens: Optional[int] = None,
                              task: str = ""
                              ) -> AsyncGenerator[str, None]:
        ...

    @abstractmethod
    async def chat(self, messages: list[dict],
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> str:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    async def generate_json(self, prompt: str, system: Optional[str] = None,
                            temperature: Optional[float] = None,
                            task: str = "") -> Any:
        raw = await self.generate(prompt, system=system,
                                  temperature=temperature, task=task)
        if not raw:
            return {}
        text = raw.strip()
        if "```" in text:
            m = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
            if m:
                text = m.group(1).strip()
        if not (text.startswith("{") or text.startswith("[")):
            brace = text.find("{")
            bracket = text.find("[")
            start = brace if brace >= 0 else bracket
            if start >= 0:
                text = text[start:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM output not valid JSON, returning empty")
            return {}

    async def generate_stream_json(self, prompt: str,
                                   system: Optional[str] = None,
                                   temperature: Optional[float] = None,
                                   task: str = "") -> AsyncGenerator[str, None]:
        buffer = ""
        async for chunk in self.generate_stream(prompt, system=system,
                                                temperature=temperature,
                                                task=task):
            buffer += chunk
            yield chunk

    async def generate_section(self, prompt: str, section_name: str,
                               system: Optional[str] = None,
                               temperature: Optional[float] = None) -> str:
        budget = TOKEN_BUDGETS.get(section_name, 1024)
        return await self.generate(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=budget,
            task=section_name,
        )

    # ── Synchronous wrappers for use outside async contexts ──

    def generate_json_sync(self, prompt: str, system: Optional[str] = None,
                           temperature: Optional[float] = None,
                           task: str = "") -> Any:
        """Synchronous wrapper around generate_json. Runs the async method in a new event loop."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.generate_json(prompt, system=system, temperature=temperature, task=task)
                )
            finally:
                loop.close()
        except Exception as e:
            logger.warning("generate_json_sync failed: %s", e)
            return {}

    def generate_section_sync(self, prompt: str, section_name: str,
                              system: Optional[str] = None,
                              temperature: Optional[float] = None) -> str:
        """Synchronous wrapper around generate_section. Runs the async method in a new event loop."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.generate_section(prompt, section_name, system=system, temperature=temperature)
                )
            finally:
                loop.close()
        except Exception as e:
            logger.warning("generate_section_sync failed: %s", e)
            return ""


def extract_json_from_text(text: str) -> Any:
    if not text:
        return {}
    text = text.strip()
    if "```" in text:
        m = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
        if m:
            text = m.group(1).strip()
    if not (text.startswith("{") or text.startswith("[")):
        brace = text.find("{")
        bracket = text.find("[")
        start = brace if brace >= 0 else bracket
        if start >= 0:
            text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
