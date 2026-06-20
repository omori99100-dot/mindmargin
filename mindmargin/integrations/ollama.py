import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional

import httpx

from mindmargin.config import settings

logger = logging.getLogger(__name__)

TOKEN_BUDGETS = {
    "hook": 512,
    "rise": 1024,
    "first_crack": 1024,
    "overconfidence_loop": 1024,
    "escalation": 1024,
    "collapse": 1024,
    "twist": 768,
    "lesson": 768,
    "close": 512,
    "title": 256,
    "seo": 1024,
    "research": 2048,
    "hook_gen": 1024,
    "quality": 1024,
}


class OllamaClient:
    """Ollama API wrapper with streaming, long-form context, token budgeting."""

    def __init__(self, base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 context_memory: int = 1024):
        self.base_url = (base_url or settings.llm.base_url).rstrip("/")
        self.model = model or settings.llm.model
        self.context_memory = context_memory
        self._conversation: list[dict] = []

    def _token_budget(self, task: str) -> int:
        return TOKEN_BUDGETS.get(task, settings.llm.max_tokens)

    def _options(self, temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> dict:
        return {
            "temperature": temperature if temperature is not None else settings.llm.temperature,
            "num_predict": max_tokens or settings.llm.max_tokens,
            "num_ctx": self.context_memory,
        }

    async def generate(self, prompt: str, system: Optional[str] = None,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None,
                       task: str = "") -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": self._options(temperature,
                                     max_tokens or self._token_budget(task)),
        }
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                text = resp.json().get("response", "")
                self._update_context("user", prompt)
                self._update_context("assistant", text)
                return text
        except Exception as e:
            logger.warning(f"Ollama call failed: {e}")
            return ""

    async def generate_stream(self, prompt: str,
                              system: Optional[str] = None,
                              temperature: Optional[float] = None,
                              max_tokens: Optional[int] = None,
                              task: str = "") -> AsyncGenerator[str, None]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": self._options(temperature,
                                     max_tokens or self._token_budget(task)),
        }
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/generate",
                                         json=payload) as resp:
                    resp.raise_for_status()
                    full_text = []
                    async for line in resp.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                chunk = data.get("response", "")
                                if chunk:
                                    full_text.append(chunk)
                                    yield chunk
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
                    self._update_context("user", prompt)
                    self._update_context("assistant", "".join(full_text))
        except Exception as e:
            logger.warning(f"Ollama stream failed: {e}")

    async def generate_json(self, prompt: str, system: Optional[str] = None,
                            temperature: Optional[float] = None,
                            task: str = "") -> Any:
        raw = await self.generate(prompt, system=system,
                                  temperature=temperature, task=task)
        if not raw:
            return {}
        text = raw.strip()
        # Try extracting JSON from markdown code blocks
        if "```" in text:
            import re as _re
            m = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
            if m:
                text = m.group(1).strip()
        # Try to find a JSON array or object in the text
        if not (text.startswith("{") or text.startswith("[")):
            import re as _re
            brace = text.find("{")
            bracket = text.find("[")
            start = brace if brace >= 0 else bracket
            if start >= 0 and start < bracket if bracket >= 0 else True:
                text = text[start:]
            elif bracket >= 0:
                text = text[bracket:]
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
        budget = self._token_budget(section_name)
        return await self.generate(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=budget,
            task=section_name,
        )

    async def chat(self, messages: list[dict],
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(temperature, max_tokens),
        }
        try:
            async with httpx.AsyncClient(timeout=settings.llm.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json().get("message", {}).get("content", "")
        except Exception as e:
            logger.warning(f"Ollama chat failed: {e}")
            return ""

    def _update_context(self, role: str, content: str):
        self._conversation.append({"role": role, "content": content})
        total = sum(len(m["content"]) for m in self._conversation)
        while total > self.context_memory * 4 and len(self._conversation) > 4:
            self._conversation.pop(0)
            total = sum(len(m["content"]) for m in self._conversation)

    def reset_context(self):
        self._conversation = []

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
