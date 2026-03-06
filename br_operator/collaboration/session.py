# BlackRoad OS - Collaboration Session Management
# Session lifecycle for 30K concurrent collaborators
#
# @blackroad_name: Session Manager
# @operator: alexa.operator.v1

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4
from datetime import datetime

from .vector_clock import VectorClock
from .crdt import CRDT, RGA, LWWRegister, ORSet
from .shard import ShardManager
from .gossip import GossipProtocol


class ParticipantRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    OBSERVER = "observer"


class ParticipantStatus(str, Enum):
    CONNECTING = "connecting"
    ACTIVE = "active"
    IDLE = "idle"
    DISCONNECTED = "disconnected"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class CursorPosition:
    """Participant's cursor position in collaborative document."""

    path: str = ""  # JSON path or document position
    offset: int = 0
    selection_start: Optional[int] = None
    selection_end: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "offset": self.offset,
            "selection_start": self.selection_start,
            "selection_end": self.selection_end,
            "metadata": self.metadata,
        }


@dataclass
class Participant:
    """A participant in a collaboration session."""

    id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    entity_id: str = ""  # Agent or user ID
    entity_type: str = "agent"  # agent, human, system
    role: ParticipantRole = ParticipantRole.EDITOR
    status: ParticipantStatus = ParticipantStatus.CONNECTING
    shard_id: Optional[str] = None
    cursor: Optional[CursorPosition] = None
    last_operation_at: Optional[datetime] = None
    joined_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "role": self.role.value,
            "status": self.status.value,
            "shard_id": self.shard_id,
            "cursor": self.cursor.to_dict() if self.cursor else None,
            "last_operation_at": self.last_operation_at.isoformat() if self.last_operation_at else None,
            "joined_at": self.joined_at.isoformat(),
        }


@dataclass
class SessionSettings:
    """Settings for a collaboration session."""

    auto_snapshot_interval_ms: int = 60000
    max_operation_size_bytes: int = 1048576
    gossip_interval_ms: int = 100
    conflict_resolution: str = "lww"  # lww, manual, consensus
    ot_enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_snapshot_interval_ms": self.auto_snapshot_interval_ms,
            "max_operation_size_bytes": self.max_operation_size_bytes,
            "gossip_interval_ms": self.gossip_interval_ms,
            "conflict_resolution": self.conflict_resolution,
            "ot_enabled": self.ot_enabled,
        }


