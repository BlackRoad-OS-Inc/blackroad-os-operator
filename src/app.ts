import Fastify, { type FastifyInstance } from 'fastify';

import type { OperatorConfig } from './config.js';
import { getConfig } from './config.js';
import { connection } from './queues/index.js';
import { runIntegrationE2E, type IntegrationProvider } from './services/integrations.service.js';
import { checkLlmHealth, generateChatResponse, type ChatRequest } from './services/llm.service.js';
import { getEventCount, getRecentEvents } from './utils/eventBus.js';
import logger from './utils/logger.js';

interface ChatRequestBody {
  message: string;
  userId?: string;
  model?: string;
}

interface IntegrationRequestBody {
  providers?: IntegrationProvider[];
  dryRun?: boolean;
}

const integrationProviders: IntegrationProvider[] = [
  'stripe',
  'git',
  'slack',
  'railway',
  'pis',
  'cloudflare',
  'gitea',
];

const chatBodySchema = {
  type: 'object',
  required: ['message'],
  additionalProperties: false,
  properties: {
    message: { type: 'string', minLength: 1 },
    userId: { type: 'string' },
    model: { type: 'string' },
  },
} as const;

const integrationsBodySchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    providers: {
      type: 'array',
      minItems: 1,
      items: { type: 'string', enum: integrationProviders },
      uniqueItems: true,
    },
    dryRun: { type: 'boolean' },
  },
} as const;

export function buildApp(config: OperatorConfig = getConfig()): FastifyInstance {
  const app = Fastify({ loggerInstance: logger });

  const startedAt = Date.now();
  const metrics = {
    requestsTotal: 0,
    responsesByStatus: {} as Record<string, number>,
    responsesByRoute: {} as Record<string, number>,
  };

  app.addHook('onRequest', async (request, reply) => {
    reply.header('x-request-id', request.id);
  });

  app.setErrorHandler((error, request, reply) => {
    const statusCode = error.statusCode ?? 500;
    const isValidationError = Boolean((error as { validation?: unknown }).validation);

    const payload = {
      error: {
        code: isValidationError ? 'VALIDATION_ERROR' : statusCode >= 500 ? 'INTERNAL_ERROR' : 'BAD_REQUEST',
        message: statusCode >= 500 ? 'Internal Server Error' : error.message,
        traceId: request.id,
      },
    };

    if (statusCode >= 500) {
      request.log.error({ err: error }, 'request failed');
    }

    reply.status(statusCode).send(payload);
  });


  app.addHook('onResponse', async (request, reply) => {
    metrics.requestsTotal += 1;

    const statusKey = String(reply.statusCode);
    metrics.responsesByStatus[statusKey] = (metrics.responsesByStatus[statusKey] ?? 0) + 1;

    const routeKey = request.routeOptions.url || request.url;
    metrics.responsesByRoute[routeKey] = (metrics.responsesByRoute[routeKey] ?? 0) + 1;
  });

  app.get('/health', async () => ({
    ok: true,
    service: 'blackroad-os-operator',
    timestamp: new Date().toISOString()
  }));

  app.get('/ready', async () => {
    let queueHealthy = false;

    try {
      const pong = await connection.ping();
      queueHealthy = pong === 'PONG';
    } catch (error) {
      logger.warn({ error }, 'queue readiness check failed');
    }

    const checks = {
      config: true,
      queue: queueHealthy
    };

    return {
      ready: Object.values(checks).every((check) => check === true),
      service: 'blackroad-os-operator',
      checks
    };
  });


  app.get('/metrics', async () => ({
    service: 'blackroad-os-operator',
    uptimeSeconds: Math.floor((Date.now() - startedAt) / 1000),
    requestsTotal: metrics.requestsTotal,
    responsesByStatus: metrics.responsesByStatus,
    responsesByRoute: metrics.responsesByRoute,
  }));

  app.get('/version', async () => ({
    service: 'blackroad-os-operator',
    version: config.version,
    commit: config.commit,
    env: config.brOsEnv
  }));

  app.post<{ Body: ChatRequestBody }>('/chat', { schema: { body: chatBodySchema } }, async (request, reply) => {
    const { message, userId, model } = request.body;

    if (!message || typeof message !== 'string' || message.trim().length === 0) {
      return reply.status(400).send({
        error: 'Bad Request',
        message: 'message field is required and must be a non-empty string'
      });
    }

    try {
      const chatRequest: ChatRequest = {
        message: message.trim(),
        userId,
        model,
      };

      const response = await generateChatResponse(chatRequest);

      return {
        reply: response.reply,
        trace: response.trace,
      };
    } catch (error) {
      logger.error({ error, message }, 'Chat request failed');
      return reply.status(500).send({
        error: 'Internal Server Error',
        message: error instanceof Error ? error.message : 'Failed to generate response'
      });
    }
  });

  app.get('/llm/health', async () => {
    const health = await checkLlmHealth();
    return {
      service: 'llm-gateway',
      provider: config.llmProvider,
      configured_model: config.ollamaModel,
      ollama_url: config.ollamaUrl,
      ...health
    };
  });
  app.post<{ Body: IntegrationRequestBody }>(
    '/integrations/e2e',
    { schema: { body: integrationsBodySchema } },
    async (request) => {
    const providers = request.body.providers ?? integrationProviders;

    const result = await runIntegrationE2E({
      providers,
      dryRun: request.body.dryRun ?? false,
    });

    return {
      service: 'blackroad-os-operator',
      ...result,
    };
  });

  app.get('/events', async (request) => {
    const query = request.query as { limit?: string | number };
    const limit = Number(query.limit ?? 100);

    return {
      count: getEventCount(),
      events: getRecentEvents(Number.isFinite(limit) ? limit : 100)
    };
  });

  return app;
}
