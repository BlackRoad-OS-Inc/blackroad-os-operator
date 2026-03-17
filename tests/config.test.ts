import { describe, it, expect, afterEach } from 'vitest';

import { getConfig } from '../src/config.js';

describe('config', () => {
  // Store original env vars
  const originalEnv = { ...process.env };

  afterEach(() => {
    // Restore original env vars
    process.env = { ...originalEnv };
  });

  describe('getConfig', () => {
    it('should return default config when no env vars set', () => {
      // Clear relevant env vars
      delete process.env.PORT;
      delete process.env.NODE_ENV;
      delete process.env.BR_OS_ENV;
      delete process.env.BR_OS_OPERATOR_VERSION;
      delete process.env.BR_OS_OPERATOR_COMMIT;
      delete process.env.REDIS_URL;
      delete process.env.BR_OS_QUEUE_URL;
      delete process.env.LOG_LEVEL;
      delete process.env.BR_OS_OPERATOR_MAX_CONCURRENCY;
      delete process.env.BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS;

      const config = getConfig();

      expect(config.port).toBe(4000);
      expect(config.nodeEnv).toBe('development');
      expect(config.brOsEnv).toBe('local');
      expect(config.version).toBe('0.0.1');
      expect(config.commit).toBe('UNKNOWN');
      expect(config.redisUrl).toBe('redis://localhost:6379');
      expect(config.logLevel).toBe('info');
      expect(config.maxConcurrency).toBe(10);
      expect(config.defaultTimeoutSeconds).toBe(300);
    });

    it('should use env vars when provided', () => {
      process.env.PORT = '5000';
      process.env.NODE_ENV = 'production';
      process.env.BR_OS_ENV = 'prod';
      process.env.BR_OS_OPERATOR_VERSION = '1.2.3';
      process.env.BR_OS_OPERATOR_COMMIT = 'abc123def';
      process.env.REDIS_URL = 'redis://prod-redis:6379';
      process.env.LOG_LEVEL = 'warn';
      process.env.BR_OS_OPERATOR_MAX_CONCURRENCY = '20';
      process.env.BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS = '600';

      const config = getConfig();

      expect(config.port).toBe(5000);
      expect(config.nodeEnv).toBe('production');
      expect(config.brOsEnv).toBe('prod');
      expect(config.version).toBe('1.2.3');
      expect(config.commit).toBe('abc123def');
      expect(config.redisUrl).toBe('redis://prod-redis:6379');
      expect(config.logLevel).toBe('warn');
      expect(config.maxConcurrency).toBe(20);
      expect(config.defaultTimeoutSeconds).toBe(600);
    });

    it('should prefer BR_OS_QUEUE_URL over default redis URL', () => {
      delete process.env.REDIS_URL;
      process.env.BR_OS_QUEUE_URL = 'redis://queue-redis:6379';

      const config = getConfig();

      expect(config.redisUrl).toBe('redis://queue-redis:6379');
    });

    it('should prefer REDIS_URL over BR_OS_QUEUE_URL', () => {
      process.env.REDIS_URL = 'redis://primary-redis:6379';
      process.env.BR_OS_QUEUE_URL = 'redis://queue-redis:6379';

      const config = getConfig();

      expect(config.redisUrl).toBe('redis://primary-redis:6379');
    });


    it('should require API_KEY when API key auth is enabled', () => {
      process.env.ENABLE_API_KEY_AUTH = 'true';
      delete process.env.API_KEY;

      expect(() => getConfig()).toThrow('API_KEY must be set when ENABLE_API_KEY_AUTH=true');
    });

    it('should throw error for invalid port', () => {
      process.env.PORT = 'invalid';

      expect(() => getConfig()).toThrow('Invalid PORT configuration');
    });

    it('should throw error for negative port', () => {
      process.env.PORT = '-1';

      expect(() => getConfig()).toThrow('Invalid PORT configuration');
    });

    it('should throw error for invalid max concurrency', () => {
      process.env.BR_OS_OPERATOR_MAX_CONCURRENCY = 'invalid';

      expect(() => getConfig()).toThrow('Invalid BR_OS_OPERATOR_MAX_CONCURRENCY configuration');
    });

    it('should throw error for negative max concurrency', () => {
      process.env.BR_OS_OPERATOR_MAX_CONCURRENCY = '-1';

      expect(() => getConfig()).toThrow('Invalid BR_OS_OPERATOR_MAX_CONCURRENCY configuration');
    });

    it('should throw error for invalid timeout', () => {
      process.env.BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS = 'invalid';

      expect(() => getConfig()).toThrow(
        'Invalid BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS configuration'
      );
    });

    it('should throw error for negative timeout', () => {
      process.env.BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS = '-1';

      expect(() => getConfig()).toThrow(
        'Invalid BR_OS_OPERATOR_DEFAULT_TIMEOUT_SECONDS configuration'
      );
    });
  });
});
