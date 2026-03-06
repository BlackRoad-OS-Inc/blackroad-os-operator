# BlackRoad OS - Sharding for 30K Collaboration
# Consistent hashing and shard management
#
# @blackroad_name: Shard Manager
# @operator: alexa.operator.v1

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import hashlib
import bisect


@dataclass
class ConsistentHash:
    """Consistent hashing ring for shard assignment.

    Uses virtual nodes for better distribution. Each shard gets
    multiple positions on the ring to ensure even load.
    """

    ring: Dict[int, str] = field(default_factory=dict)
    sorted_keys: List[int] = field(default_factory=list)
    virtual_nodes: int = 150  # Virtual nodes per shard
    shards: Set[str] = field(default_factory=set)

    def _hash(self, key: str) -> int:
        """Hash a key to a ring position."""
        return int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**32)

    def add_shard(self, shard_id: str) -> None:
        """Add a shard to the ring."""
        if shard_id in self.shards:
            return

        self.shards.add(shard_id)

        for i in range(self.virtual_nodes):
            virtual_key = f"{shard_id}:{i}"
            hash_val = self._hash(virtual_key)
            self.ring[hash_val] = shard_id
            bisect.insort(self.sorted_keys, hash_val)

    def remove_shard(self, shard_id: str) -> None:
        """Remove a shard from the ring."""
        if shard_id not in self.shards:
            return

        self.shards.discard(shard_id)

        for i in range(self.virtual_nodes):
            virtual_key = f"{shard_id}:{i}"
            hash_val = self._hash(virtual_key)
            if hash_val in self.ring:
                del self.ring[hash_val]
                self.sorted_keys.remove(hash_val)

    def get_shard(self, key: str) -> Optional[str]:
        """Get the shard responsible for a key."""
        if not self.ring:
            return None

        hash_val = self._hash(key)
        idx = bisect.bisect_right(self.sorted_keys, hash_val)

        # Wrap around to first shard if past the end
        if idx >= len(self.sorted_keys):
            idx = 0

        return self.ring[self.sorted_keys[idx]]

    def get_n_shards(self, key: str, n: int) -> List[str]:
        """Get N shards for a key (for replication)."""
        if not self.ring or n <= 0:
            return []

        result = []
        seen = set()
        hash_val = self._hash(key)
        idx = bisect.bisect_right(self.sorted_keys, hash_val)

        while len(result) < n and len(seen) < len(self.shards):
            if idx >= len(self.sorted_keys):
                idx = 0

            shard = self.ring[self.sorted_keys[idx]]
            if shard not in seen:
                result.append(shard)
                seen.add(shard)

            idx += 1

        return result


@dataclass
class Shard:
    """A collaboration shard handling up to 1,000 participants.

    Scale: 30 shards × 1,000 participants = 30,000 concurrent.
    """

    id: str
    capacity: int = 1000
    participants: Set[str] = field(default_factory=set)
    peer_shards: Set[str] = field(default_factory=set)
    status: str = "healthy"  # healthy, degraded, overloaded, draining

    @property
    def participant_count(self) -> int:
        return len(self.participants)

    @property
    def load_percentage(self) -> float:
        return (self.participant_count / self.capacity) * 100

    @property
    def is_available(self) -> bool:
        return (
            self.status in ("healthy", "degraded") and
            self.participant_count < self.capacity
        )

    def add_participant(self, participant_id: str) -> bool:
        """Add a participant to this shard."""
        if not self.is_available:
            return False
        self.participants.add(participant_id)
        self._update_status()
        return True

    def remove_participant(self, participant_id: str) -> bool:
        """Remove a participant from this shard."""
        if participant_id in self.participants:
            self.participants.discard(participant_id)
            self._update_status()
            return True
        return False

    def _update_status(self) -> None:
        """Update shard status based on load."""
        load = self.load_percentage
        if load >= 95:
            self.status = "overloaded"
        elif load >= 80:
            self.status = "degraded"
        elif self.status != "draining":
            self.status = "healthy"

    def start_draining(self) -> None:
        """Start draining this shard (no new participants)."""
        self.status = "draining"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "capacity": self.capacity,
            "participant_count": self.participant_count,
            "load_percentage": self.load_percentage,
            "status": self.status,
            "peer_shards": list(self.peer_shards),
        }