@dataclass
class SessionSnapshot:
    """Point-in-time snapshot of session state."""

    id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    state: Dict[str, Any] = field(default_factory=dict)
    vector_clock: VectorClock = field(default_factory=VectorClock)
    operation_count: int = 0
    size_bytes: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "state": self.state,
            "vector_clock": self.vector_clock.to_dict(),
            "operation_count": self.operation_count,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CollaborationSession:
    """A collaboration session for up to 30K concurrent participants.

    Uses CRDT state with gossip protocol for eventual consistency.
    Participants are distributed across shards for scalability.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    crdt_type: str = "rga"  # rga, lww-register, or-set
    max_participants: int = 30000
    settings: SessionSettings = field(default_factory=SessionSettings)

    # State
    state: Optional[CRDT] = None
    vector_clock: VectorClock = field(default_factory=VectorClock)
    participants: Dict[str, Participant] = field(default_factory=dict)
    operations: List[Dict[str, Any]] = field(default_factory=list)

    # Sharding
    shard_manager: Optional[ShardManager] = None
    assigned_shards: Set[str] = field(default_factory=set)
    primary_shard: Optional[str] = None

    # Gossip
    gossip: Optional[GossipProtocol] = None

    # Snapshots
    snapshots: List[SessionSnapshot] = field(default_factory=list)

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Initialize session state."""
        if self.state is None:
            self._init_state()

    def _init_state(self) -> None:
        """Initialize CRDT state based on type."""
        if self.crdt_type == "rga":
            self.state = RGA(node_id=self.id)
        elif self.crdt_type == "lww-register":
            self.state = LWWRegister(_value=None, node_id=self.id)
        elif self.crdt_type == "or-set":
            self.state = ORSet(node_id=self.id)
        else:
            self.state = RGA(node_id=self.id)

    @property
    def participant_count(self) -> int:
        return len(self.participants)

    def add_participant(
        self,
        entity_id: str,
        entity_type: str = "agent",
        role: ParticipantRole = ParticipantRole.EDITOR,
    ) -> Optional[Participant]:
        """Add a participant to the session."""
        if self.participant_count >= self.max_participants:
            return None

        if self.status != SessionStatus.ACTIVE:
            return None

        participant = Participant(
            session_id=self.id,
            entity_id=entity_id,
            entity_type=entity_type,
            role=role,
            status=ParticipantStatus.ACTIVE,
        )

        # Assign to shard
        if self.shard_manager:
            shard_id = self.shard_manager.assign_shard(participant.id)
            participant.shard_id = shard_id
            if shard_id:
                self.assigned_shards.add(shard_id)
                if self.primary_shard is None:
                    self.primary_shard = shard_id

        self.participants[participant.id] = participant
        self.updated_at = datetime.utcnow()

        return participant

    def remove_participant(self, participant_id: str) -> bool:
        """Remove a participant from the session."""
        if participant_id not in self.participants:
            return False

        participant = self.participants[participant_id]

        # Remove from shard
        if self.shard_manager and participant.shard_id:
            self.shard_manager.remove_participant(participant_id, participant.shard_id)

        del self.participants[participant_id]
        self.updated_at = datetime.utcnow()

        return True

    def get_participant(self, participant_id: str) -> Optional[Participant]:
        """Get a participant by ID."""
        return self.participants.get(participant_id)

    def update_cursor(self, participant_id: str, cursor: CursorPosition) -> bool:
        """Update a participant's cursor position."""
        if participant_id not in self.participants:
            return False

        self.participants[participant_id].cursor = cursor
        return True

    def apply_operation(
        self,
        operation: Dict[str, Any],
        participant_id: str,
    ) -> Dict[str, Any]:
        """Apply an operation to the session state."""
        # Validate participant
        if participant_id not in self.participants:
            raise ValueError("Participant not in session")

        participant = self.participants[participant_id]
        if participant.role == ParticipantRole.VIEWER:
            raise ValueError("Viewers cannot apply operations")

        # Increment vector clock
        self.vector_clock = self.vector_clock.increment(participant_id)

        # Add metadata to operation
        operation["participant_id"] = participant_id
        operation["vector_clock"] = self.vector_clock.to_dict()
        operation["timestamp"] = datetime.utcnow().isoformat()

        # Apply to CRDT state
        op_type = operation.get("type")
        if isinstance(self.state, RGA):
            if op_type == "insert":
                index = operation.get("index", 0)
                value = operation.get("value")
                self.state = self.state.insert(index, value)
            elif op_type == "delete":
                index = operation.get("index", 0)
                self.state = self.state.delete(index)

        # Store operation
        self.operations.append(operation)

        # Update participant
        participant.last_operation_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

        # Propagate via gossip
        if self.gossip:
            self.gossip.add_operation(operation)

        return {
            "success": True,
            "vector_clock": self.vector_clock.to_dict(),
            "operation_id": operation.get("id", str(uuid4())),
        }

    def create_snapshot(self) -> SessionSnapshot:
        """Create a snapshot of current state."""
        import json

        state_dict = self.state.to_dict() if self.state else {}
        state_json = json.dumps(state_dict)

        snapshot = SessionSnapshot(
            session_id=self.id,
            state=state_dict,
            vector_clock=VectorClock.from_dict(self.vector_clock.to_dict()),
            operation_count=len(self.operations),
            size_bytes=len(state_json.encode()),
        )

        self.snapshots.append(snapshot)
        return snapshot

    def get_state_delta(self, since_clock: VectorClock) -> Dict[str, Any]:
        """Get operations since a given vector clock."""
        delta_ops = []

        for op in self.operations:
            op_clock = VectorClock.from_dict(op.get("vector_clock", {}))
            if op_clock.happens_after(since_clock):
                delta_ops.append(op)

        return {
            "operations": delta_ops,
            "vector_clock": self.vector_clock.to_dict(),
            "is_delta": True,
        }

    def close(self) -> None:
        """Close the session."""
        self.status = SessionStatus.CLOSING

        # Create final snapshot
        self.create_snapshot()

        # Stop gossip
        if self.gossip:
            self.gossip.stop()

        # Mark all participants as disconnected
        for participant in self.participants.values():
            participant.status = ParticipantStatus.DISCONNECTED

        self.status = SessionStatus.CLOSED
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "crdt_type": self.crdt_type,
            "participant_count": self.participant_count,
            "max_participants": self.max_participants,
            "vector_clock": self.vector_clock.to_dict(),
            "settings": self.settings.to_dict(),
            "assigned_shards": list(self.assigned_shards),
            "primary_shard": self.primary_shard,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class SessionManager:
    """Manages multiple collaboration sessions.

    Handles session lifecycle, shard assignment, and gossip coordination.
    """

    sessions: Dict[str, CollaborationSession] = field(default_factory=dict)
    shard_manager: ShardManager = field(default_factory=ShardManager)

    async def create_session(
        self,
        name: str,
        crdt_type: str = "rga",
        max_participants: int = 30000,
        settings: Optional[SessionSettings] = None,
    ) -> CollaborationSession:
        """Create a new collaboration session."""
        session = CollaborationSession(
            name=name,
            crdt_type=crdt_type,
            max_participants=max_participants,
            settings=settings or SessionSettings(),
            shard_manager=self.shard_manager,
        )

        # Initialize gossip for session's primary shard
        if session.primary_shard:
            session.gossip = GossipProtocol(
                shard_id=session.primary_shard,
                gossip_interval_ms=session.settings.gossip_interval_ms,
            )

        self.sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Optional[CollaborationSession]:
        """Get a session by ID."""
        return self.sessions.get(session_id)

    async def close_session(self, session_id: str) -> bool:
        """Close a session."""
        if session_id not in self.sessions:
            return False

        session = self.sessions[session_id]
        session.close()
        return True

    def list_sessions(
        self,
        status: Optional[SessionStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[CollaborationSession]:
        """List sessions with optional filtering."""
        sessions = list(self.sessions.values())

        if status:
            sessions = [s for s in sessions if s.status == status]

        return sessions[offset:offset + limit]

    async def join_session(
        self,
        session_id: str,
        entity_id: str,
        entity_type: str = "agent",
        role: ParticipantRole = ParticipantRole.EDITOR,
    ) -> Optional[Dict[str, Any]]:
        """Join a session and get connection details."""
        session = self.get_session(session_id)
        if not session:
            return None

        participant = session.add_participant(entity_id, entity_type, role)
        if not participant:
            return None

        # Get current state for new participant
        state = session.state.to_dict() if session.state else {}

        return {
            "participant": participant.to_dict(),
            "shard_id": participant.shard_id,
            "state": state,
            "vector_clock": session.vector_clock.to_dict(),
            "websocket_url": f"wss://collab-{participant.shard_id}.blackroad.io/v1/ws",
        }

    async def leave_session(
        self,
        session_id: str,
        participant_id: str,
    ) -> bool:
        """Leave a session."""
        session = self.get_session(session_id)
        if not session:
            return False

        return session.remove_participant(participant_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get session manager statistics."""
        active = sum(1 for s in self.sessions.values() if s.status == SessionStatus.ACTIVE)
        total_participants = sum(s.participant_count for s in self.sessions.values())

        return {
            "total_sessions": len(self.sessions),
            "active_sessions": active,
            "total_participants": total_participants,
            "shard_stats": self.shard_manager.to_dict(),
        }
