"""
Tests for Ollama @mention routing.

Validates that @copilot, @lucidia, @blackboxprogramming, and @ollama
triggers are detected and stripped correctly, and that generate_chat_response
routes to OllamaClient instead of the external LLM provider.
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from br_operator.llm_client import LLMMessage, LLMResult, LLMTrace, OllamaClient
from br_operator.llm_service import (
    OLLAMA_MENTION_TRIGGERS,
    detect_ollama_mention,
    strip_mention_prefix,
)


# ---------------------------------------------------------------------------
# detect_ollama_mention
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "@copilot hello",
    "@COPILOT hello",
    "@lucidia what is the time?",
    "@Lucidia what is the time?",
    "@blackboxprogramming run tests",
    "@BlackBoxProgramming run tests",
    "@ollama summarise this",
    "@OLLAMA summarise this",
    "Hey @ollama can you help?",        # inline mention
    "Please ask @copilot to answer",    # inline mention
])
def test_detect_ollama_mention_true(message: str) -> None:
    assert detect_ollama_mention(message) is True


@pytest.mark.parametrize("message", [
    "hello world",
    "What is the weather?",
    "copilot without at-sign",
    "lucidia without at-sign",
    "@unknown handle",
    "",
])
def test_detect_ollama_mention_false(message: str) -> None:
    assert detect_ollama_mention(message) is False


# ---------------------------------------------------------------------------
# strip_mention_prefix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("@copilot hello there", "hello there"),
    ("@COPILOT hello there", "hello there"),
    ("@lucidia what is X?", "what is X?"),
    ("@blackboxprogramming run lint", "run lint"),
    ("@ollama give me a poem", "give me a poem"),
    ("@ollama", ""),                    # only trigger, no body
    ("hello world", "hello world"),    # no trigger → unchanged
    ("Hey @copilot do this", "Hey @copilot do this"),  # inline → unchanged
])
def test_strip_mention_prefix(raw: str, expected: str) -> None:
    assert strip_mention_prefix(raw) == expected


# ---------------------------------------------------------------------------
# OLLAMA_MENTION_TRIGGERS constant
# ---------------------------------------------------------------------------

def test_ollama_mention_triggers_set() -> None:
    assert "@copilot" in OLLAMA_MENTION_TRIGGERS
    assert "@lucidia" in OLLAMA_MENTION_TRIGGERS
    assert "@blackboxprogramming" in OLLAMA_MENTION_TRIGGERS
    assert "@ollama" in OLLAMA_MENTION_TRIGGERS


# ---------------------------------------------------------------------------
# generate_chat_response routes to Ollama on @mention
# ---------------------------------------------------------------------------

def _make_ollama_result(text: str = "pong") -> LLMResult:
    return LLMResult(
        reply=text,
        trace=LLMTrace(
            llm_provider="ollama",
            model="llama3.2:latest",
            response_time_ms=10.0,
        ),
    )


@pytest.mark.asyncio
async def test_generate_chat_response_uses_ollama_for_copilot_mention() -> None:
    from br_operator.llm_service import generate_chat_response

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.chat.return_value = _make_ollama_result("I am Ollama")

    with patch("br_operator.llm_service.get_ollama_client", return_value=mock_ollama):
        result = await generate_chat_response(message="@copilot ping")

    mock_ollama.chat.assert_called_once()
    assert result["reply"] == "I am Ollama"
    assert result["trace"]["llm_provider"] == "ollama"
    assert result["trace"]["used_rag"] is False


@pytest.mark.asyncio
async def test_generate_chat_response_uses_ollama_for_lucidia_mention() -> None:
    from br_operator.llm_service import generate_chat_response

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.chat.return_value = _make_ollama_result("Lucidia here")

    with patch("br_operator.llm_service.get_ollama_client", return_value=mock_ollama):
        result = await generate_chat_response(message="@lucidia hello")

    mock_ollama.chat.assert_called_once()
    assert result["trace"]["llm_provider"] == "ollama"


@pytest.mark.asyncio
async def test_generate_chat_response_uses_ollama_for_blackboxprogramming() -> None:
    from br_operator.llm_service import generate_chat_response

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.chat.return_value = _make_ollama_result("BlackBox via Ollama")

    with patch("br_operator.llm_service.get_ollama_client", return_value=mock_ollama):
        result = await generate_chat_response(message="@blackboxprogramming run tests")

    mock_ollama.chat.assert_called_once()
    assert result["trace"]["llm_provider"] == "ollama"


@pytest.mark.asyncio
async def test_generate_chat_response_uses_ollama_for_ollama_mention() -> None:
    from br_operator.llm_service import generate_chat_response

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.chat.return_value = _make_ollama_result("direct ollama")

    with patch("br_operator.llm_service.get_ollama_client", return_value=mock_ollama):
        result = await generate_chat_response(message="@ollama tell me a joke")

    mock_ollama.chat.assert_called_once()
    assert result["trace"]["llm_provider"] == "ollama"


@pytest.mark.asyncio
async def test_generate_chat_response_strips_prefix_before_ollama_call() -> None:
    """The message sent to Ollama should have the @mention prefix removed."""
    from br_operator.llm_service import generate_chat_response

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.chat.return_value = _make_ollama_result("ok")

    with patch("br_operator.llm_service.get_ollama_client", return_value=mock_ollama):
        await generate_chat_response(message="@copilot what is 2+2?")

    call_args = mock_ollama.chat.call_args
    messages: List[LLMMessage] = call_args.kwargs.get("messages") or call_args.args[0]
    # The last message (user turn) should not contain the trigger prefix
    user_msg = messages[-1].content
    assert "@copilot" not in user_msg.lower()
    assert user_msg == "what is 2+2?"


@pytest.mark.asyncio
async def test_generate_chat_response_does_not_use_ollama_for_plain_message() -> None:
    """Plain messages (no @mention) must not call OllamaClient."""
    from br_operator.llm_service import generate_chat_response

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_openai = MagicMock()
    mock_openai.chat.return_value = _make_ollama_result("openai reply")
    # Reuse LLMResult shape; provider label doesn't matter for this assertion
    mock_openai.chat.return_value.trace.llm_provider = "openai"

    with (
        patch("br_operator.llm_service.get_ollama_client", return_value=mock_ollama),
        patch("br_operator.llm_service.get_llm_client", return_value=mock_openai),
        patch("br_operator.llm_service.fetch_rag_context", return_value=([], 0)),
    ):
        result = await generate_chat_response(message="hello world")

    mock_ollama.chat.assert_not_called()
    mock_openai.chat.assert_called_once()
