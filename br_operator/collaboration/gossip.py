# BlackRoad OS - Gossip Protocol
# Eventual consistency for 30K collaboration
#
# @blackroad_name: Gossip Protocol
# @operator: alexa.operator.v1

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4
import asyncio
import time
import random

from .vector_clock import VectorClock


@dataclass
class GossipMessage:
    """A gossip message for state synchronization."""

    id: str = field(default_factory=lambda: str(uuid4()))
    from_shard: str = ""
    to_shard: str = ""
    vector_clock: VectorClock = field(default_factory=VectorClock)
    digest: str = ""  # Hash of current state
    operations: List[Dict[str, Any]] = field(default_factory=list)
    anti_entropy: bool = False  # Request full state sync
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from_shard": self.from_shard,
            "to_shard": self.to_shard,
            "vector_clock": self.vector_clock.to_dict(),
            "digest": self.digest,
            "operations": self.operations,
            "anti_entropy": self.anti_entropy,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GossipMessage:
        return cls(
            id=data["id"],
            from_shard=data["from_shard"],
            to_shard=data["to_shard"],
            vector_clock=VectorClock.from_dict(data["vector_clock"]),
            digest=data["digest"],
            operations=data["operations"],
            anti_entropy=data.get("anti_entropy", False),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class GossipResponse:
    """Response to a gossip message."""

    from_shard: str
    vector_clock: VectorClock
    missing_operations: List[Dict[str, Any]] = field(default_factory=list)
    in_sync: bool = False
    full_state: Optional[Dict[str, Any]] = None  # For anti-entropy

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_shard": self.from_shard,
            "vector_clock": self.vector_clock.to_dict(),
            "missing_operations": self.missing_operations,
            "in_sync": self.in_sync,
            "full_state": self.full_state,
        }


