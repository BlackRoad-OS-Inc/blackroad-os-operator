"""Ledger service for BlackRoad OS governance.

This service handles:
- Recording ledger events (POST /ledger/event)
- Querying ledger events (GET /ledger/events)
- In-memory store for v0 (DB integration later)

The ledger is append-only. No retroactive edits without a higher-order governance event.

Usage:
    from br_operator.ledger_service import LedgerService, get_ledger_service

    ledger = await get_ledger_service()
    event = await ledger.record(event_create)
    events = await ledger.query(query)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from br_operator.models.ledger import (
    LedgerEvent,
    LedgerEventCreate,
    LedgerEventList,
    LedgerEventQuery,
)


class LedgerService:
    """In-memory ledger service for v0.

    TODO: Replace with Postgres-backed implementation.
    """

    def __init__(self):
        self._events: List[LedgerEvent] = []
        self._by_id: dict[UUID, LedgerEvent] = {}
        self._by_correlation: dict[UUID, List[LedgerEvent]] = {}

    async def record(self, create: LedgerEventCreate) -> LedgerEvent:
        """Record a new ledger event.

        This is the core append operation. Events are immutable once recorded.
        """
        now = datetime.now(timezone.utc)

        event = LedgerEvent(
            id=uuid4(),
            correlation_id=create.correlation_id,
            intent_id=create.intent_id,
            sequence_num=create.sequence_num,
            layer=create.layer,
            host=create.host,
            service=create.service,
            policy_scope=create.policy_scope,
            actor=create.actor,
            action=create.action,
            resource_type=create.resource_type,
            resource_id=create.resource_id,
            decision=create.decision,
            policy_id=create.policy_id,
            policy_version=create.policy_version,
            asserted_facts=create.asserted_facts,
            fact_evidence=create.fact_evidence,
            claims=create.claims,
            ledger_level=create.ledger_level,
            metadata=create.metadata,
            request_context=create.request_context,
            response_summary=create.response_summary,
            occurred_at=create.occurred_at or now,
            recorded_at=now,
        )

        # Store
        self._events.append(event)
        self._by_id[event.id] = event

        # Index by correlation
        if event.correlation_id not in self._by_correlation:
            self._by_correlation[event.correlation_id] = []
        self._by_correlation[event.correlation_id].append(event)

        return event

    async def get(self, event_id: UUID) -> Optional[LedgerEvent]:
        """Get a single event by ID."""
        return self._by_id.get(event_id)

    async def get_by_correlation(self, correlation_id: UUID) -> List[LedgerEvent]:
        """Get all events in a correlation chain."""
        return self._by_correlation.get(correlation_id, [])

    async def query(self, q: LedgerEventQuery) -> LedgerEventList:
        """Query events with filters.

        Supports filtering by:
        - correlation_id, intent_id
        - actor_user_id, actor_agent_id
        - action, policy_scope, decision
        - host, service
        - time range (occurred_after, occurred_before)

        Returns paginated results.
        """
        results = self._events

        # Apply filters
        if q.correlation_id:
            results = [e for e in results if e.correlation_id == q.correlation_id]

        if q.intent_id:
            results = [e for e in results if e.intent_id == q.intent_id]

        if q.actor_user_id:
            results = [e for e in results if e.actor.user_id == q.actor_user_id]

        if q.actor_agent_id:
            results = [e for e in results if e.actor.agent_id == q.actor_agent_id]

        if q.action:
            results = [e for e in results if e.action == q.action]

        if q.policy_scope:
            results = [e for e in results if e.policy_scope == q.policy_scope]

        if q.decision:
            results = [e for e in results if e.decision == q.decision]

        if q.host:
            results = [e for e in results if e.host == q.host]

        if q.service:
            results = [e for e in results if e.service == q.service]

        if q.occurred_after:
            results = [e for e in results if e.occurred_at >= q.occurred_after]

        if q.occurred_before:
            results = [e for e in results if e.occurred_at <= q.occurred_before]

        # Sort by occurred_at descending (most recent first)
        results.sort(key=lambda e: e.occurred_at, reverse=True)

        total = len(results)

        # Paginate
        results = results[q.offset : q.offset + q.limit]

        return LedgerEventList(
            events=results,
            total=total,
            limit=q.limit,
            offset=q.offset,
        )

    async def count(self) -> int:
        """Get total event count."""
        return len(self._events)

    async def count_by_decision(self) -> dict[str, int]:
        """Get event counts grouped by decision."""
        counts: dict[str, int] = {}
        for event in self._events:
            decision = event.decision.value
            counts[decision] = counts.get(decision, 0) + 1
        return counts


# Singleton instance
_ledger: Optional[LedgerService] = None


async def get_ledger_service() -> LedgerService:
    """Get or create the singleton ledger service."""
    global _ledger
    if _ledger is None:
        _ledger = LedgerService()
    return _ledger
