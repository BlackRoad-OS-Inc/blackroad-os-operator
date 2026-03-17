# Operator Runtime Overview

The Operator is a lightweight job scheduler and orchestrator for BlackRoad OS. It uses BullMQ backed by Redis for job queueing and node-cron for scheduled tasks.

## Current Components

### Job Queue
- File: `src/queues/index.ts`
- Uses BullMQ with Redis as the backing store
- Factory function `getQueue(name)` creates or retrieves named queues
- Connection is shared across all queues

### Job Processors
- Directory: `src/jobs/`
- Example: `src/jobs/sample.job.ts` - demonstrates basic job processing
- Each processor registers a BullMQ Worker that processes jobs from a specific queue
- Workers log job execution and failures

### Schedulers
- Directory: `src/schedulers/`
- Example: `src/schedulers/heartbeat.scheduler.ts` - enqueues heartbeat jobs every 5 minutes
- Uses node-cron for recurring tasks
- Schedulers enqueue jobs into appropriate queues

### Configuration
- File: `src/config.ts`
- Centralized typed configuration from environment variables
- Provides safe defaults and validates critical values
- Supports standard BlackRoad OS env vars: `BR_OS_ENV`, `BR_OS_OPERATOR_VERSION`, etc.

### HTTP Endpoints
The Fastify app in `src/index.ts` exposes standard service endpoints:
- `GET /health` - Liveness check
- `GET /ready` - Readiness check (validates config and verifies Redis queue connectivity with PING)
- `GET /version` - Build and environment metadata
- `GET /metrics` - Service-level request counters and response status aggregates
- `GET /events` - Recent domain events buffered by the operator event bus
- `POST /integrations/e2e` - Unified backend integration checks for Stripe, Git, Slack, Railway, Pi agents, Cloudflare, and Gitea

## Adding New Jobs
1. Create a new file in `src/jobs/` (e.g., `my-job.job.ts`)
2. Define your job input type in `src/types/index.ts`
3. Implement a BullMQ Worker that processes jobs from a named queue
4. Register the processor in `src/index.ts` by calling your registration function
5. Jobs can be enqueued using `getQueue('my-queue').add('job-name', payload)`

## Adding New Schedulers
1. Create a new file in `src/schedulers/` (e.g., `my-task.scheduler.ts`)
2. Use node-cron's `schedule()` function with a cron expression
3. Have the scheduler enqueue jobs via `getQueue().add()`
4. Start the scheduler in `src/index.ts`

## Future Enhancements
- Agent registration and discovery
- Authentication and request signing
- Multi-queue orchestration policies
- Workflow composition (fan-out, fan-in, conditional branching)

