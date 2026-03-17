/**
 * Configuration module for blackroad-os-operator.
 * Reads typed settings from environment variables with safe defaults.
 */

export interface OperatorConfig {
  /** Server port */
  port: number;

  /** Node environment (development, staging, production) */
  nodeEnv: string;

  /** BlackRoad OS environment identifier */
  brOsEnv: string;

  /** Service version */
  version: string;

  /** Git commit SHA */
  commit: string;

  /** Redis connection URL */
  redisUrl: string;

  /** Log level for pino */
  logLevel: string;

  /** Maximum concurrency for workers */
  maxConcurrency: number;

  /** Default job timeout in seconds */
  defaultTimeoutSeconds: number;

  /** LLM Provider (ollama, openai, etc.) */
  llmProvider: string;

  /** Ollama URL for LLM calls */
  ollamaUrl: string;

  /** Default Ollama model to use */
  ollamaModel: string;

  /** RAG API URL for context retrieval */
  ragApiUrl: string;


  /** Stripe API key for E2E integration checks */
  stripeApiKey: string;

  /** Slack bot token for E2E integration checks */
  slackBotToken: string;

  /** Railway API token for E2E integration checks */
  railwayApiToken: string;

  /** Cloudflare API token for E2E integration checks */
  cloudflareApiToken: string;

  /** Gitea API token for E2E integration checks */
  giteaToken: string;
}

/**
 * Load and validate configuration from environment variables.
 * Fails fast for critical missing values, provides safe defaults otherwise.
 */
export function getConfig(): OperatorConfig {
  const config: OperatorConfig = {
    port: Number(process.env.PORT ?? 4000),
    nodeEnv: process.env.NODE_ENV ?? 'development',
    brOsEnv: process.env.BR_OS_ENV ?? 'local',
    version: process.env.BR_OS_OPERATOR_VERSION ?? '0.0.1',
    commit: process.env.BR_OS_OPERATOR_COMMIT ?? 'UNKNOWN',
    redisUrl: process.env.REDIS_URL ?? process.env.BR_OS_QUEUE_URL ?? 'redis://localhost:6379',
    logLevel: process.env.LOG_LEVEL ?? 'info',
    maxConcurrency: Number(process.env.BR_OS_OPERATOR_MAX_CONCURRENCY ?? 10),
    defaultTimeoutSeconds: Number(process.env.BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS ?? 300),
    llmProvider: process.env.LLM_PROVIDER ?? 'ollama',
    ollamaUrl: process.env.OLLAMA_URL ?? 'http://gpt-oss-model.railway.internal:11434',
    ollamaModel: process.env.OLLAMA_MODEL ?? 'llama3.2:1b',
    ragApiUrl: process.env.RAG_API_URL ?? 'http://rag-api.railway.internal:8000',
    stripeApiKey: process.env.STRIPE_API_KEY ?? '',
    slackBotToken: process.env.SLACK_BOT_TOKEN ?? '',
    railwayApiToken: process.env.RAILWAY_API_TOKEN ?? '',
    cloudflareApiToken: process.env.CLOUDFLARE_API_TOKEN ?? '',
    giteaToken: process.env.GITEA_TOKEN ?? '',
  };

  // Validate critical values
  if (isNaN(config.port) || config.port <= 0) {
    throw new Error('Invalid PORT configuration');
  }

  if (isNaN(config.maxConcurrency) || config.maxConcurrency <= 0) {
    throw new Error('Invalid BR_OS_OPERATOR_MAX_CONCURRENCY configuration');
  }

  if (isNaN(config.defaultTimeoutSeconds) || config.defaultTimeoutSeconds <= 0) {
    throw new Error('Invalid BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS configuration');
  }

  return config;
}
