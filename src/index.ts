import 'dotenv/config';

import { getConfig } from './config.js';
import { registerSampleJobProcessor } from './jobs/sample.job.js';
import { startHeartbeatScheduler } from './schedulers/heartbeat.scheduler.js';
import { buildApp } from './app.js';
import logger from './utils/logger.js';

const config = getConfig();

export function registerBackgroundJobs(): void {
  registerSampleJobProcessor();
  startHeartbeatScheduler();
}

export async function startServer(): Promise<void> {
  const app = buildApp(config);

  try {
    registerBackgroundJobs();

    await app.listen({ port: config.port, host: '0.0.0.0' });
    logger.info(
      {
        port: config.port,
        env: config.brOsEnv,
        version: config.version,
        commit: config.commit
      },
      'operator engine started'
    );
  } catch (error) {
    logger.error({ error }, 'failed to start operator engine');
    process.exit(1);
  }
}

startServer();

// TODO(op-next): add auth middleware and request signing
// TODO(op-next): expose agent registration endpoints