@dataclass
class GossipProtocol:
    """Gossip protocol for eventual consistency across shards.

    Uses push-pull gossip with anti-entropy for convergence.
    Gossip interval: 100ms for sub-200ms eventual consistency.
    """

    shard_id: str
    peers: Set[str] = field(default_factory=set)
    vector_clock: VectorClock = field(default_factory=VectorClock)
    pending_operations: List[Dict[str, Any]] = field(default_factory=list)
    known_clocks: Dict[str, VectorClock] = field(default_factory=dict)

    # Configuration
    gossip_interval_ms: int = 100
    fanout: int = 2  # Number of peers to gossip with each round
    max_operations_per_message: int = 100
    anti_entropy_interval_s: int = 60

    # Callbacks
    on_receive_operations: Optional[Callable[[List[Dict]], None]] = None
    on_send_message: Optional[Callable[[str, GossipMessage], None]] = None

    # State
    _running: bool = False
    _last_anti_entropy: float = 0

    def add_peer(self, peer_id: str) -> None:
        """Add a peer shard."""
        self.peers.add(peer_id)
        if peer_id not in self.known_clocks:
            self.known_clocks[peer_id] = VectorClock()

    def remove_peer(self, peer_id: str) -> None:
        """Remove a peer shard."""
        self.peers.discard(peer_id)
        self.known_clocks.pop(peer_id, None)

    def add_operation(self, operation: Dict[str, Any]) -> None:
        """Add a local operation to be gossiped."""
        # Increment our clock
        self.vector_clock = self.vector_clock.increment(self.shard_id)

        # Add clock to operation
        operation["vector_clock"] = self.vector_clock.to_dict()
        operation["shard_id"] = self.shard_id

        self.pending_operations.append(operation)

    def _select_peers(self) -> List[str]:
        """Select random peers for gossip (fan-out)."""
        if len(self.peers) <= self.fanout:
            return list(self.peers)
        return random.sample(list(self.peers), self.fanout)

    def _compute_digest(self) -> str:
        """Compute a digest of current state for comparison."""
        import hashlib
        clock_str = str(sorted(self.vector_clock.clock.items()))
        return hashlib.sha256(clock_str.encode()).hexdigest()[:16]

    def create_gossip_message(self, to_shard: str) -> GossipMessage:
        """Create a gossip message for a peer."""
        # Get operations the peer hasn't seen
        peer_clock = self.known_clocks.get(to_shard, VectorClock())
        ops_to_send = []

        for op in self.pending_operations[-self.max_operations_per_message:]:
            op_clock = VectorClock.from_dict(op.get("vector_clock", {}))
            if op_clock.happens_after(peer_clock):
                ops_to_send.append(op)

        # Check if we need anti-entropy
        need_anti_entropy = (
            time.time() - self._last_anti_entropy > self.anti_entropy_interval_s
        )

        return GossipMessage(
            from_shard=self.shard_id,
            to_shard=to_shard,
            vector_clock=self.vector_clock,
            digest=self._compute_digest(),
            operations=ops_to_send,
            anti_entropy=need_anti_entropy,
        )

    def receive_gossip(self, message: GossipMessage) -> GossipResponse:
        """Handle an incoming gossip message."""
        # Update our knowledge of the sender's clock
        self.known_clocks[message.from_shard] = message.vector_clock

        # Find operations we have that they don't
        their_clock = message.vector_clock
        missing_ops = []

        for op in self.pending_operations:
            op_clock = VectorClock.from_dict(op.get("vector_clock", {}))
            if op_clock.happens_after(their_clock):
                missing_ops.append(op)

        # Apply operations we received
        new_ops = []
        for op in message.operations:
            op_clock = VectorClock.from_dict(op.get("vector_clock", {}))
            if op_clock.happens_after(self.vector_clock):
                new_ops.append(op)
                self.pending_operations.append(op)

        # Merge clocks
        self.vector_clock = self.vector_clock.merge(message.vector_clock)

        # Notify about new operations
        if new_ops and self.on_receive_operations:
            self.on_receive_operations(new_ops)

        # Check if in sync
        in_sync = self._compute_digest() == message.digest

        # Handle anti-entropy request
        full_state = None
        if message.anti_entropy:
            self._last_anti_entropy = time.time()
            full_state = {
                "operations": self.pending_operations[-1000:],  # Last 1000 ops
            }

        return GossipResponse(
            from_shard=self.shard_id,
            vector_clock=self.vector_clock,
            missing_operations=missing_ops[:self.max_operations_per_message],
            in_sync=in_sync,
            full_state=full_state,
        )

    def apply_response(self, response: GossipResponse) -> None:
        """Apply a gossip response."""
        # Update knowledge of responder's clock
        self.known_clocks[response.from_shard] = response.vector_clock

        # Apply missing operations they sent us
        for op in response.missing_operations:
            op_clock = VectorClock.from_dict(op.get("vector_clock", {}))
            if op_clock.happens_after(self.vector_clock):
                self.pending_operations.append(op)
                if self.on_receive_operations:
                    self.on_receive_operations([op])

        # Merge clocks
        self.vector_clock = self.vector_clock.merge(response.vector_clock)

        # Handle full state from anti-entropy
        if response.full_state:
            for op in response.full_state.get("operations", []):
                if op not in self.pending_operations:
                    self.pending_operations.append(op)

    async def gossip_round(self) -> None:
        """Execute one round of gossip."""
        peers = self._select_peers()

        for peer_id in peers:
            message = self.create_gossip_message(peer_id)

            if self.on_send_message:
                # Send message to peer (callback handles network)
                self.on_send_message(peer_id, message)

    async def run(self) -> None:
        """Run the gossip protocol continuously."""
        self._running = True

        while self._running:
            try:
                await self.gossip_round()
            except Exception:
                # Log error but keep running
                pass

            await asyncio.sleep(self.gossip_interval_ms / 1000)

    def stop(self) -> None:
        """Stop the gossip protocol."""
        self._running = False

    def prune_old_operations(self, max_age_seconds: float = 300) -> int:
        """Remove old operations to prevent unbounded growth."""
        cutoff = time.time() - max_age_seconds
        original_count = len(self.pending_operations)

        self.pending_operations = [
            op for op in self.pending_operations
            if op.get("timestamp", 0) > cutoff
        ]

        return original_count - len(self.pending_operations)

    def get_stats(self) -> Dict[str, Any]:
        """Get gossip protocol statistics."""
        return {
            "shard_id": self.shard_id,
            "peer_count": len(self.peers),
            "pending_operations": len(self.pending_operations),
            "vector_clock": self.vector_clock.to_dict(),
            "known_clocks": {k: v.to_dict() for k, v in self.known_clocks.items()},
            "gossip_interval_ms": self.gossip_interval_ms,
            "running": self._running,
        }