@dataclass
class ShardManager:
    """Manages sharding for 30K concurrent collaboration.

    Architecture:
    - 30 shards × 1,000 participants = 30,000 capacity
    - Consistent hashing for participant assignment
    - Automatic rebalancing when shards become overloaded
    """

    shards: Dict[str, Shard] = field(default_factory=dict)
    hash_ring: ConsistentHash = field(default_factory=ConsistentHash)
    default_shard_count: int = 30
    shard_capacity: int = 1000

    def __post_init__(self):
        """Initialize shards if empty."""
        if not self.shards:
            self._initialize_shards()

    def _initialize_shards(self) -> None:
        """Create initial shards."""
        for i in range(self.default_shard_count):
            shard_id = f"{i:03d}"
            self.shards[shard_id] = Shard(id=shard_id, capacity=self.shard_capacity)
            self.hash_ring.add_shard(shard_id)

        # Set up peer relationships (each shard knows its neighbors)
        shard_ids = list(self.shards.keys())
        for i, shard_id in enumerate(shard_ids):
            prev_id = shard_ids[(i - 1) % len(shard_ids)]
            next_id = shard_ids[(i + 1) % len(shard_ids)]
            self.shards[shard_id].peer_shards = {prev_id, next_id}

    def assign_shard(self, participant_id: str) -> Optional[str]:
        """Assign a participant to a shard using consistent hashing."""
        shard_id = self.hash_ring.get_shard(participant_id)
        if shard_id and self.shards[shard_id].is_available:
            self.shards[shard_id].add_participant(participant_id)
            return shard_id

        # Primary shard unavailable, find alternative
        return self._find_available_shard(participant_id)

    def _find_available_shard(self, participant_id: str) -> Optional[str]:
        """Find an available shard when primary is full."""
        # Try replica shards first
        replicas = self.hash_ring.get_n_shards(participant_id, 3)
        for shard_id in replicas:
            if self.shards[shard_id].is_available:
                self.shards[shard_id].add_participant(participant_id)
                return shard_id

        # Fall back to any available shard (least loaded)
        available = [
            s for s in self.shards.values()
            if s.is_available
        ]
        if available:
            shard = min(available, key=lambda s: s.participant_count)
            shard.add_participant(participant_id)
            return shard.id

        return None

    def remove_participant(self, participant_id: str, shard_id: str) -> bool:
        """Remove a participant from a shard."""
        if shard_id in self.shards:
            return self.shards[shard_id].remove_participant(participant_id)
        return False

    def get_shard(self, shard_id: str) -> Optional[Shard]:
        """Get a shard by ID."""
        return self.shards.get(shard_id)

    def get_participant_shard(self, participant_id: str) -> Optional[str]:
        """Find which shard a participant is in."""
        for shard in self.shards.values():
            if participant_id in shard.participants:
                return shard.id
        return None

    def add_shard(self) -> Shard:
        """Add a new shard dynamically."""
        new_id = f"{len(self.shards):03d}"
        new_shard = Shard(id=new_id, capacity=self.shard_capacity)

        # Set peers
        if self.shards:
            last_shard = list(self.shards.values())[-1]
            first_shard = list(self.shards.values())[0]
            new_shard.peer_shards = {last_shard.id, first_shard.id}

        self.shards[new_id] = new_shard
        self.hash_ring.add_shard(new_id)
        return new_shard

    def drain_shard(self, shard_id: str) -> List[str]:
        """Start draining a shard and return participants to relocate."""
        if shard_id not in self.shards:
            return []

        shard = self.shards[shard_id]
        shard.start_draining()
        return list(shard.participants)

    def rebalance(self) -> Dict[str, str]:
        """Rebalance participants across shards.

        Returns mapping of participant_id -> new_shard_id.
        """
        moves: Dict[str, str] = {}

        # Find overloaded and underloaded shards
        overloaded = [s for s in self.shards.values() if s.load_percentage > 80]
        underloaded = [s for s in self.shards.values() if s.load_percentage < 50]

        if not overloaded or not underloaded:
            return moves

        for source in overloaded:
            excess = source.participant_count - int(source.capacity * 0.7)
            participants_to_move = list(source.participants)[:excess]

            for participant_id in participants_to_move:
                # Find best target
                target = min(underloaded, key=lambda s: s.participant_count)
                if target.is_available:
                    source.remove_participant(participant_id)
                    target.add_participant(participant_id)
                    moves[participant_id] = target.id

        return moves

    @property
    def total_participants(self) -> int:
        return sum(s.participant_count for s in self.shards.values())

    @property
    def total_capacity(self) -> int:
        return sum(s.capacity for s in self.shards.values())

    @property
    def healthy_shard_count(self) -> int:
        return sum(1 for s in self.shards.values() if s.status == "healthy")

    def to_dict(self) -> Dict:
        return {
            "shards": [s.to_dict() for s in self.shards.values()],
            "total_participants": self.total_participants,
            "total_capacity": self.total_capacity,
            "healthy_count": self.healthy_shard_count,
        }
