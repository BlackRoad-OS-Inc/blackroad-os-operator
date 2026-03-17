import { beforeEach, describe, expect, it, vi } from 'vitest';

import { runIntegrationE2E } from '../src/services/integrations.service.js';

describe('runIntegrationE2E', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('returns success in dry-run mode', async () => {
    const result = await runIntegrationE2E({
      providers: ['stripe', 'git', 'slack', 'railway', 'pis', 'cloudflare', 'gitea'],
      dryRun: true,
    });

    expect(result.ok).toBe(true);
    expect(result.dryRun).toBe(true);
    expect(result.results).toHaveLength(7);
    expect(result.results.every((entry) => entry.ok)).toBe(true);
  });

  it('marks provider unhealthy when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));

    const result = await runIntegrationE2E({
      providers: ['stripe'],
      dryRun: false,
    });

    expect(result.ok).toBe(false);
    expect(result.results[0]).toMatchObject({
      provider: 'stripe',
      ok: false,
      status: 0,
    });
  });

  it('deduplicates providers before running checks', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
      })
    );

    const result = await runIntegrationE2E({
      providers: ['git', 'git', 'gitea'],
      dryRun: false,
    });

    expect(result.results).toHaveLength(2);
  });
});
