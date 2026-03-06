"""Deploy Service - Hub for triggering deployments across agents.

This is the brain that receives iPhone/Shortcut POST requests and
dispatches commands to connected br-agents on Mac, Pi, etc.

@amundson 0.1.0
@operator alexa.operator.v1
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================
# MODELS
# ============================================

class DeployTarget(str, Enum):
    """Valid deploy targets."""
    WEB = "web"
    API = "api"
    OPERATOR = "operator"
    WORKERS = "workers"
    PI_MESH = "pi-mesh"
    ALL = "all"


class DeployEnv(str, Enum):
    """Deployment environments."""
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"


class DeployStatus(str, Enum):
    """Status of a deployment."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL = "partial"  # Some targets succeeded, some failed
    FAILED = "failed"


class ServiceStatus(str, Enum):
    """Individual service status."""
    HEALTHY = "healthy"      # ✅
    DEGRADED = "degraded"    # ⚠️
    DOWN = "down"            # ❌
    UNKNOWN = "unknown"      # 🪧


class DeployRequest(BaseModel):
    """Request to trigger a deployment."""
    target: DeployTarget = DeployTarget.ALL
    env: DeployEnv = DeployEnv.PROD
    reason: Optional[str] = None
    dry_run: bool = False


class ServiceResult(BaseModel):
    """Result for a single service in a deployment."""
    service: str
    status: ServiceStatus
    message: Optional[str] = None
    duration_ms: Optional[int] = None
    agent: Optional[str] = None  # Which agent handled it


class DeployResponse(BaseModel):
    """Response from a deployment request."""
    deploy_id: UUID
    target: DeployTarget
    env: DeployEnv
    status: DeployStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    reason: Optional[str] = None
    results: List[ServiceResult] = Field(default_factory=list)
    summary: Optional[str] = None


# ============================================
# AGENT REGISTRY (In-Memory)
# ============================================

class AgentConnection(BaseModel):
    """Represents a connected br-agent."""
    agent_id: str
    machine_id: str
    connected_at: datetime
    last_heartbeat: datetime
    capabilities: List[str] = Field(default_factory=list)
    actions: Dict[str, Any] = Field(default_factory=dict)


# Connected agents (in production, use Redis or WebSocket manager)
_connected_agents: Dict[str, AgentConnection] = {}


# ============================================
# DEPLOY MAPPINGS
# ============================================

# What each target means in terms of actions
DEPLOY_TARGETS = {
    DeployTarget.WEB: {
        "agents": ["mac-main", "railway-agent"],
        "actions": {
            "mac-main": "build_web",
            "railway-agent": "deploy_web",
        },
        "services": ["blackroad-os-web", "blackroad-hello"],
    },
    DeployTarget.API: {
        "agents": ["mac-main", "railway-agent"],
        "actions": {
            "mac-main": "build_api",
            "railway-agent": "deploy_api",
        },
        "services": ["blackroad-cece-operator"],
    },
    DeployTarget.OPERATOR: {
        "agents": ["railway-agent"],
        "actions": {
            "railway-agent": "deploy_operator",
        },
        "services": ["blackroad-cece-operator"],
    },
    DeployTarget.WORKERS: {
        "agents": ["mac-main"],
        "actions": {
            "mac-main": "deploy_workers",
        },
        "services": [
            "blackroad-router", "blackroad-api-gateway", "cece",
            "blackroad-identity", "blackroad-billing", "blackroad-status",
        ],
    },
    DeployTarget.PI_MESH: {
        "agents": ["pi-1", "pi-2", "pi-3"],
        "actions": {
            "pi-1": "refresh_agent",
            "pi-2": "refresh_agent",
            "pi-3": "refresh_agent",
        },
        "services": ["pi-mesh-agent"],
    },
    DeployTarget.ALL: {
        "agents": ["mac-main", "railway-agent", "pi-1", "pi-2", "pi-3"],
        "actions": {
            "mac-main": ["build_web", "build_api", "deploy_workers"],
            "railway-agent": ["deploy_web", "deploy_api", "deploy_operator"],
            "pi-1": "refresh_agent",
            "pi-2": "refresh_agent",
            "pi-3": "refresh_agent",
        },
        "services": ["web", "api", "workers", "pi-mesh"],
    },
}


# ============================================
# DEPLOY HISTORY
# ============================================

_deploy_history: Dict[UUID, DeployResponse] = {}


# ============================================
# SERVICE CLASS
# ============================================

