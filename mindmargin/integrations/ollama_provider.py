import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from mindmargin.config import settings
from mindmargin.integrations.provider import LLMProvider
from mindmargin.integrations.tracking import estimate_tokens, get_tracker

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 context_memory: int = 1024,
                 timeout: Optional[int] = None):
        self.base_url = (base_url or settings.llm.base_url).rstrip("/")
        self.model = model or settings.llm.model
        self.context_memory = context_memory
        self._timeout = timeout or settings.llm.timeout
        self._conversation: list[dict] = []

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self.model

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
            "options": self._options(temperature, max_tokens),
        }
        if system:
            payload["system"] = system

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                text = resp.json().get("response", "")
                self._update_context("user", prompt)
                self._update_context("assistant", text)
                latency = (time.monotonic() - start) * 1000
                in_tok = estimate_tokens(prompt)
                out_tok = estimate_tokens(text)
                get_tracker().record("ollama", self.model, task, in_tok, out_tok, latency, success=True)
                return text
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("ollama", self.model, task, 0, 0, latency, success=False)
            logger.warning(f"Ollama generate failed: {e}")
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
            "options": self._options(temperature, max_tokens),
        }
        if system:
            payload["system"] = system

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
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
                    result = "".join(full_text)
                    self._update_context("assistant", result)
                    latency = (time.monotonic() - start) * 1000
                    in_tok = estimate_tokens(prompt)
                    out_tok = estimate_tokens(result)
                    get_tracker().record("ollama", self.model, task, in_tok, out_tok, latency, success=True)
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("ollama", self.model, task, 0, 0, latency, success=False)
            logger.warning(f"Ollama stream failed: {e}")

    async def chat(self, messages: list[dict],
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(temperature, max_tokens),
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                result = resp.json().get("message", {}).get("content", "")
                latency = (time.monotonic() - start) * 1000
                in_tok = estimate_tokens(str(messages))
                out_tok = estimate_tokens(result)
                get_tracker().record("ollama", self.model, "chat", in_tok, out_tok, latency, success=True)
                return result
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("ollama", self.model, "chat", 0, 0, latency, success=False)
            logger.warning(f"Ollama chat failed: {e}")
            return ""

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    def _update_context(self, role: str, content: str):
        self._conversation.append({"role": role, "content": content})
        total = sum(len(m["content"]) for m in self._conversation)
        while total > self.context_memory * 4 and len(self._conversation) > 4:
            self._conversation.pop(0)
            total = sum(len(m["content"]) for m in self._conversation)

    def reset_context(self):
        self._conversation = []
