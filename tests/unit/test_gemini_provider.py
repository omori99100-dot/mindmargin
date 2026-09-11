import pytest
from unittest.mock import AsyncMock, patch

import httpx

import mindmargin.integrations.gemini_provider as gp


class _FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.t

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def _client_for(responses):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=responses)
    return client


def _response(status_code, **kwargs):
    return httpx.Response(
        status_code, request=httpx.Request("POST", "http://localhost"), **kwargs
    )


@pytest.fixture(autouse=True)
def _reset_tracker():
    from mindmargin.integrations.tracking import get_tracker
    get_tracker().reset()


@pytest.fixture(autouse=True)
def _no_real_sleeps(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(gp.asyncio, "sleep", fake_sleep)
    return sleeps


class TestGeminiRetry:
    def _provider(self, monkeypatch, **kwargs):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        return gp.GeminiProvider(**kwargs)

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_success_after_503_retry(self, mock_client_class, monkeypatch):
        client = _client_for([
            _response(503),
            _response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}),
        ])
        mock_client_class.return_value = client
        provider = self._provider(monkeypatch)
        result = await provider.generate("hi", task="test")
        assert result == "ok"
        assert client.post.call_count == 2

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_retry_after_respected_on_429(self, mock_client_class, monkeypatch):
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(gp.asyncio, "sleep", fake_sleep)
        client = _client_for([
            _response(429, headers={"Retry-After": "2"}),
            _response(200, json={"candidates": [{"content": {"parts": [{"text": "slow"}]}}]}),
        ])
        mock_client_class.return_value = client
        provider = self._provider(monkeypatch, burst_capacity=3)
        result = await provider.generate("hi", task="test")
        assert result == "slow"
        assert client.post.call_count == 2
        assert sleeps == [pytest.approx(2.0, abs=0.01)]

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_exhausted_retries_fall_back_to_empty(self, mock_client_class, monkeypatch):
        client = _client_for([_response(503), _response(503), _response(503)])
        mock_client_class.return_value = client
        provider = self._provider(monkeypatch)
        result = await provider.generate("hi", task="test")
        assert result == ""
        assert client.post.call_count == 3

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_non_retryable_4xx_fails_fast(self, mock_client_class, monkeypatch):
        client = _client_for([_response(400)])
        mock_client_class.return_value = client
        provider = self._provider(monkeypatch)
        result = await provider.generate("hi", task="test")
        assert result == ""
        assert client.post.call_count == 1

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_token_bucket_paces_requests(self, mock_client_class, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr(gp.time, "monotonic", clock.monotonic)
        monkeypatch.setattr(gp.asyncio, "sleep", clock.sleep)
        client = _client_for([
            _response(200, json={"candidates": [{"content": {"parts": [{"text": "a"}]}}]}),
            _response(200, json={"candidates": [{"content": {"parts": [{"text": "b"}]}}]}),
        ])
        mock_client_class.return_value = client
        provider = self._provider(monkeypatch, requests_per_minute=1, burst_capacity=1)
        first = await provider.generate("one", task="test")
        second = await provider.generate("two", task="test")
        assert (first, second) == ("a", "b")
        assert len(clock.sleeps) >= 1
        assert clock.sleeps[0] > 0

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_retry_delay_parsed_from_429_body_message(self, mock_client_class, monkeypatch):
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(gp.asyncio, "sleep", fake_sleep)
        body = {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": (
                    "You exceeded your current quota, please check your plan and billing "
                    "details. For more information on this error, head to: "
                    "https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your "
                    "current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded "
                    "for metric: generativelanguage.googleapis.com/"
                    "generate_content_free_tier_requests, limit: 5, model: "
                    "gemini-3.8-flash\nPlease retry in 27.97032315s."
                ),
            },
        }
        client = _client_for([
            _response(429, json=body),
            _response(200, json={"candidates": [{"content": {"parts": [{"text": "quota-aware"}]}}]}),
        ])
        mock_client_class.return_value = client
        provider = self._provider(monkeypatch, burst_capacity=3)
        result = await provider.generate("hi", task="test")
        assert result == "quota-aware"
        assert client.post.call_count == 2
        assert sleeps == [pytest.approx(27.97032315, abs=0.01)]

    @patch("httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_retry_delay_falls_back_to_header_when_body_unparseable(self, mock_client_class, monkeypatch):
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(gp.asyncio, "sleep", fake_sleep)
        client = _client_for([
            _response(429, headers={"Retry-After": "2"}, text="not-json"),
            _response(200, json={"candidates": [{"content": {"parts": [{"text": "header"}]}}]}),
        ])
        mock_client_class.return_value = client
        provider = self._provider(monkeypatch, burst_capacity=3)
        result = await provider.generate("hi", task="test")
        assert result == "header"
        assert client.post.call_count == 2
        assert sleeps == [pytest.approx(2.0, abs=0.01)]