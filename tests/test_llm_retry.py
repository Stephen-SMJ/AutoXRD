from __future__ import annotations

import httpx
import openai

from core.llm import LLMClient


def openai_client_without_network() -> LLMClient:
    client = object.__new__(LLMClient)
    client.provider = "openai"
    return client


def test_openai_http2_stream_reset_is_retryable():
    error = openai.APIError(
        "stream error: stream ID 1; INTERNAL_ERROR; received from peer",
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        body=None,
    )
    assert openai_client_without_network().is_retryable_error(error)


def test_ordinary_openai_api_error_is_not_retryable():
    error = openai.APIError(
        "invalid request parameter",
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        body=None,
    )
    assert not openai_client_without_network().is_retryable_error(error)
