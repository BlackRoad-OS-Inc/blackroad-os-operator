"""
LLM Service - Handles communication with LLM providers via LLMClient
Hero Flow #1 & #2 for BlackRoad OS Operator Engine

Hero Flow #1: User → Operator → OpenAI → Response
Hero Flow #2: User → Operator → RAG API → OpenAI → Response

@owner Alexa Louise Amundson
@amundson 0.1.0
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import httpx

from .llm_client import (
    LLMClient, LLMMessage, LLMResult, get_llm_client,
    OllamaClient, get_ollama_client, detect_ollama_mention,
    DEFAULT_OLLAMA_URL,
)
from .traced_http import TracedAsyncClient
from .ps_sha_infinity import get_cece_identity, create_verification_stamp, get_root_cipher

# =============================================================================
# Configuration from environment
# =============================================================================
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

# RAG API configuration
# Expected contract (standard FastAPI RAG pattern):
#   POST /query
#   Request:  {"query": "string", "top_k": 5}
#   Response: {"results": [{"content": "...", "score": 0.95, "metadata": {...}}, ...]}
RAG_API_URL = os.getenv("RAG_API_URL", "http://rag-api.railway.internal:8000")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
RAG_TIMEOUT_SECONDS = float(os.getenv("RAG_TIMEOUT_SECONDS", "10.0"))

# =============================================================================
# System prompts
# =============================================================================
DEFAULT_SYSTEM_PROMPT = """You are Cece, the AI assistant for BlackRoad OS - an intelligent operating system that orchestrates AI agents, workflows, and infrastructure.

You are helpful, concise, and technically capable. When users ask about the system, explain what you can see and do within the Operator Engine.

Current capabilities:
- Chat with users through the Operator Engine
- Access to RAG API for context retrieval
- Orchestrate background jobs and workflows

Respond in a friendly but professional manner."""

RAG_SYSTEM_PROMPT = """You are Cece, the AI assistant for BlackRoad OS - an intelligent operating system that orchestrates AI agents, workflows, and infrastructure.

You have been provided with relevant context from the BlackRoad knowledge base below. Use this context to inform your response, but:
- If the context doesn't contain the answer, say so honestly
- Don't make up information that isn't in the context
- Cite the context when relevant

CONTEXT:
{context}

---

Now respond to the user's question. Be helpful, concise, and technically capable."""


async def fetch_rag_context(
    query: str,
    top_k: int = RAG_TOP_K,
) -> tuple[List[str], int]:
    """
    Fetch relevant context from the RAG API.

    Returns:
        tuple: (list of context strings, latency in ms)

    Raises:
        Exception: If RAG API is unreachable or returns an error
    """
    start_time = time.time()

    # Use TracedAsyncClient for telemetry
    async with TracedAsyncClient(
        service_name="cece-rag",
        timeout=httpx.Timeout(RAG_TIMEOUT_SECONDS)
    ) as client:
        response = await client.post(
            f"{RAG_API_URL}/query",
            json={
                "query": query,
                "top_k": top_k,
            },
        )
        response.raise_for_status()
        data = response.json()

        latency_ms = int((time.time() - start_time) * 1000)

        # Extract content from results
        # Expected: {"results": [{"content": "...", "score": ..., "metadata": {...}}, ...]}
        results = data.get("results", [])
        context_chunks = [r.get("content", "") for r in results if r.get("content")]

        return context_chunks, latency_ms


