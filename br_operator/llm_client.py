"""
LLM Client - Multi-provider LLM wrapper for BlackRoad OS Operator

Supports Ollama (local, no API key) and OpenAI (cloud).
Set LLM_PROVIDER=ollama to run fully local with no external dependencies.

@owner Alexa Louise Amundson
@amundson 0.2.0
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Literal, Optional, Union

import ollama as ollama_lib
from openai import OpenAI

from .secrets import resolve_secret, SecretNotFoundError


@dataclass
class LLMMessage:
    """A single message in a chat conversation."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMTrace:
    """Trace information for an LLM call."""

    llm_provider: str
    model: str
    response_time_ms: float
    used_rag: bool = False
    raw_tokens_in: Optional[int] = None
    raw_tokens_out: Optional[int] = None


@dataclass
class LLMResult:
    """Result from an LLM call."""

    reply: str
    trace: LLMTrace


class OllamaClient:
    """Local Ollama LLM client - no API key required."""

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
        # base_url is exposed so check_llm_health() can read it uniformly
        self.base_url = self.host
        self._client = ollama_lib.Client(host=self.host)

    def chat(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """
        Send a chat request to the local Ollama instance.

        Args:
            messages: List of LLMMessage objects
            model: Override the default model
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens in response

        Returns:
            LLMResult with reply and trace
        """
        start_time = time.time()

        ollama_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        options: dict = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens

        response = self._client.chat(
            model=model or self.model,
            messages=ollama_messages,
            options=options,
        )

        response_time_ms = (time.time() - start_time) * 1000

        # Extract token counts from Ollama response
        tokens_in = getattr(response, "prompt_eval_count", None)
        tokens_out = getattr(response, "eval_count", None)

        trace = LLMTrace(
            llm_provider="ollama",
            model=response.model,
            response_time_ms=round(response_time_ms, 2),
            used_rag=False,
            raw_tokens_in=tokens_in,
            raw_tokens_out=tokens_out,
        )

        reply = response.message.content or ""
        return LLMResult(reply=reply.strip(), trace=trace)


class LLMClient:
    """OpenAI-compatible LLM client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        # Use secrets resolver - alias-based lookup
        # Falls back to direct env var for backwards compatibility
        self.api_key = api_key or resolve_secret("openai.default") or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        if not self.api_key:
            raise SecretNotFoundError(
                alias="openai.default",
                env_var="OPENAI_API_KEY",
                hint="Set OPENAI_API_KEY in Railway or local .env"
            )

        # Initialize OpenAI client
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self._client = OpenAI(**client_kwargs)

    def chat(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """
        Send a chat request to the LLM.

        Args:
            messages: List of LLMMessage objects
            model: Override the default model
            temperature: Sampling temperature (0.0 to 2.0)
            max_tokens: Maximum tokens in response

        Returns:
            LLMResult with reply and trace
        """
        start_time = time.time()

        # Convert to OpenAI format
        openai_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        # Build request kwargs
        request_kwargs = {
            "model": model or self.model,
            "messages": openai_messages,
            "temperature": temperature,
        }
        if max_tokens:
            request_kwargs["max_tokens"] = max_tokens

        # Make the API call
        response = self._client.chat.completions.create(**request_kwargs)

        response_time_ms = (time.time() - start_time) * 1000

        # Extract usage
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else None
        tokens_out = usage.completion_tokens if usage else None

        # Build trace
        trace = LLMTrace(
            llm_provider="openai",
            model=response.model,
            response_time_ms=round(response_time_ms, 2),
            used_rag=False,  # Caller can override this
            raw_tokens_in=tokens_in,
            raw_tokens_out=tokens_out,
        )

        # Extract reply
        reply = ""
        if response.choices and len(response.choices) > 0:
            reply = response.choices[0].message.content or ""

        return LLMResult(reply=reply.strip(), trace=trace)


# Singleton instance
_llm_client: Optional[Union[LLMClient, OllamaClient]] = None


def get_llm_client() -> Union[LLMClient, OllamaClient]:
    """
    Get or create the singleton LLM client.

    Set LLM_PROVIDER=ollama to use local Ollama (no API key needed).
    Set LLM_PROVIDER=openai (default) to use OpenAI.
    """
    global _llm_client
    if _llm_client is None:
        provider = os.getenv("LLM_PROVIDER", "openai").lower()
        if provider == "ollama":
            _llm_client = OllamaClient()
        else:
            _llm_client = LLMClient()
    return _llm_client
