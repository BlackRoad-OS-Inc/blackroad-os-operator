"""
LLM Client - OpenAI API wrapper for BlackRoad OS Operator

Provides a clean interface for LLM calls with structured tracing.
Uses the secrets resolver for API key management.

@owner Alexa Louise Amundson
@amundson 0.1.0
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import List, Literal, Optional

import httpx
from openai import OpenAI

from .secrets import resolve_secret, get_secret, SecretNotFoundError


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
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create the singleton LLM client."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


class OllamaClient:
    """Direct Ollama API client — no external provider dependency.

    Sends requests to a locally-running Ollama instance.
    Configured via OLLAMA_URL and OLLAMA_MODEL environment variables.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        self.timeout = timeout
        # Persistent client for connection reuse across requests
        self._client = httpx.Client(timeout=self.timeout)

    def chat(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """Send a chat request to the local Ollama instance.

        Args:
            messages: List of LLMMessage objects
            model: Override the default Ollama model
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens in response (maps to num_predict)

        Returns:
            LLMResult with reply and trace
        """
        start_time = time.time()

        ollama_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        payload: dict = {
            "model": model or self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        response = self._client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        response_time_ms = (time.time() - start_time) * 1000

        reply = data.get("message", {}).get("content", "").strip()
        used_model = data.get("model", model or self.model)

        # Ollama eval_count ≈ tokens out; prompt_eval_count ≈ tokens in
        tokens_in = data.get("prompt_eval_count")
        tokens_out = data.get("eval_count")

        trace = LLMTrace(
            llm_provider="ollama",
            model=used_model,
            response_time_ms=round(response_time_ms, 2),
            used_rag=False,
            raw_tokens_in=tokens_in,
            raw_tokens_out=tokens_out,
        )

        return LLMResult(reply=reply, trace=trace)

    def list_models(self) -> List[str]:
        """Return model names available in the local Ollama instance."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []


# Singleton Ollama client
_ollama_client: Optional[OllamaClient] = None


def get_ollama_client() -> OllamaClient:
    """Get or create the singleton Ollama client."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client