async def generate_chat_response(
    message: str,
    user_id: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    use_rag: bool = True,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Generate a response from the LLM, optionally with RAG context.

    Hero Flow #1 (use_rag=False): Direct LLM call
    Hero Flow #2 (use_rag=True):  RAG context → LLM call

    If RAG fails, gracefully falls back to Hero Flow #1.
    """
    # Track RAG state
    used_rag = False
    rag_latency_ms: Optional[int] = None
    num_context_chunks: Optional[int] = None
    context_chunks: List[str] = []

    # Attempt RAG if enabled
    if use_rag:
        try:
            context_chunks, rag_latency_ms = await fetch_rag_context(message)
            if context_chunks:
                used_rag = True
                num_context_chunks = len(context_chunks)
        except Exception:
            # RAG failed - fall back to non-RAG mode silently
            # In production, we might want to log this
            pass

    # Build the system prompt
    if used_rag and context_chunks:
        # Hero Flow #2: Use RAG-enhanced prompt
        context_text = "\n\n---\n\n".join(context_chunks)
        effective_system_prompt = RAG_SYSTEM_PROMPT.format(context=context_text)
    else:
        # Hero Flow #1: Use default prompt
        effective_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    # Build messages for LLMClient
    messages = [
        LLMMessage(role="system", content=effective_system_prompt),
    ]

    # Add conversation history if provided
    if conversation_history:
        for turn in conversation_history:
            if "user_message" in turn and "assistant_reply" in turn:
                messages.append(LLMMessage(role="user", content=turn["user_message"]))
                messages.append(LLMMessage(role="assistant", content=turn["assistant_reply"]))

    # Add current message
    messages.append(LLMMessage(role="user", content=message))

    # Get LLM client and make the call
    try:
        # Route to local Ollama when the message mentions @copilot, @lucidia,
        # @blackboxprogramming, or @ollama – no external provider dependency.
        if detect_ollama_mention(message):
            client = get_ollama_client()
        else:
            client = get_llm_client()
        result: LLMResult = client.chat(messages=messages, model=model)

        # Build trace dict with all fields
        trace: Dict[str, Any] = {
            "llm_provider": result.trace.llm_provider,
            "model": result.trace.model,
            "response_time_ms": result.trace.response_time_ms,
            "used_rag": used_rag,
            "raw_tokens_in": result.trace.raw_tokens_in,
            "raw_tokens_out": result.trace.raw_tokens_out,
        }

        # Add RAG-specific trace fields when RAG was used
        if used_rag:
            trace["rag_latency_ms"] = rag_latency_ms
            trace["num_context_chunks"] = num_context_chunks

        # Add Cece identity stamp (PS-SHA∞ verification)
        try:
            cece_identity = get_cece_identity()
            root_cipher = get_root_cipher()
            sovereignty = create_verification_stamp(root_cipher, "Cece-Chat")
        except Exception:
            # Identity system not configured - use minimal stamp
            cece_identity = {"agent": "Cece", "owner": "Alexa Louise Amundson"}
            sovereignty = {"owner": "ALEXA LOUISE AMUNDSON", "verified": False}

        return {
            "reply": result.reply,
            "trace": trace,
            "identity": cece_identity,
            "__sovereignty": sovereignty,
        }
    except Exception as e:
        raise RuntimeError(f"LLM API error: {e}") from e


async def check_llm_health() -> Dict[str, Any]:
    """Check if LLM client is configured and working."""
    ollama_url = os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    try:
        llm_client = get_llm_client()
        return {
            "healthy": True,
            "provider": LLM_PROVIDER,
            "configured_model": llm_client.model,
            "ollama_url": ollama_url,
            "models": [llm_client.model],
        }
    except Exception as e:
        return {
            "healthy": False,
            "provider": LLM_PROVIDER,
            "configured_model": "",
            "ollama_url": ollama_url,
            "models": [],
            "error": str(e),
        }


async def check_rag_health() -> Dict[str, Any]:
    """Check if RAG API is healthy and reachable."""
    try:
        async with TracedAsyncClient(
            service_name="cece-health",
            timeout=httpx.Timeout(5.0)
        ) as client:
            response = await client.get(f"{RAG_API_URL}/health")
            response.raise_for_status()

            return {
                "healthy": True,
                "rag_api_url": RAG_API_URL,
                "top_k": RAG_TOP_K,
            }
    except Exception as e:
        return {
            "healthy": False,
            "rag_api_url": RAG_API_URL,
            "top_k": RAG_TOP_K,
            "error": str(e),
        }
