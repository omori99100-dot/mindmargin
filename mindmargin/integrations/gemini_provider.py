import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from mindmargin.integrations.provider import LLMProvider
from mindmargin.integrations.tracking import get_tracker

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(self, model: str = "gemini-1.5-flash",
                 api_key: Optional[str] = None,
                 timeout: int = 120):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model
        self._timeout = timeout
        self._has_key = bool(self._api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self.model

    def _base_url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"

    def _count_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) * 1.3))

    async def generate(self, prompt: str, system: Optional[str] = None,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None,
                       task: str = "") -> str:
        if not self._has_key:
            logger.warning("Gemini API key not set, skipping generation")
            return ""
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature if temperature is not None else 0.7,
                "maxOutputTokens": max_tokens or 4096,
            },
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url()}:generateContent?key={self._api_key}",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                text = ""
                for candidate in data.get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        text += part.get("text", "")
                usage = data.get("usageMetadata", {})
                in_tok = usage.get("promptTokenCount", self._count_tokens(prompt + (system or "")))
                out_tok = usage.get("candidatesTokenCount", self._count_tokens(text))
                latency = (time.monotonic() - start) * 1000
                get_tracker().record("gemini", self.model, task, in_tok, out_tok, latency, success=True)
                return text
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("gemini", self.model, task, 0, 0, latency, success=False)
            logger.warning(f"Gemini generate failed: {e}")
            return ""

    async def generate_stream(self, prompt: str,
                              system: Optional[str] = None,
                              temperature: Optional[float] = None,
                              max_tokens: Optional[int] = None,
                              task: str = "") -> AsyncGenerator[str, None]:
        if not self._has_key:
            return
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature if temperature is not None else 0.7,
                "maxOutputTokens": max_tokens or 4096,
            },
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url()}:streamGenerateContent?key={self._api_key}",
                    json=payload,
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
                                for candidate in data.get("candidates", []):
                                    for part in candidate.get("content", {}).get("parts", []):
                                        chunk = part.get("text", "")
                                        if chunk:
                                            full_text.append(chunk)
                                            yield chunk
                            except json.JSONDecodeError:
                                continue
                    latency = (time.monotonic() - start) * 1000
                    result = "".join(full_text)
                    in_tok = self._count_tokens(prompt + (system or ""))
                    out_tok = self._count_tokens(result)
                    get_tracker().record("gemini", self.model, task, in_tok, out_tok, latency, success=True)
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("gemini", self.model, task, 0, 0, latency, success=False)
            logger.warning(f"Gemini stream failed: {e}")

    async def chat(self, messages: list[dict],
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> str:
        if not self._has_key:
            return ""
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            contents.append({"role": role, "parts": [{"text": content}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature if temperature is not None else 0.7,
                "maxOutputTokens": max_tokens or 4096,
            },
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url()}:generateContent?key={self._api_key}",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                text = ""
                for candidate in data.get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        text += part.get("text", "")
                usage = data.get("usageMetadata", {})
                in_tok = usage.get("promptTokenCount", self._count_tokens(str(messages)))
                out_tok = usage.get("candidatesTokenCount", self._count_tokens(text))
                latency = (time.monotonic() - start) * 1000
                get_tracker().record("gemini", self.model, "chat", in_tok, out_tok, latency, success=True)
                return text
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            get_tracker().record("gemini", self.model, "chat", 0, 0, latency, success=False)
            logger.warning(f"Gemini chat failed: {e}")
            return ""

    async def health_check(self) -> bool:
        if not self._has_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={self._api_key}",
                )
                return resp.status_code == 200
        except Exception:
            return False
