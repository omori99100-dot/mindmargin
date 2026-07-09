import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from mindmargin.integrations.provider import LLMProvider
from mindmargin.integrations.tracking import get_tracker

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = "claude-3-5-sonnet-20241022",
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: int = 120):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        self._timeout = timeout
        self._has_key = bool(self._api_key)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self.model

    def _headers(self) -> dict:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _count_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) * 1.3))

    async def generate(self, prompt: str, system: Optional[str] = None,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None,
                       task: str = "") -> str:
        if not self._has_key:
            logger.warning("Anthropic API key not set, skipping generation")
            return ""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens or 4096,
            "temperature": temperature if temperature is not None else 0.7,
        }
        if system:
            payload["system"] = system

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/messages",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                text = "".join(
                    block["text"] for block in data.get("content", [])
                    if block.get("type") == "text"
                )
                usage = data.get("usage", {})
                in_tok = usage.get("input_tokens", self._count_tokens(prompt + (system or "")))
                out_tok = usage.get("output_tokens", self._count_tokens(text))
                latency = (time.monotonic() - start) * 1000
                get_tracker().record("anthropic", self.model, task, in_tok, out_tok, latency, success=True)
                return text
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("anthropic", self.model, task, 0, 0, latency, success=False)
            logger.warning(f"Anthropic generate failed: {e}")
            return ""

    async def generate_stream(self, prompt: str,
                              system: Optional[str] = None,
                              temperature: Optional[float] = None,
                              max_tokens: Optional[int] = None,
                              task: str = "") -> AsyncGenerator[str, None]:
        if not self._has_key:
            return
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens or 4096,
            "temperature": temperature if temperature is not None else 0.7,
            "stream": True,
        }
        if system:
            payload["system"] = system

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/messages",
                    headers=self._headers(), json=payload,
                ) as resp:
                    resp.raise_for_status()
                    full_text = []
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                if data.get("type") == "content_block_delta":
                                    delta = data.get("delta", {})
                                    chunk = delta.get("text", "")
                                    if chunk:
                                        full_text.append(chunk)
                                        yield chunk
                            except json.JSONDecodeError:
                                continue
                    latency = (time.monotonic() - start) * 1000
                    result = "".join(full_text)
                    in_tok = self._count_tokens(prompt + (system or ""))
                    out_tok = self._count_tokens(result)
                    get_tracker().record("anthropic", self.model, task, in_tok, out_tok, latency, success=True)
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("anthropic", self.model, task, 0, 0, latency, success=False)
            logger.warning(f"Anthropic stream failed: {e}")

    async def chat(self, messages: list[dict],
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> str:
        if not self._has_key:
            return ""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature if temperature is not None else 0.7,
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/messages",
                    headers=self._headers(), json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                text = "".join(
                    block["text"] for block in data.get("content", [])
                    if block.get("type") == "text"
                )
                usage = data.get("usage", {})
                in_tok = usage.get("input_tokens", self._count_tokens(str(messages)))
                out_tok = usage.get("output_tokens", self._count_tokens(text))
                latency = (time.monotonic() - start) * 1000
                get_tracker().record("anthropic", self.model, "chat", in_tok, out_tok, latency, success=True)
                return text
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("anthropic", self.model, "chat", 0, 0, latency, success=False)
            logger.warning(f"Anthropic chat failed: {e}")
            return ""

    async def health_check(self) -> bool:
        if not self._has_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False
