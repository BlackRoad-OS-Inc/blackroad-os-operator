"""
BlackRoad OS Operator - Reconciliation Loop

The "air traffic control" for 30,000 agents.
Reconciles desired state vs actual state and manages worker scaling.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional
import asyncpg
import aioredis

logger = logging.getLogger(__name__)


@dataclass
class WorkerPoolState:
    """Current state of a worker pool."""
    id: str
    name: str
    pack_id: Optional[str]
    queue_name: str
    min_workers: int
    max_workers: int
    target_latency_ms: int
    current_workers: int
    queue_depth: int = 0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0


@dataclass
class AgentHealth:
    """Health status of an agent."""
    id: str
    ps_sha_id: str
    org_id: str
    name: str
    status: str
    error_rate: float
    job_count: int
    avg_latency_ms: float


@dataclass
class ScaleDecision:
    """A scaling decision for a worker pool."""
    pool_name: str
    current: int
    target: int
    reason: str


class OperatorConfig:
    """Configuration for the operator."""

    def __init__(
        self,
        reconcile_interval: int = 10,
        scale_step: int = 1,
        high_queue_threshold: int = 100,
        low_queue_threshold: int = 5,
        error_rate_threshold: float = 0.1,
        latency_threshold_multiplier: float = 1.5,
    ):
        self.reconcile_interval = reconcile_interval
        self.scale_step = scale_step
        self.high_queue_threshold = high_queue_threshold
        self.low_queue_threshold = low_queue_threshold
        self.error_rate_threshold = error_rate_threshold
        self.latency_threshold_multiplier = latency_threshold_multiplier


class InfraProvider:
    """Base class for infrastructure providers (Railway, etc.)."""

    async def get_worker_count(self, pool_name: str) -> int:
        """Get current worker count for a pool."""
        raise NotImplementedError

    async def set_worker_count(self, pool_name: str, count: int) -> bool:
        """Set worker count for a pool."""
        raise NotImplementedError


class RailwayProvider(InfraProvider):
    """Railway infrastructure provider."""

    def __init__(self, api_token: str, project_id: str):
        self.api_token = api_token
        self.project_id = project_id

    async def get_worker_count(self, pool_name: str) -> int:
        """Get current replicas from Railway."""
        # TODO: Implement Railway API call
        # GET https://backboard.railway.com/graphql
        # Query for service replicas
        return 1

    async def set_worker_count(self, pool_name: str, count: int) -> bool:
        """Set replicas in Railway."""
        # TODO: Implement Railway API call
        # POST https://backboard.railway.com/graphql
        # Mutation to update service replicas
        logger.info(f"Would scale {pool_name} to {count} workers")
        return True


class Reconciler:
    """
    Main reconciliation loop for BlackRoad OS.

    Periodically:
    1. Reads desired state from Postgres (packs, worker_pools, agents)
    2. Reads actual state (queue depths from Redis, metrics from Beacon)
    3. Compares and makes scaling decisions
    4. Marks unhealthy agents if error rates are high
    """

    def __init__(
        self,
        db: asyncpg.Pool,
        redis: aioredis.Redis,
        infra: InfraProvider,
        config: Optional[OperatorConfig] = None,
    ):
        self.db = db
        self.redis = redis
        self.infra = infra
        self.config = config or OperatorConfig()
        self._running = False

    async def start(self):
        """Start the reconciliation loop."""
        self._running = True
        logger.info("Starting operator reconciliation loop")

        while self._running:
            try:
                await self.reconcile()
            except Exception as e:
                logger.error(f"Reconciliation error: {e}", exc_info=True)

            await asyncio.sleep(self.config.reconcile_interval)

    async def stop(self):
        """Stop the reconciliation loop."""
        self._running = False
        logger.info("Stopping operator reconciliation loop")

    async def reconcile(self):
        """
        Main reconciliation step.

        1. Get worker pool states
        2. Get queue depths
        3. Get metrics
        4. Make scaling decisions
        5. Apply scaling
        6. Check agent health
        """
        logger.debug("Starting reconciliation cycle")

        # 1. Get worker pools from DB
        pools = await self._get_worker_pools()

        # 2. Get queue depths from Redis
        for pool in pools:
            pool.queue_depth = await self._get_queue_depth(pool.queue_name)

        # 3. Get metrics (placeholder - would come from Beacon)
        metrics = await self._get_metrics()

        # 4. Make scaling decisions
        decisions = []
        for pool in pools:
            decision = self._evaluate_scaling(pool, metrics)
            if decision:
                decisions.append(decision)

        # 5. Apply scaling decisions
        for decision in decisions:
            logger.info(
                f"Scaling {decision.pool_name}: {decision.current} -> {decision.target} ({decision.reason})"
            )
            success = await self.infra.set_worker_count(decision.pool_name, decision.target)
            if success:
                await self._update_pool_worker_count(decision.pool_name, decision.target)

        # 6. Check agent health
        await self._check_agent_health()

        logger.debug("Reconciliation cycle complete")

    async def _get_worker_pools(self) -> list[WorkerPoolState]:
        """Get all worker pools from database."""
        rows = await self.db.fetch(
            """
            SELECT id, name, pack_id, queue_name, min_workers, max_workers,
                   target_latency_ms, current_workers
            FROM worker_pools
            WHERE status = 'active'
            """
        )
        return [
            WorkerPoolState(
                id=str(row["id"]),
                name=row["name"],
                pack_id=str(row["pack_id"]) if row["pack_id"] else None,
                queue_name=row["queue_name"],
                min_workers=row["min_workers"],
                max_workers=row["max_workers"],
                target_latency_ms=row["target_latency_ms"],
                current_workers=row["current_workers"],
            )
            for row in rows
        ]

    async def _get_queue_depth(self, queue_name: str) -> int:
        """Get the depth of a Redis stream queue."""
        try:
            length = await self.redis.xlen(queue_name)
            return length or 0
        except Exception as e:
            logger.warning(f"Failed to get queue depth for {queue_name}: {e}")
            return 0

    async def _get_metrics(self) -> dict[str, Any]:
        """Get metrics from Beacon service."""
        # TODO: Implement Beacon API call
        # For now, return empty metrics
        return {
            "pools": {},
            "agents": {},
        }

    def _evaluate_scaling(
        self,
        pool: WorkerPoolState,
        metrics: dict[str, Any],
    ) -> Optional[ScaleDecision]:
        """Evaluate whether a pool needs scaling."""
        current = pool.current_workers
        target = current

        # Get pool-specific metrics
        pool_metrics = metrics.get("pools", {}).get(pool.name, {})
        latency = pool_metrics.get("p95_latency_ms", 0)

        # Scale up conditions
        if pool.queue_depth > self.config.high_queue_threshold:
            target = min(current + self.config.scale_step, pool.max_workers)
            reason = f"High queue depth ({pool.queue_depth})"
        elif latency > pool.target_latency_ms * self.config.latency_threshold_multiplier:
            target = min(current + self.config.scale_step, pool.max_workers)
            reason = f"High latency ({latency}ms > {pool.target_latency_ms}ms)"
        # Scale down conditions
        elif pool.queue_depth < self.config.low_queue_threshold and current > pool.min_workers:
            target = max(current - self.config.scale_step, pool.min_workers)
            reason = f"Low queue depth ({pool.queue_depth})"

        if target != current:
            return ScaleDecision(
                pool_name=pool.name,
                current=current,
                target=target,
                reason=reason,
            )
        return None

    async def _update_pool_worker_count(self, pool_name: str, count: int):
        """Update the worker count in the database."""
        await self.db.execute(
            """
            UPDATE worker_pools
            SET current_workers = $1, updated_at = now()
            WHERE name = $2
            """,
            count,
            pool_name,
        )

    async def _check_agent_health(self):
        """Check agent health and mark unhealthy agents."""
        # Get agents with high error rates from recent jobs
        unhealthy_agents = await self.db.fetch(
            """
            WITH agent_stats AS (
                SELECT
                    agent_id,
                    COUNT(*) as total_jobs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_jobs,
                    AVG(EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000) as avg_latency_ms
                FROM jobs
                WHERE created_at > now() - interval '1 hour'
                GROUP BY agent_id
            )
            SELECT
                a.id,
                a.ps_sha_id,
                a.org_id,
                a.name,
                a.status,
                COALESCE(s.failed_jobs::float / NULLIF(s.total_jobs, 0), 0) as error_rate,
                COALESCE(s.total_jobs, 0) as job_count,
                COALESCE(s.avg_latency_ms, 0) as avg_latency_ms
            FROM agents a
            LEFT JOIN agent_stats s ON s.agent_id = a.id
            WHERE a.status = 'active'
            AND COALESCE(s.failed_jobs::float / NULLIF(s.total_jobs, 0), 0) > $1
            AND COALESCE(s.total_jobs, 0) >= 5
            """,
            self.config.error_rate_threshold,
        )

        for row in unhealthy_agents:
            logger.warning(
                f"Agent {row['name']} ({row['ps_sha_id'][:8]}...) has high error rate: "
                f"{row['error_rate']:.1%} over {row['job_count']} jobs"
            )
            await self.db.execute(
                """
                UPDATE agents
                SET status = 'error',
                    error_message = $1,
                    updated_at = now()
                WHERE id = $2
                """,
                f"High error rate: {row['error_rate']:.1%}",
                row["id"],
            )

            # Log to RoadChain
            await self.db.execute(
                """
                INSERT INTO roadchain (org_id, entity_type, entity_id, action, actor_type, payload, ps_sha_id)
                VALUES ($1, 'agent', $2, 'marked_unhealthy', 'system', $3, $4)
                """,
                row["org_id"],
                row["id"],
                {"error_rate": row["error_rate"], "job_count": row["job_count"]},
                row["ps_sha_id"],
            )


async def create_reconciler(
    database_url: str,
    redis_url: str,
    railway_token: Optional[str] = None,
    railway_project: Optional[str] = None,
) -> Reconciler:
    """Factory function to create a reconciler with connections."""
    db = await asyncpg.create_pool(database_url)
    redis = await aioredis.from_url(redis_url)

    if railway_token and railway_project:
        infra = RailwayProvider(railway_token, railway_project)
    else:
        # Mock provider for development
        infra = InfraProvider()

    return Reconciler(db=db, redis=redis, infra=infra)
