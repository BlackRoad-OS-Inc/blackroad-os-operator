# Operator Blitz: 100 TODOs

A focused execution backlog to make `blackroad-os-operator` the operational center repo.

## 1) Platform Core (1-20)
- [ ] 1. Add request-id middleware for all API routes.
- [ ] 2. Add global typed error envelope (`code`, `message`, `traceId`).
- [ ] 3. Add centralized input schema validation for all POST routes.
- [ ] 4. Add `/metrics` endpoint with service counters.
- [ ] 5. Add structured startup diagnostics endpoint.
- [ ] 6. Add graceful shutdown hooks for queues and workers.
- [ ] 7. Add environment sanity checker at startup.
- [ ] 8. Add versioned API namespace (`/v1`).
- [ ] 9. Add OpenAPI generation for Fastify routes.
- [ ] 10. Add API contract snapshot tests.
- [ ] 11. Add distributed tracing headers pass-through.
- [ ] 12. Add rate limiting for public routes.
- [ ] 13. Add API key auth middleware toggle.
- [ ] 14. Add role-based route guards.
- [ ] 15. Add route-level timeout wrappers.
- [ ] 16. Add health dependency map output.
- [ ] 17. Add readiness deep-check and shallow-check modes.
- [ ] 18. Add queue backlog depth endpoint.
- [ ] 19. Add feature flags support for integrations.
- [ ] 20. Add startup config fingerprint logging.

## 2) Integrations: Stripe/Git/Slack/Railway/Pi/Cloudflare/Gitea (21-40)
- [ ] 21. Add per-provider retry policy overrides.
- [ ] 22. Add provider-specific timeout settings.
- [ ] 23. Add token presence validation before live checks.
- [ ] 24. Add signed webhook verification for Stripe.
- [ ] 25. Add Git provider abstraction (`github|gitea`).
- [ ] 26. Add Slack channel delivery test route.
- [ ] 27. Add Railway deploy status polling adapter.
- [ ] 28. Add Pi fleet registry and heartbeat tracker.
- [ ] 29. Add Cloudflare zone verification check.
- [ ] 30. Add Cloudflare DNS dry-run mutation preview.
- [ ] 31. Add Gitea repo webhook validation.
- [ ] 32. Add integration response normalization per provider.
- [ ] 33. Add partial-failure tolerance mode.
- [ ] 34. Add provider circuit-breaker telemetry output.
- [ ] 35. Add provider SLA dashboard payload endpoint.
- [ ] 36. Add secure secret alias map usage for tokens.
- [ ] 37. Add integration check history persistence.
- [ ] 38. Add manual override for provider maintenance mode.
- [ ] 39. Add fallback host support for each provider.
- [ ] 40. Add integration smoke job scheduler.

## 3) Workflows & Jobs (41-60)
- [ ] 41. Add workflow registry endpoint.
- [ ] 42. Add workflow run endpoint with idempotency key required.
- [ ] 43. Add workflow cancellation endpoint.
- [ ] 44. Add workflow replay endpoint.
- [ ] 45. Add workflow run history endpoint.
- [ ] 46. Add job dead-letter queue support.
- [ ] 47. Add configurable worker concurrency by queue.
- [ ] 48. Add delayed job scheduling endpoint.
- [ ] 49. Add cron schedule CRUD API.
- [ ] 50. Add workflow status streaming over SSE.
- [ ] 51. Add fan-out/fan-in generic helper library.
- [ ] 52. Add workflow-level compensation hooks.
- [ ] 53. Add dry-run execution mode across workflows.
- [ ] 54. Add workflow policy gate pre-check.
- [ ] 55. Add workflow audit event correlation IDs.
- [ ] 56. Add queue processing lag measurement.
- [ ] 57. Add job payload schema registry.
- [ ] 58. Add poison-message detection logic.
- [ ] 59. Add workflow template generator script.
- [ ] 60. Add workflow run diff inspector.

## 4) Reliability, Security, Compliance (61-80)
- [ ] 61. Add secret redaction in all logs.
- [ ] 62. Add PII scanning for outbound logs.
- [ ] 63. Add authz checks on integration execution routes.
- [ ] 64. Add allowlist for outbound integration hosts.
- [ ] 65. Add outbound request signing where supported.
- [ ] 66. Add mTLS option for internal service calls.
- [ ] 67. Add security headers middleware baseline.
- [ ] 68. Add brute-force protection for auth endpoints.
- [ ] 69. Add audit event immutability checksum.
- [ ] 70. Add tamper-evident audit chain endpoint.
- [ ] 71. Add compliance tags to high-risk routes.
- [ ] 72. Add policy decision cache with TTL.
- [ ] 73. Add emergency kill switch for integrations.
- [ ] 74. Add chaos test mode for dependency failure.
- [ ] 75. Add synthetic canary checks every 5 minutes.
- [ ] 76. Add SLO error budget calculation endpoint.
- [ ] 77. Add incident mode response profile toggle.
- [ ] 78. Add secure default deny mode for unknown actions.
- [ ] 79. Add invariant test suite for policy/ledger paths.
- [ ] 80. Add signed release artifact provenance.

## 5) Testing, DX, Ops, and Rollout (81-100)
- [ ] 81. Add full backend E2E pipeline in CI.
- [ ] 82. Add contract tests for `/integrations/e2e`.
- [ ] 83. Add mocked live-provider simulation test harness.
- [ ] 84. Add load test script for API and queues.
- [ ] 85. Add soak test (24h) for queue workers.
- [ ] 86. Add flaky test quarantine tagging.
- [ ] 87. Add deterministic seed mode for test runs.
- [ ] 88. Add local `make e2e` command for operator API.
- [ ] 89. Add one-command dev bootstrap script.
- [ ] 90. Add release checklist automation script.
- [ ] 91. Add migration guide: Python runtime -> TS runtime.
- [ ] 92. Add architecture decision record for “single operator repo”.
- [ ] 93. Add runbook for integration outage handling.
- [ ] 94. Add runbook for Redis failure scenarios.
- [ ] 95. Add runbook for webhook incident triage.
- [ ] 96. Add environment promotion checklist (dev/stage/prod).
- [ ] 97. Add dashboard JSON export for Grafana.
- [ ] 98. Add PR template for operator workflow changes.
- [ ] 99. Add issue templates for integration bugs.
- [ ] 100. Add monthly platform reliability review ritual.
