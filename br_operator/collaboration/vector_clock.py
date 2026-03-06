# BlackRoad OS - Vector Clock Implementation
# Causal ordering for 30K concurrent collaborators
#
# @blackroad_name: Vector Clock
# @operator: alexa.operator.v1

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple
import json


@dataclass
class VectorClock:
    """Vector clock for causal ordering in distributed collaboration.

    Each participant maintains a logical timestamp. The vector clock
    captures the causal relationships between events across all participants.

    Comparison rules:
    - vc1 < vc2: vc1 happened before vc2
    - vc1 > vc2: vc1 happened after vc2
    - vc1 || vc2: vc1 and vc2 are concurrent (incomparable)
    """

    clock: Dict[str, int] = field(default_factory=dict)

    def increment(self, participant_id: str) -> VectorClock:
        """Increment the clock for a participant (local event)."""
        new_clock = self.clock.copy()
        new_clock[participant_id] = new_clock.get(participant_id, 0) + 1
        return VectorClock(clock=new_clock)

    def merge(self, other: VectorClock) -> VectorClock:
        """Merge with another vector clock (receive event)."""
        new_clock = self.clock.copy()
        for pid, ts in other.clock.items():
            new_clock[pid] = max(new_clock.get(pid, 0), ts)
        return VectorClock(clock=new_clock)

    def update(self, participant_id: str, other: VectorClock) -> VectorClock:
        """Update clock on receiving a message: merge + increment."""
        return self.merge(other).increment(participant_id)

    def get(self, participant_id: str) -> int:
        """Get timestamp for a participant."""
        return self.clock.get(participant_id, 0)

    def compare(self, other: VectorClock) -> Tuple[bool, bool, bool]:
        """Compare two vector clocks.

        Returns (before, after, concurrent):
        - (True, False, False): self happened before other
        - (False, True, False): self happened after other
        - (False, False, True): self and other are concurrent
        - (True, True, False): self equals other
        """
        all_keys = set(self.clock.keys()) | set(other.clock.keys())

        self_before = True  # self <= other for all components
        other_before = True  # other <= self for all components
        strictly_less = False
        strictly_greater = False

        for key in all_keys:
            self_val = self.clock.get(key, 0)
            other_val = other.clock.get(key, 0)

            if self_val > other_val:
                other_before = False
                strictly_greater = True
            if self_val < other_val:
                self_before = False
                strictly_less = True

        # Determine relationship
        if self_before and strictly_less:
            return (True, False, False)  # self < other
        elif other_before and strictly_greater:
            return (False, True, False)  # self > other
        elif self_before and other_before:
            return (True, True, False)  # equal
        else:
            return (False, False, True)  # concurrent

    def happens_before(self, other: VectorClock) -> bool:
        """Check if this clock happened before another."""
        before, after, concurrent = self.compare(other)
        return before and not after

    def happens_after(self, other: VectorClock) -> bool:
        """Check if this clock happened after another."""
        before, after, concurrent = self.compare(other)
        return after and not before

    def is_concurrent(self, other: VectorClock) -> bool:
        """Check if two clocks are concurrent (incomparable)."""
        before, after, concurrent = self.compare(other)
        return concurrent

    def is_causally_stable(self, known_clocks: Dict[str, VectorClock]) -> bool:
        """Check if this event is causally stable.

        An event is causally stable when all participants have seen
        all events that happened before it.
        """
        for pid, vc in known_clocks.items():
            for key, ts in self.clock.items():
                if key != pid and vc.get(key) < ts:
                    return False
        return True

    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary for serialization."""
        return self.clock.copy()

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> VectorClock:
        """Create from dictionary."""
        return cls(clock=data.copy())

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.clock)

    @classmethod
    def from_json(cls, data: str) -> VectorClock:
        """Deserialize from JSON string."""
        return cls(clock=json.loads(data))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorClock):
            return False
        before, after, concurrent = self.compare(other)
        return before and after  # Equal when both <= conditions hold

    def __lt__(self, other: VectorClock) -> bool:
        return self.happens_before(other)

    def __le__(self, other: VectorClock) -> bool:
        return self == other or self < other

    def __gt__(self, other: VectorClock) -> bool:
        return self.happens_after(other)

    def __ge__(self, other: VectorClock) -> bool:
        return self == other or self > other

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.clock.items())))

    def __repr__(self) -> str:
        return f"VectorClock({self.clock})"
