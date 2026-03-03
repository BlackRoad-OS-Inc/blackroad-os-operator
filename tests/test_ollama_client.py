"""
Tests for Ollama LLM client integration.

Validates that OllamaClient and get_llm_client() work correctly without
requiring a live Ollama instance or an OpenAI API key.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from br_operator.llm_client import (
    LLMMessage,
    LLMResult,
    LLMTrace,
    OllamaClient,
    get_llm_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ollama_response(content: str = "hello from ollama", model: str = "llama3.2") -> MagicMock:
    """Build a fake ollama.Client.chat() response."""
    msg = MagicMock()
    msg.content = content

    resp = MagicMock()
    resp.message = msg
    resp.model = model
    resp.prompt_eval_count = 10
    resp.eval_count = 5
    return resp


# ---------------------------------------------------------------------------
# OllamaClient unit tests
# ---------------------------------------------------------------------------

def test_ollama_client_defaults():
    """OllamaClient uses sensible defaults from env / fallback values."""
    with patch.dict(os.environ, {}, clear=False):
        with patch("br_operator.llm_client.ollama_lib.Client"):
            client = OllamaClient()
    assert client.host == "http://localhost:11434"
    assert client.model == "llama3.2"


def test_ollama_client_env_overrides():
    """OllamaClient respects OLLAMA_HOST and OLLAMA_MODEL env vars."""
    env = {"OLLAMA_HOST": "http://192.168.1.10:11434", "OLLAMA_MODEL": "mistral"}
    with patch.dict(os.environ, env):
        with patch("br_operator.llm_client.ollama_lib.Client"):
            client = OllamaClient()
    assert client.host == "http://192.168.1.10:11434"
    assert client.model == "mistral"


def test_ollama_client_chat_returns_llm_result():
    """OllamaClient.chat() returns a valid LLMResult with Ollama trace."""
    fake_response = _make_ollama_response("The answer is 42.", model="llama3.2")

    with patch("br_operator.llm_client.ollama_lib.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat.return_value = fake_response

        client = OllamaClient(host="http://localhost:11434", model="llama3.2")
        result = client.chat(messages=[LLMMessage(role="user", content="What is 6x7?")])

    assert isinstance(result, LLMResult)
    assert result.reply == "The answer is 42."
    assert result.trace.llm_provider == "ollama"
    assert result.trace.model == "llama3.2"
    assert result.trace.response_time_ms >= 0
    assert result.trace.raw_tokens_in == 10
    assert result.trace.raw_tokens_out == 5


def test_ollama_client_chat_model_override():
    """OllamaClient.chat() forwards model override to ollama."""
    fake_response = _make_ollama_response(model="phi3")

    with patch("br_operator.llm_client.ollama_lib.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat.return_value = fake_response

        client = OllamaClient()
        client.chat(messages=[LLMMessage(role="user", content="hi")], model="phi3")

    call_kwargs = mock_instance.chat.call_args
    assert call_kwargs.kwargs["model"] == "phi3"


def test_ollama_client_chat_max_tokens():
    """OllamaClient.chat() passes max_tokens as num_predict."""
    fake_response = _make_ollama_response()

    with patch("br_operator.llm_client.ollama_lib.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat.return_value = fake_response

        client = OllamaClient()
        client.chat(
            messages=[LLMMessage(role="user", content="hi")],
            max_tokens=256,
        )

    options = mock_instance.chat.call_args.kwargs["options"]
    assert options["num_predict"] == 256


# ---------------------------------------------------------------------------
# get_llm_client() provider selection
# ---------------------------------------------------------------------------

def test_get_llm_client_returns_ollama_when_provider_set(monkeypatch):
    """get_llm_client() returns OllamaClient when LLM_PROVIDER=ollama."""
    import br_operator.llm_client as llm_mod

    # Reset singleton so selection runs fresh
    llm_mod._llm_client = None

    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    with patch("br_operator.llm_client.ollama_lib.Client"):
        client = get_llm_client()

    assert isinstance(client, OllamaClient)

    # Cleanup singleton for other tests
    llm_mod._llm_client = None


def test_get_llm_client_singleton_is_reused(monkeypatch):
    """get_llm_client() returns the same instance on repeated calls."""
    import br_operator.llm_client as llm_mod

    llm_mod._llm_client = None
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    with patch("br_operator.llm_client.ollama_lib.Client"):
        first = get_llm_client()
        second = get_llm_client()

    assert first is second

    llm_mod._llm_client = None
