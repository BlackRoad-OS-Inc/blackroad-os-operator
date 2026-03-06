"""
Pydantic models for BlackRoad OS Operator API.
Hero Flow #1 request/response contracts.

Every response carries:
- trace: what tools + models were used (capability layer)
- identity: which agent is speaking (identity layer)
- sovereignty: which human/entity owns it (ownership layer)

@owner Alexa Louise Amundson
@system BlackRoad OS
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Request model for POST /chat endpoint."""

    message: str = Field(..., min_length=1, description="The user's message to Cece")
    userId: Optional[str] = Field(None, description="Optional user identifier for context")
    model: Optional[str] = Field(None, description="Override the default LLM model")


class ChatTrace(BaseModel):
    """
    Trace metadata returned with chat responses.

    This is about capability usage - which wands were used, not who is wielding them.
    """

    llm_provider: str = Field(..., description="LLM provider used (e.g., 'openai')")
    model: str = Field(..., description="Model name used for generation")
    used_rag: bool = Field(..., description="Whether RAG context was retrieved")
    response_time_ms: float = Field(..., description="Total response time in milliseconds")
    raw_tokens_in: Optional[int] = Field(None, description="Input tokens consumed")
    raw_tokens_out: Optional[int] = Field(None, description="Output tokens generated")
    credential_alias: Optional[str] = Field(None, description="Credential alias used")
    rag_latency_ms: Optional[float] = Field(None, description="RAG API latency in ms (when used)")
    num_context_chunks: Optional[int] = Field(None, description="Number of context chunks retrieved")


class ChatIdentity(BaseModel):
    """
    Identity of the agent responding.

    This is the stable, BlackRoad-native identity that exists
    independent of any API key or external vendor.
    """

    agent: str = Field(..., description="Agent name")
    fingerprint: str = Field(..., description="PS-SHA∞ fingerprint")
    owner: str = Field(..., description="Owner of this agent")
    infrastructure: str = Field(default="BlackRoad OS", description="Infrastructure")
    root_fingerprint: Optional[str] = Field(None, description="Root identity fingerprint")


class ChatSovereignty(BaseModel):
    """
    Sovereignty stamp proving ownership and verification.

    This is the law: every governed response carries a sovereignty stamp.
    """

    owner: str = Field(..., description="Ultimate owner (UPPERCASE)")
    verified: bool = Field(..., description="Cryptographically verified")
    zeta_time: Optional[str] = Field(None, description="Zeta-time stamp")
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp")
    fingerprint: Optional[str] = Field(None, description="Root PS-SHA∞ fingerprint")
    context: Optional[str] = Field(None, description="Verification context")
    signature: Optional[str] = Field(None, description="Verification signature")


class ChatResponse(BaseModel):
    """
    Response model for POST /chat endpoint.

    A complete BlackRoad response with identity framing.
    Every governed response carries trace + identity + sovereignty.
    """

    reply: str = Field(..., description="Cece's response message")
    trace: ChatTrace = Field(..., description="Request trace metadata (capability layer)")
    identity: Optional[ChatIdentity] = Field(None, description="Agent identity (identity layer)")

    # Pydantic v2 configuration using ConfigDict
    model_config = ConfigDict(extra="allow")  # Allow __sovereignty as extra field


class LLMHealthResponse(BaseModel):
    """Response model for GET /llm/health endpoint."""

    healthy: bool
    models: list[str]
    provider: str
    configured_model: str
    ollama_url: str
    error: Optional[str] = None


class RAGHealthResponse(BaseModel):
    """Response model for GET /rag/health endpoint."""

    healthy: bool
    rag_api_url: str
    top_k: int
    error: Optional[str] = None
