"""Tests for Ollama mention detection and routing."""
from __future__ import annotations

import pytest

from br_operator.llm_client import detect_ollama_mention, OllamaClient, DEFAULT_OLLAMA_URL, DEFAULT_OLLAMA_MODEL


# ---------------------------------------------------------------------------
# detect_ollama_mention
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "@copilot, help me",
    "@copilot. what do you think?",
    "Hey @lucidia can you answer this?",
    "@blackboxprogramming write some code",
    "@blackboxprogramming. do it now",
    "@ollama respond please",
    "HELLO @COPILOT UPPER CASE",
    "mixed @Lucidia case",
])
def test_detect_ollama_mention_positive(message: str) -> None:
    assert detect_ollama_mention(message) is True, f"Should detect mention in: {message!r}"


@pytest.mark.parametrize("message", [
    "Hey ChatGPT, help me",
    "Use openai for this",
    "No mentions here at all",
    "copilot without the @ sign",
    "blackboxprogramming without @",
])
def test_detect_ollama_mention_negative(message: str) -> None:
    assert detect_ollama_mention(message) is False, f"Should NOT detect mention in: {message!r}"


# ---------------------------------------------------------------------------
# OllamaClient defaults
# ---------------------------------------------------------------------------

def test_ollama_client_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    client = OllamaClient()
    assert client.base_url == DEFAULT_OLLAMA_URL
    assert client.model == DEFAULT_OLLAMA_MODEL


def test_ollama_client_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_URL", "http://mypi.local:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral:instruct")
    client = OllamaClient()
    assert client.base_url == "http://mypi.local:11434"
    assert client.model == "mistral:instruct"
