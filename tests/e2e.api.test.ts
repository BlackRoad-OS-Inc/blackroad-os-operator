import type { FastifyInstance } from 'fastify';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearEvents, emitJobStarted } from '../src/utils/eventBus.js';

const mockGenerateChatResponse = vi.fn();
const mockCheckLlmHealth = vi.fn();
const mockPing = vi.fn();

vi.mock('../src/services/llm.service.js', () => ({
  generateChatResponse: mockGenerateChatResponse,
  checkLlmHealth: mockCheckLlmHealth,
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
    expect(response.json()).toMatchObject({
      ok: true,
      service: 'blackroad-os-operator',
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

  it('returns recent domain events', async () => {
    emitJobStarted('job-1', 'deploy');

    const response = await app.inject({ method: 'GET', url: '/events?limit=5' });

    expect(response.statusCode).toBe(200);
    const body = response.json() as { count: number; events: Array<{ type: string }> };
    expect(body.count).toBe(1);
    expect(body.events[0].type).toBe('job.started');
  });
});
