import type { FastifyInstance } from 'fastify';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearEvents, emitJobStarted } from '../src/utils/eventBus.js';

const mockGenerateChatResponse = vi.fn();
const mockCheckLlmHealth = vi.fn();
const mockRunIntegrationE2E = vi.fn();
const mockPing = vi.fn();

vi.mock('../src/services/llm.service.js', () => ({
  generateChatResponse: mockGenerateChatResponse,
  checkLlmHealth: mockCheckLlmHealth,
}));


vi.mock('../src/services/integrations.service.js', () => ({
  runIntegrationE2E: mockRunIntegrationE2E,
}));

vi.mock('../src/queues/index.js', () => ({
  connection: {
    ping: mockPing,
  },
}));

describe('E2E API routes', () => {
  let app: FastifyInstance;

  beforeEach(async () => {
    clearEvents();
    mockGenerateChatResponse.mockReset();
    mockCheckLlmHealth.mockReset();
    mockRunIntegrationE2E.mockReset();
    mockPing.mockReset();

    const { buildApp } = await import('../src/app.js');

    app = buildApp({
      port: 4000,
      nodeEnv: 'test',
      brOsEnv: 'test',
      version: '1.2.3-test',
      commit: 'deadbeef',
      redisUrl: 'redis://localhost:6379',
      logLevel: 'silent',
      maxConcurrency: 10,
      defaultTimeoutSeconds: 300,
      llmProvider: 'ollama',
      ollamaUrl: 'http://ollama.test:11434',
      ollamaModel: 'llama-test',
      ragApiUrl: 'http://rag.test:8000',
      stripeApiKey: '',
      slackBotToken: '',
      railwayApiToken: '',
      cloudflareApiToken: '',
      giteaToken: '',
      enableApiKeyAuth: false,
      apiKey: '',
    });

    await app.ready();
  });

  afterEach(async () => {
    if (app) {
      await app.close();
    }
    clearEvents();
  });

  it('returns service health', async () => {
    const response = await app.inject({ method: 'GET', url: '/health' });

    expect(response.statusCode).toBe(200);
    expect(response.headers['x-request-id']).toBeDefined();
    expect(response.json()).toMatchObject({
      ok: true,
      service: 'blackroad-os-operator',
    });
  });





  it('supports versioned v1 health and version endpoints', async () => {
    const health = await app.inject({ method: 'GET', url: '/v1/health' });
    const version = await app.inject({ method: 'GET', url: '/v1/version' });

    expect(health.statusCode).toBe(200);
    expect(version.statusCode).toBe(200);
    expect(health.json()).toMatchObject({ ok: true, service: 'blackroad-os-operator' });
    expect(version.json()).toMatchObject({ version: '1.2.3-test', env: 'test' });
  });

  it('supports versioned v1 integrations endpoint', async () => {
    mockRunIntegrationE2E.mockResolvedValue({
      ok: true,
      dryRun: true,
      results: [],
    });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/integrations/e2e',
      payload: { dryRun: true },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toMatchObject({
      service: 'blackroad-os-operator',
      ok: true,
      dryRun: true,
    });
  });

  it('returns structured startup diagnostics', async () => {
    const response = await app.inject({ method: 'GET', url: '/diagnostics/startup' });

    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      service: string;
      startedAtIso: string;
      config: {
        nodeEnv: string;
        brOsEnv: string;
        version: string;
        commit: string;
      };
      integrationsConfigured: Record<string, boolean>;
    };

    expect(body.service).toBe('blackroad-os-operator');
    expect(body.config.nodeEnv).toBe('test');
    expect(body.config.version).toBe('1.2.3-test');
    expect(body.integrationsConfigured).toMatchObject({
      stripe: false,
      slack: false,
      railway: false,
      cloudflare: false,
      gitea: false,
    });
  });

  it('enforces API key when auth toggle is enabled', async () => {
    await app.close();

    const { buildApp } = await import('../src/app.js');
    app = buildApp({
      port: 4000,
      nodeEnv: 'test',
      brOsEnv: 'test',
      version: '1.2.3-test',
      commit: 'deadbeef',
      redisUrl: 'redis://localhost:6379',
      logLevel: 'silent',
      maxConcurrency: 10,
      defaultTimeoutSeconds: 300,
      llmProvider: 'ollama',
      ollamaUrl: 'http://ollama.test:11434',
      ollamaModel: 'llama-test',
      ragApiUrl: 'http://rag.test:8000',
      stripeApiKey: '',
      slackBotToken: '',
      railwayApiToken: '',
      cloudflareApiToken: '',
      giteaToken: '',
      enableApiKeyAuth: true,
      apiKey: 'secret-key',
    });
    await app.ready();

    const diagnostics = await app.inject({
      method: 'GET',
      url: '/diagnostics/startup',
    });

    expect(diagnostics.statusCode).toBe(200);

    const unauthorized = await app.inject({
      method: 'POST',
      url: '/integrations/e2e',
      payload: { dryRun: true },
    });

    expect(unauthorized.statusCode).toBe(401);
    expect(unauthorized.json()).toMatchObject({
      error: {
        code: 'UNAUTHORIZED',
      },
    });

    const authorized = await app.inject({
      method: 'POST',
      url: '/integrations/e2e',
      headers: { 'x-api-key': 'secret-key' },
      payload: { dryRun: true },
    });

    expect(authorized.statusCode).toBe(200);
  });

  it('exposes request metrics counters', async () => {
    await app.inject({ method: 'GET', url: '/health' });
    await app.inject({ method: 'GET', url: '/version' });

    const firstMetrics = await app.inject({ method: 'GET', url: '/metrics' });
    const response = await app.inject({ method: 'GET', url: '/metrics' });

    expect(firstMetrics.statusCode).toBe(200);
    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      service: string;
      requestsTotal: number;
      responsesByStatus: Record<string, number>;
      responsesByRoute: Record<string, number>;
      uptimeSeconds: number;
    };

    expect(body.service).toBe('blackroad-os-operator');
    expect(body.requestsTotal).toBeGreaterThanOrEqual(3);
    expect(body.responsesByStatus['200']).toBeGreaterThanOrEqual(3);
    expect(body.responsesByRoute['/health']).toBeGreaterThanOrEqual(1);
    expect(body.responsesByRoute['/version']).toBeGreaterThanOrEqual(1);
    expect(body.responsesByRoute['/metrics']).toBeGreaterThanOrEqual(1);
  });

  it('returns typed validation errors for invalid chat payload shape', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/chat',
      payload: { wrong: 'field' },
    });

    expect(response.statusCode).toBe(400);
    expect(response.json()).toMatchObject({
      error: {
        code: 'VALIDATION_ERROR',
      },
    });
  });

  it('reports ready=true when Redis responds to ping', async () => {
    mockPing.mockResolvedValue('PONG');

    const response = await app.inject({ method: 'GET', url: '/ready' });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      ready: true,
      service: 'blackroad-os-operator',
      checks: {
        config: true,
        queue: true,
      },
    });
  });

  it('reports ready=false when Redis ping fails', async () => {
    mockPing.mockRejectedValue(new Error('redis down'));

    const response = await app.inject({ method: 'GET', url: '/ready' });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      ready: false,
      service: 'blackroad-os-operator',
      checks: {
        config: true,
        queue: false,
      },
    });
  });

  it('returns version metadata from config', async () => {
    const response = await app.inject({ method: 'GET', url: '/version' });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      service: 'blackroad-os-operator',
      version: '1.2.3-test',
      commit: 'deadbeef',
      env: 'test',
    });
  });

  it('validates chat input', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/chat',
      payload: { message: '   ' },
    });

    expect(response.statusCode).toBe(400);
    expect(response.json()).toMatchObject({ error: 'Bad Request' });
  });

  it('handles successful chat requests', async () => {
    mockGenerateChatResponse.mockResolvedValue({
      reply: 'Hello from Cece',
      trace: {
        llm_provider: 'ollama',
        model: 'llama-test',
        used_rag: false,
        response_time_ms: 42,
      },
    });

    const response = await app.inject({
      method: 'POST',
      url: '/chat',
      payload: { message: 'hello', userId: 'u1' },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      reply: 'Hello from Cece',
      trace: {
        llm_provider: 'ollama',
        model: 'llama-test',
        used_rag: false,
        response_time_ms: 42,
      },
    });
  });

  it('handles chat failures with 500', async () => {
    mockGenerateChatResponse.mockRejectedValue(new Error('provider timeout'));

    const response = await app.inject({
      method: 'POST',
      url: '/chat',
      payload: { message: 'hello' },
    });

    expect(response.statusCode).toBe(500);
    expect(response.json()).toMatchObject({
      error: 'Internal Server Error',
      message: 'provider timeout',
    });
  });

  it('returns llm health metadata', async () => {
    mockCheckLlmHealth.mockResolvedValue({
      healthy: true,
      models: ['llama-test'],
    });

    const response = await app.inject({ method: 'GET', url: '/llm/health' });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      service: 'llm-gateway',
      provider: 'ollama',
      configured_model: 'llama-test',
      ollama_url: 'http://ollama.test:11434',
      healthy: true,
      models: ['llama-test'],
    });
  });


  it('runs full integration e2e checks', async () => {
    mockRunIntegrationE2E.mockResolvedValue({
      ok: true,
      dryRun: false,
      results: [
        { provider: 'stripe', ok: true, status: 200, latencyMs: 10, detail: 'reachable' },
        { provider: 'git', ok: true, status: 200, latencyMs: 11, detail: 'reachable' },
        { provider: 'slack', ok: true, status: 200, latencyMs: 12, detail: 'reachable' },
        { provider: 'railway', ok: true, status: 200, latencyMs: 13, detail: 'reachable' },
        { provider: 'pis', ok: true, status: 200, latencyMs: 14, detail: 'reachable' },
        { provider: 'cloudflare', ok: true, status: 200, latencyMs: 15, detail: 'reachable' },
        { provider: 'gitea', ok: true, status: 200, latencyMs: 16, detail: 'reachable' },
      ],
    });

    const response = await app.inject({
      method: 'POST',
      url: '/integrations/e2e',
      payload: {
        providers: ['stripe', 'git', 'slack', 'railway', 'pis', 'cloudflare', 'gitea'],
        dryRun: false,
      },
    });

    expect(response.statusCode).toBe(200);
    expect(mockRunIntegrationE2E).toHaveBeenCalledWith({
      providers: ['stripe', 'git', 'slack', 'railway', 'pis', 'cloudflare', 'gitea'],
      dryRun: false,
    });

    expect(response.json()).toMatchObject({
      service: 'blackroad-os-operator',
      ok: true,
      dryRun: false,
    });
  });

  it('rejects invalid integration providers', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/integrations/e2e',
      payload: {
        providers: ['stripe', 'nope'],
      },
    });

    expect(response.statusCode).toBe(400);
    expect(response.json()).toMatchObject({
      error: {
        code: 'VALIDATION_ERROR',
      },
    });
  });

  it('supports dry-run mode for all integrations', async () => {
    mockRunIntegrationE2E.mockResolvedValue({
      ok: true,
      dryRun: true,
      results: [],
    });

    const response = await app.inject({
      method: 'POST',
      url: '/integrations/e2e',
      payload: { dryRun: true },
    });

    expect(response.statusCode).toBe(200);
    expect(mockRunIntegrationE2E).toHaveBeenCalledWith({
      providers: ['stripe', 'git', 'slack', 'railway', 'pis', 'cloudflare', 'gitea'],
      dryRun: true,
    });
    expect(response.json()).toMatchObject({ dryRun: true });
  });

  it('returns recent domain events', async () => {
    emitJobStarted('job-1', 'deploy');

    const response = await app.inject({ method: 'GET', url: '/events?limit=5' });

    expect(response.statusCode).toBe(200);
    const body = response.json() as { count: number; events: Array<{ type: string }> };
    expect(body.count).toBe(1);
    expect(body.events[0].type).toBe('job.started');
  });
});
