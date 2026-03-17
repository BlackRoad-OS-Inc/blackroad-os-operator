import { getConfig } from '../config.js';
import logger from '../utils/logger.js';

export type IntegrationProvider =
  | 'stripe'
  | 'git'
  | 'slack'
  | 'railway'
  | 'pis'
  | 'cloudflare'
  | 'gitea';

export interface IntegrationCheckInput {
  providers: IntegrationProvider[];
  dryRun?: boolean;
}

export interface IntegrationProviderResult {
  provider: IntegrationProvider;
  ok: boolean;
  status: number;
  latencyMs: number;
  detail: string;
}

export interface IntegrationCheckResult {
  ok: boolean;
  dryRun: boolean;
  results: IntegrationProviderResult[];
}

const providerUrls: Record<IntegrationProvider, string> = {
  stripe: 'https://api.stripe.com/v1/charges?limit=1',
  git: 'https://api.github.com/rate_limit',
  slack: 'https://slack.com/api/api.test',
  railway: 'https://backboard.railway.com/graphql/v2',
  pis: 'http://127.0.0.1:8080/health',
  cloudflare: 'https://api.cloudflare.com/client/v4/user/tokens/verify',
  gitea: 'https://gitea.com/api/v1/version',
};

function getHeaders(provider: IntegrationProvider): Record<string, string> {
  const config = getConfig();

  switch (provider) {
    case 'stripe':
      return config.stripeApiKey ? { Authorization: `Bearer ${config.stripeApiKey}` } : {};
    case 'slack':
      return config.slackBotToken ? { Authorization: `Bearer ${config.slackBotToken}` } : {};
    case 'cloudflare':
      return config.cloudflareApiToken ? { Authorization: `Bearer ${config.cloudflareApiToken}` } : {};
    case 'railway':
      return config.railwayApiToken ? { Authorization: `Bearer ${config.railwayApiToken}` } : {};
    case 'gitea':
      return config.giteaToken ? { Authorization: `token ${config.giteaToken}` } : {};
    default:
      return {};
  }
}

async function runSingle(provider: IntegrationProvider, dryRun: boolean): Promise<IntegrationProviderResult> {
  const started = Date.now();

  if (dryRun) {
    return {
      provider,
      ok: true,
      status: 200,
      latencyMs: Date.now() - started,
      detail: 'dry-run: provider check skipped',
    };
  }

  const url = providerUrls[provider];

  try {
    const response = await fetch(url, {
      method: provider === 'railway' ? 'POST' : 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...getHeaders(provider),
      },
      body:
        provider === 'railway'
          ? JSON.stringify({ query: '{ me { email } }' })
          : undefined,
    });

    const ok = response.ok;

    return {
      provider,
      ok,
      status: response.status,
      latencyMs: Date.now() - started,
      detail: ok ? 'reachable' : 'unhealthy response',
    };
  } catch (error) {
    logger.warn({ provider, error }, 'integration check failed');

    return {
      provider,
      ok: false,
      status: 0,
      latencyMs: Date.now() - started,
      detail: error instanceof Error ? error.message : 'request failed',
    };
  }
}

export async function runIntegrationE2E(input: IntegrationCheckInput): Promise<IntegrationCheckResult> {
  const uniqueProviders = Array.from(new Set(input.providers));
  const dryRun = input.dryRun ?? false;

  const results = await Promise.all(uniqueProviders.map((provider) => runSingle(provider, dryRun)));

  return {
    ok: results.every((result) => result.ok),
    dryRun,
    results,
  };
}