class DeployService:
    """Orchestrates deployments across connected agents."""

    def __init__(self):
        self.agents = _connected_agents
        self.history = _deploy_history

    async def deploy(self, request: DeployRequest) -> DeployResponse:
        """Execute a deployment.

        In production, this would:
        1. Look up which agents are needed for the target
        2. Send commands to each agent via WebSocket
        3. Collect results and aggregate status
        4. Log to ledger

        For now, we simulate this and return expected structure.
        """
        deploy_id = uuid4()
        started_at = datetime.now(timezone.utc)

        logger.info(f"Deploy {deploy_id}: target={request.target}, env={request.env}")

        target_config = DEPLOY_TARGETS.get(request.target, {})
        required_agents = target_config.get("agents", [])
        actions = target_config.get("actions", {})
        services = target_config.get("services", [])

        results: List[ServiceResult] = []

        # Check which agents are connected
        for agent_id in required_agents:
            if agent_id in self.agents:
                # Agent is connected - would send command here
                agent = self.agents[agent_id]
                action = actions.get(agent_id)

                if request.dry_run:
                    results.append(ServiceResult(
                        service=agent_id,
                        status=ServiceStatus.HEALTHY,
                        message=f"[DRY RUN] Would execute: {action}",
                        agent=agent_id,
                    ))
                else:
                    # Simulate execution (in production, send via WebSocket)
                    results.append(ServiceResult(
                        service=agent_id,
                        status=ServiceStatus.HEALTHY,
                        message=f"Executed: {action}",
                        duration_ms=1500,
                        agent=agent_id,
                    ))
            else:
                # Agent not connected
                results.append(ServiceResult(
                    service=agent_id,
                    status=ServiceStatus.UNKNOWN,
                    message="Agent not connected",
                    agent=agent_id,
                ))

        # Determine overall status
        statuses = [r.status for r in results]
        if all(s == ServiceStatus.HEALTHY for s in statuses):
            overall_status = DeployStatus.SUCCESS
        elif all(s in (ServiceStatus.DOWN, ServiceStatus.UNKNOWN) for s in statuses):
            overall_status = DeployStatus.FAILED
        elif any(s == ServiceStatus.HEALTHY for s in statuses):
            overall_status = DeployStatus.PARTIAL
        else:
            overall_status = DeployStatus.FAILED

        # Build summary with emojis
        emoji_map = {
            ServiceStatus.HEALTHY: "✅",
            ServiceStatus.DEGRADED: "⚠️",
            ServiceStatus.DOWN: "❌",
            ServiceStatus.UNKNOWN: "🪧",
        }
        summary_parts = [f"{r.service}: {emoji_map.get(r.status, '?')}" for r in results]
        summary = " | ".join(summary_parts)

        completed_at = datetime.now(timezone.utc)

        response = DeployResponse(
            deploy_id=deploy_id,
            target=request.target,
            env=request.env,
            status=overall_status,
            started_at=started_at,
            completed_at=completed_at,
            reason=request.reason,
            results=results,
            summary=summary,
        )

        # Store in history
        self.history[deploy_id] = response

        logger.info(f"Deploy {deploy_id} completed: {overall_status.value}")
        return response

    def register_agent(self, agent_id: str, machine_id: str, capabilities: List[str], actions: Dict[str, Any]) -> AgentConnection:
        """Register a connected agent."""
        now = datetime.now(timezone.utc)
        connection = AgentConnection(
            agent_id=agent_id,
            machine_id=machine_id,
            connected_at=now,
            last_heartbeat=now,
            capabilities=capabilities,
            actions=actions,
        )
        self.agents[agent_id] = connection
        logger.info(f"Agent registered: {agent_id} ({machine_id})")
        return connection

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister a disconnected agent."""
        if agent_id in self.agents:
            del self.agents[agent_id]
            logger.info(f"Agent unregistered: {agent_id}")
            return True
        return False

    def heartbeat(self, agent_id: str) -> bool:
        """Update agent heartbeat."""
        if agent_id in self.agents:
            self.agents[agent_id].last_heartbeat = datetime.now(timezone.utc)
            return True
        return False

    def list_agents(self) -> List[AgentConnection]:
        """List all connected agents."""
        return list(self.agents.values())

    def get_deploy(self, deploy_id: UUID) -> Optional[DeployResponse]:
        """Get a deployment by ID."""
        return self.history.get(deploy_id)

    def list_deploys(self, limit: int = 20) -> List[DeployResponse]:
        """List recent deployments."""
        deploys = sorted(
            self.history.values(),
            key=lambda d: d.started_at,
            reverse=True,
        )
        return deploys[:limit]


# ============================================
# SINGLETON
# ============================================

_deploy_service: Optional[DeployService] = None


def get_deploy_service() -> DeployService:
    """Get or create the deploy service singleton."""
    global _deploy_service
    if _deploy_service is None:
        _deploy_service = DeployService()
    return _deploy_service
