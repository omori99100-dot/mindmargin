import asyncio
import email.utils
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

import httpx

from mindmargin.integrations.provider import LLMProvider
from mindmargin.integrations.tracking import get_tracker

logger = logging.getLogger(__name__)


class _TokenBucket:
    def __init__(self, rate: float, capacity: float):
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._updated = time.monotonic()

    async def wait(self) -> None:
        while True:
            now = time.monotonic()
            self._tokens = min(
                self._capacity, self._tokens + (now - self._updated) * self._rate
            )
            self._updated = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            await asyncio.sleep((1 - self._tokens) / self._rate)


class GeminiProvider(LLMProvider):
    def __init__(self, model: str = "gemini-flash-latest",
                 api_key: Optional[str] = None,
                 timeout: int = 120,
                 max_retries: int = 3,
                 requests_per_minute: float = 15,
                 burst_capacity: int = 3):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model
        self._timeout = timeout
        self._has_key = bool(self._api_key)
        self._max_retries = max_retries
        self._bucket = _TokenBucket(
            rate=requests_per_minute / 60.0, capacity=burst_capacity
        )

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

    def _backoff_delay(self, attempt: int) -> float:
        return min(2 ** attempt + random.uniform(0, 1), 60)

    def _retry_after(self, resp: httpx.Response) -> Optional[float]:
        header = resp.headers.get("Retry-After")
        if not header:
            return None
        try:
            return float(header)
        except ValueError:
            pass
        try:
            parsed = email.utils.parsedate_to_datetime(header)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            return None

    async def _post(self, url: str, payload: dict) -> httpx.Response:
        for attempt in range(1, self._max_retries + 1):
            await self._bucket.wait()
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload)
            except Exception as e:
                if attempt < self._max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        f"Gemini POST attempt {attempt} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            if resp.status_code == 429:
                logger.warning(f"Gemini 429 response body: {resp.text[:500]}")
                if attempt < self._max_retries:
                    delay = self._retry_after(resp) or self._backoff_delay(attempt)
                    logger.warning(
                        f"Gemini POST attempt {attempt} got HTTP 429. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
            if resp.status_code >= 500:
                if attempt < self._max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        f"Gemini POST attempt {attempt} got HTTP {resp.status_code}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return resp
        raise httpx.HTTPError(
            f"Gemini request failed after {self._max_retries} attempts"
        )

    async def _stream_request(self, url: str, payload: dict):
        for attempt in range(1, self._max_retries + 1):
            await self._bucket.wait()
            client = httpx.AsyncClient(timeout=self._timeout)
            try:
                request = client.build_request("POST", url, json=payload)
                resp = await client.send(request, stream=True)
            except Exception as e:
                await client.aclose()
                if attempt < self._max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        f"Gemini stream attempt {attempt} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            if resp.status_code == 429:
                logger.warning(f"Gemini 429 response body: {resp.text[:500]}")
                await resp.aclose()
                await client.aclose()
                if attempt < self._max_retries:
                    delay = self._retry_after(resp) or self._backoff_delay(attempt)
                    logger.warning(
                        f"Gemini stream attempt {attempt} got HTTP 429. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
            if resp.status_code >= 500:
                await resp.aclose()
                await client.aclose()
                if attempt < self._max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        f"Gemini stream attempt {attempt} got HTTP {resp.status_code}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
            if resp.is_error:
                await resp.aclose()
                await client.aclose()
                resp.raise_for_status()
            return client, resp
        raise httpx.HTTPError(
            f"Gemini request failed after {self._max_retries} attempts"
        )

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
            resp = await self._post(
                f"{self._base_url()}:generateContent?key={self._api_key}", payload
            )
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
            client, resp = await self._stream_request(
                f"{self._base_url()}:streamGenerateContent?key={self._api_key}", payload
            )
            full_text = []
            try:
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
            finally:
                await resp.aclose()
                await client.aclose()
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
            resp = await self._post(
                f"{self._base_url()}:generateContent?key={self._api_key}", payload
            )
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