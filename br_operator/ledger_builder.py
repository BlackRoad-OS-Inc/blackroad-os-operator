"""Ledger event builder for BlackRoad OS Operator.

Python equivalent of lib/ledger-builder.ts for server-side event construction.

This ensures all mesh/agent/infra events have required fields and conform
to the Amundson governance contract.

Usage:
    from br_operator.ledger_builder import (
        build_mesh_connect_event,
        build_agent_invoke_event,
        build_operator_infra_event,
        validate_ledger_event,
    )

@amundson 0.1.0
@governor alice.governor.v1
@operator alexa.operator.v1
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from br_operator.models.policy import (
    LedgerLevel,
    PolicyEffect,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
)
from br_operator.models.ledger import (
    Layer,
    LedgerActor,
    LedgerDecision,
    LedgerEventCreate,
)

# ============================================
# CONSTANTS
# ============================================

LANGUAGE_VERSION = "0.1.0"

MESH_POLICY_PACK = {
    "name": "mesh-policies",
    "version": "1.0.0",
}

INFRA_POLICY_PACK = {
    "name": "infra-policies",
    "version": "1.0.0",
}

# Ledger level precedence
LEDGER_LEVEL_RANK: Dict[LedgerLevel, int] = {
    LedgerLevel.NONE: 0,
    LedgerLevel.DECISION: 1,
    LedgerLevel.ACTION: 2,
    LedgerLevel.FULL: 3,
}


# ============================================
# HELPERS
# ============================================

def _resolve_level(required: LedgerLevel, override: Optional[LedgerLevel] = None) -> LedgerLevel:
    """Ensure actual ledger level is >= required level."""
    if override is None:
        return required

    if LEDGER_LEVEL_RANK[override] < LEDGER_LEVEL_RANK[required]:
        return required

    return override


def _resolve_layer(host: str) -> Layer:
    """Resolve the layer from the host."""
    if "gov." in host or ".systems" in host:
        return Layer.GOVERNANCE
    if "mesh." in host or "agents." in host:
        return Layer.MESH
    if "api.blackroad.io" in host:
        return Layer.GATEWAY
    if "db." in host or "infra." in host or "ops." in host:
        return Layer.INFRA
    return Layer.EXPERIENCE


def _resolve_policy_scope(host: str) -> str:
    """Resolve the policy scope from the host."""
    if host.startswith("mesh.") or host.endswith(".blackroad.network"):
        return "mesh.*"
    if host.startswith("agents."):
        return "agents.*"
    if host.startswith("infra.") or host.startswith("ops."):
        return "infra.*"
    if host.startswith("gov."):
        return "gov.api.*"
    if host.startswith("edu."):
        return "edu.*"
    if host.startswith("homework."):
        return "homework.*"
    return "app.*"


def _effect_to_decision(effect: PolicyEffect) -> LedgerDecision:
    """Convert PolicyEffect to LedgerDecision."""
    return LedgerDecision(effect.value)


# ============================================
# BUILDER OPTIONS
# ============================================

class LedgerEventOptions:
    """Options for building a ledger event."""

    def __init__(
        self,
        request: PolicyEvaluateRequest,
        response: PolicyEvaluateResponse,
        resource_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ledger_level_override: Optional[LedgerLevel] = None,
        request_context: Optional[Dict[str, Any]] = None,
        response_summary: Optional[Dict[str, Any]] = None,
        intent_id: Optional[str] = None,
        sequence_num: int = 0,
        policy_pack_name: Optional[str] = None,
        policy_pack_version: Optional[str] = None,
    ):
        self.request = request
        self.response = response
        self.resource_id = resource_id
        self.metadata = metadata or {}
        self.ledger_level_override = ledger_level_override
        self.request_context = request_context
        self.response_summary = response_summary
        self.intent_id = intent_id
        self.sequence_num = sequence_num
        self.policy_pack_name = policy_pack_name
        self.policy_pack_version = policy_pack_version


# ============================================
# CORE BUILDER
# ============================================

def build_ledger_event(options: LedgerEventOptions) -> LedgerEventCreate:
    """Build a ledger event from a policy evaluation request/response pair.

    This is the canonical way to create ledger events. It ensures:
    1. All required fields are present
    2. Ledger level is >= required_ledger_level
    3. Location fields are consistent with the host
    4. Evidence from the request is preserved
    """
    request = options.request
    response = options.response

    host = request.context.request_metadata.host or "app.blackroad.io"
    service = request.context.request_metadata.service or "unknown"
    correlation_id = request.context.request_metadata.correlation_id or str(uuid4())

    ledger_level = _resolve_level(response.required_ledger_level, options.ledger_level_override)

    # Build metadata with pack info
    metadata = {
        **options.metadata,
        "language_version": LANGUAGE_VERSION,
    }

    if options.policy_pack_name:
        metadata["policy_pack"] = options.policy_pack_name
    if options.policy_pack_version:
        metadata["policy_pack_version"] = options.policy_pack_version

    return LedgerEventCreate(
        # Identity
        correlation_id=correlation_id,
        intent_id=options.intent_id,
        sequence_num=options.sequence_num,

        # Location
        layer=_resolve_layer(host),
        host=host,
        service=service,
        policy_scope=_resolve_policy_scope(host),

        # Actor
        actor=LedgerActor(
            user_id=request.subject.user_id,
            role=request.subject.role,
            agent_id=request.subject.attributes.get("agent_id") if request.subject.attributes else None,
            delegation_id=None,  # Set from claims if present
        ),

        # Action
        action=request.action,
        resource_type=request.resource.type,
        resource_id=options.resource_id or request.resource.id,

        # Decision
        decision=_effect_to_decision(response.decision),
        policy_id=response.policy_id,
        policy_version=response.policy_version,

        # Evidence
        asserted_facts=request.context.asserted_facts,
        fact_evidence=request.context.fact_evidence,
        claims=request.context.claims,

        # Metadata
        ledger_level=ledger_level,
        metadata=metadata,
        request_context=options.request_context if ledger_level == LedgerLevel.FULL else None,
        response_summary=options.response_summary if ledger_level == LedgerLevel.FULL else None,
    )


# ============================================
# MESH/AGENT HELPERS
# ============================================

def build_mesh_connect_event(
    request: PolicyEvaluateRequest,
    response: PolicyEvaluateResponse,
    connection_id: str,
    connection_type: str = "websocket",
    client_info: Optional[Dict[str, Any]] = None,
) -> LedgerEventCreate:
    """Build a ledger event for mesh connection."""
    return build_ledger_event(LedgerEventOptions(
        request=request,
        response=response,
        resource_id=connection_id,
        metadata={
            "connection_type": connection_type,
            "client_info": client_info or {},
            "event_type": "mesh:connected",
        },
        policy_pack_name=MESH_POLICY_PACK["name"],
        policy_pack_version=MESH_POLICY_PACK["version"],
        request_context={
            "connection_id": connection_id,
            "connection_type": connection_type,
        },
        response_summary={
            "connected": response.decision in (PolicyEffect.ALLOW, PolicyEffect.WARN, PolicyEffect.SHADOW_DENY),
        },
    ))


def build_mesh_route_event(
    request: PolicyEvaluateRequest,
    response: PolicyEvaluateResponse,
    message_id: str,
    source: str,
    destination: str,
) -> LedgerEventCreate:
    """Build a ledger event for mesh message routing."""
    return build_ledger_event(LedgerEventOptions(
        request=request,
        response=response,
        resource_id=message_id,
        metadata={
            "source": source,
            "destination": destination,
            "event_type": "mesh:routed",
        },
        policy_pack_name=MESH_POLICY_PACK["name"],
        policy_pack_version=MESH_POLICY_PACK["version"],
    ))


def build_agent_invoke_event(
    request: PolicyEvaluateRequest,
    response: PolicyEvaluateResponse,
    invocation_id: str,
    agent_id: str,
    capability: str,
    payload_summary: Optional[Dict[str, Any]] = None,
) -> LedgerEventCreate:
    """Build a ledger event for agent invocation."""
    return build_ledger_event(LedgerEventOptions(
        request=request,
        response=response,
        resource_id=invocation_id,
        metadata={
            "agent_id": agent_id,
            "capability": capability,
            "payload_summary": payload_summary or {},
            "event_type": "agent:invoked",
        },
        policy_pack_name=MESH_POLICY_PACK["name"],
        policy_pack_version=MESH_POLICY_PACK["version"],
        request_context={
            "agent_id": agent_id,
            "capability": capability,
        },
        response_summary={
            "invoked": response.decision in (PolicyEffect.ALLOW, PolicyEffect.WARN, PolicyEffect.SHADOW_DENY),
        },
    ))


def build_agent_register_event(
    request: PolicyEvaluateRequest,
    response: PolicyEvaluateResponse,
    agent_id: str,
    agent_name: str,
    capabilities: List[str],
) -> LedgerEventCreate:
    """Build a ledger event for agent registration."""
    return build_ledger_event(LedgerEventOptions(
        request=request,
        response=response,
        resource_id=agent_id,
        metadata={
            "agent_name": agent_name,
            "capabilities": capabilities,
            "event_type": "agent:registered",
        },
        policy_pack_name=MESH_POLICY_PACK["name"],
        policy_pack_version=MESH_POLICY_PACK["version"],
    ))


# ============================================
# INFRA HELPERS
# ============================================

def build_operator_infra_event(
    request: PolicyEvaluateRequest,
    response: PolicyEvaluateResponse,
    operation_id: str,
    operation_type: str,
    target_service: str,
    details: Optional[Dict[str, Any]] = None,
) -> LedgerEventCreate:
    """Build a ledger event for infrastructure operations."""
    return build_ledger_event(LedgerEventOptions(
        request=request,
        response=response,
        resource_id=operation_id,
        metadata={
            "operation_type": operation_type,
            "target_service": target_service,
            "details": details or {},
            "event_type": f"operator:{operation_type}",
        },
        policy_pack_name=INFRA_POLICY_PACK["name"],
        policy_pack_version=INFRA_POLICY_PACK["version"],
        request_context={
            "operation_id": operation_id,
            "operation_type": operation_type,
            "target_service": target_service,
        },
        response_summary={
            "executed": response.decision in (PolicyEffect.ALLOW, PolicyEffect.WARN, PolicyEffect.SHADOW_DENY),
        },
    ))


def build_db_operation_event(
    request: PolicyEvaluateRequest,
    response: PolicyEvaluateResponse,
    operation_id: str,
    operation_type: str,  # migrate, backup, restore
    database: str,
    details: Optional[Dict[str, Any]] = None,
) -> LedgerEventCreate:
    """Build a ledger event for database operations."""
    return build_ledger_event(LedgerEventOptions(
        request=request,
        response=response,
        resource_id=operation_id,
        metadata={
            "operation_type": operation_type,
            "database": database,
            "details": details or {},
            "event_type": f"operator:{operation_type}",
        },
        policy_pack_name=INFRA_POLICY_PACK["name"],
        policy_pack_version=INFRA_POLICY_PACK["version"],
        request_context={
            "operation_id": operation_id,
            "database": database,
        },
        response_summary={
            "executed": response.decision in (PolicyEffect.ALLOW, PolicyEffect.WARN, PolicyEffect.SHADOW_DENY),
        },
    ))


# ============================================
# VALIDATION
# ============================================

def validate_ledger_event(event: LedgerEventCreate) -> None:
    """Validate a ledger event has all required fields.

    Raises ValueError if validation fails.
    """
    required_fields = [
        ("correlation_id", event.correlation_id),
        ("layer", event.layer),
        ("host", event.host),
        ("service", event.service),
        ("policy_scope", event.policy_scope),
        ("actor", event.actor),
        ("action", event.action),
        ("resource_type", event.resource_type),
        ("decision", event.decision),
        ("ledger_level", event.ledger_level),
    ]

    for field_name, value in required_fields:
        if value is None:
            raise ValueError(f"Missing required field: {field_name}")

    # Actor validation
    if not event.actor.user_id and not event.actor.agent_id:
        raise ValueError("Actor must have either user_id or agent_id")

    if not event.actor.role:
        raise ValueError("Actor must have a role")

    # Full fidelity validation
    if event.ledger_level == LedgerLevel.FULL:
        if not event.request_context:
            # Warning, not error - some full events may not have context
            pass
