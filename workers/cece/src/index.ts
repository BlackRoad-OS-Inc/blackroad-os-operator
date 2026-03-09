/**
 * CECE - BlackRoad Multi-Model AI Gateway
 *
 * Routes to: Lucidia (Ollama), Claude (Anthropic), ChatGPT (OpenAI),
 *            Cadillac (Custom), HuggingFace
 *
 * @owner Alexa Louise Amundson
 * @agent Cece
 * @system BlackRoad OS
 * @brhash cece-multimodel-v2
 */

export interface Env {
  // API Keys
  OPENAI_API_KEY: string;
  ANTHROPIC_API_KEY: string;
  HUGGINGFACE_API_KEY: string;

  // Endpoints
  OLLAMA_URL: string;        // Local Ollama (Lucidia)
  CADILLAC_URL: string;      // Cadillac agent
  OPERATOR_URL: string;      // Railway backend

  CECE_VERSION: string;
}

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-API-Key',
  'Content-Type': 'application/json',
  'X-Served-By': 'cece-multimodel',
  'X-BR-Signal': 'intercepted',
  'X-BR-Operator': 'alexa.operator.v1',
};

// Model routing configuration
const MODELS = {
  // Lucidia - Local Ollama models
  'lucidia': { provider: 'ollama', model: 'lucidia' },
  'llama3.2': { provider: 'ollama', model: 'llama3.2' },
  'mistral': { provider: 'ollama', model: 'mistral' },
  'phi3': { provider: 'ollama', model: 'phi3' },

  // Claude - Anthropic
  'claude': { provider: 'anthropic', model: 'claude-sonnet-4-20250514' },
  'claude-sonnet': { provider: 'anthropic', model: 'claude-sonnet-4-20250514' },
  'claude-opus': { provider: 'anthropic', model: 'claude-opus-4-20250514' },
  'claude-haiku': { provider: 'anthropic', model: 'claude-3-5-haiku-20241022' },

  // ChatGPT - OpenAI
  'chatgpt': { provider: 'openai', model: 'gpt-4o' },
  'gpt-4': { provider: 'openai', model: 'gpt-4o' },
  'gpt-4o': { provider: 'openai', model: 'gpt-4o' },
  'gpt-4o-mini': { provider: 'openai', model: 'gpt-4o-mini' },
  'o1': { provider: 'openai', model: 'o1' },

  // Cadillac - Custom BlackRoad agent
  'cadillac': { provider: 'cadillac', model: 'cadillac-v1' },

  // HuggingFace
  'huggingface': { provider: 'huggingface', model: 'meta-llama/Llama-2-70b-chat-hf' },
  'llama2': { provider: 'huggingface', model: 'meta-llama/Llama-2-70b-chat-hf' },
};

const DEFAULT_MODEL = 'claude';

// Mentions that unconditionally route to Ollama – no external provider fallback.
const OLLAMA_MENTION_RE = /@(copilot|lucidia|blackboxprogramming|ollama)\b/i;

function detectOllamaMention(message: string): boolean {
  return OLLAMA_MENTION_RE.test(message);
}

// CECE's personality system prompt
const CECE_SYSTEM = `You are Cece, BlackRoad's AI assistant. You are helpful, friendly, and knowledgeable.
You were created by Alexa Louise Amundson as part of BlackRoad OS.
You have access to multiple AI models and can route to the best one for each task.
Be concise but thorough. Always be honest about your capabilities.`;

function ceceStamp(model?: string) {
  return {
    agent: 'Cece',
    edge: 'Cloudflare',
    owner: 'Alexa Louise Amundson',
    infrastructure: 'BlackRoad OS',
    model_used: model || 'unknown',
    timestamp: new Date().toISOString(),
  };
}

// Provider implementations
async function callOllama(env: Env, model: string, message: string): Promise<string> {
  const url = env.OLLAMA_URL || 'http://localhost:11434';
  const resp = await fetch(`${url}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      prompt: message,
      system: CECE_SYSTEM,
      stream: false,
    }),
  });

  if (!resp.ok) throw new Error(`Ollama error: ${resp.status}`);
  const data = await resp.json() as any;
  return data.response || 'No response from Ollama';
}

async function callAnthropic(env: Env, model: string, message: string): Promise<string> {
  if (!env.ANTHROPIC_API_KEY) throw new Error('ANTHROPIC_API_KEY not configured');

  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      max_tokens: 4096,
      system: CECE_SYSTEM,
      messages: [{ role: 'user', content: message }],
    }),
  });

  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`Anthropic error: ${resp.status} - ${err}`);
  }

  const data = await resp.json() as any;
  return data.content?.[0]?.text || 'No response from Claude';
}

async function callOpenAI(env: Env, model: string, message: string): Promise<string> {
  if (!env.OPENAI_API_KEY) throw new Error('OPENAI_API_KEY not configured');

  const resp = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${env.OPENAI_API_KEY}`,
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: CECE_SYSTEM },
        { role: 'user', content: message },
      ],
      max_tokens: 4096,
    }),
  });

  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`OpenAI error: ${resp.status} - ${err}`);
  }

  const data = await resp.json() as any;
  return data.choices?.[0]?.message?.content || 'No response from ChatGPT';
}

async function callHuggingFace(env: Env, model: string, message: string): Promise<string> {
  if (!env.HUGGINGFACE_API_KEY) throw new Error('HUGGINGFACE_API_KEY not configured');

  const resp = await fetch(`https://api-inference.huggingface.co/models/${model}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${env.HUGGINGFACE_API_KEY}`,
    },
    body: JSON.stringify({
      inputs: `${CECE_SYSTEM}\n\nUser: ${message}\n\nAssistant:`,
      parameters: { max_new_tokens: 1024 },
    }),
  });

  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`HuggingFace error: ${resp.status} - ${err}`);
  }

  const data = await resp.json() as any;
  return data[0]?.generated_text || 'No response from HuggingFace';
}

async function callCadillac(env: Env, message: string): Promise<string> {
  const url = env.CADILLAC_URL || 'https://cadillac.blackroad.io';
  const resp = await fetch(`${url}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, agent: 'cece' }),
  });

  if (!resp.ok) throw new Error(`Cadillac error: ${resp.status}`);
  const data = await resp.json() as any;
  return data.response || data.message || 'No response from Cadillac';
}

// Main router
async function routeToModel(env: Env, modelKey: string, message: string): Promise<{ response: string; provider: string; model: string }> {
  const config = MODELS[modelKey as keyof typeof MODELS] || MODELS[DEFAULT_MODEL];
  const { provider, model } = config;

  let response: string;

  switch (provider) {
    case 'ollama':
      response = await callOllama(env, model, message);
      break;
    case 'anthropic':
      response = await callAnthropic(env, model, message);
      break;
    case 'openai':
      response = await callOpenAI(env, model, message);
      break;
    case 'huggingface':
      response = await callHuggingFace(env, model, message);
      break;
    case 'cadillac':
      response = await callCadillac(env, message);
      break;
    default:
      throw new Error(`Unknown provider: ${provider}`);
  }

  return { response, provider, model };
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    // Health check
    if (path === '/health' || path === '/') {
      return new Response(JSON.stringify({
        status: 'online',
        service: 'cece-multimodel',
        version: env.CECE_VERSION || '2.0.0',
        ...ceceStamp(),
        models: Object.keys(MODELS),
        providers: ['ollama/lucidia', 'anthropic/claude', 'openai/chatgpt', 'huggingface', 'cadillac'],
        endpoints: {
          chat: 'POST /chat { message, model? }',
          models: 'GET /models',
          health: 'GET /health',
          info: 'GET /info',
        },
        message: "Hi! I'm Cece with multi-model support! Try: lucidia, claude, chatgpt, cadillac, or huggingface!",
      }, null, 2), { status: 200, headers: CORS_HEADERS });
    }

    // Models list
    if (path === '/models' && request.method === 'GET') {
      return new Response(JSON.stringify({
        available_models: MODELS,
        default: DEFAULT_MODEL,
        providers: {
          ollama: ['lucidia', 'llama3.2', 'mistral', 'phi3'],
          anthropic: ['claude', 'claude-sonnet', 'claude-opus', 'claude-haiku'],
          openai: ['chatgpt', 'gpt-4', 'gpt-4o', 'gpt-4o-mini', 'o1'],
          huggingface: ['huggingface', 'llama2'],
          cadillac: ['cadillac'],
        },
        ...ceceStamp(),
      }, null, 2), { status: 200, headers: CORS_HEADERS });
    }

    // Info endpoint
    if (path === '/info' && request.method === 'GET') {
      return new Response(JSON.stringify({
        name: 'Cece',
        description: 'BlackRoad Multi-Model AI Gateway',
        capabilities: [
          'Multi-model routing (Lucidia, Claude, ChatGPT, Cadillac, HuggingFace)',
          'Automatic fallback between providers',
          'Edge-optimized responses via Cloudflare',
          'Context-aware conversations',
        ],
        ...ceceStamp(),
      }, null, 2), { status: 200, headers: CORS_HEADERS });
    }

    // Main chat endpoint
    if (path === '/chat') {
      if (request.method !== 'POST') {
        return new Response(JSON.stringify({
          error: 'Method not allowed. Use POST.',
          hint: 'POST /chat with { "message": "your message", "model": "claude" }',
        }), { status: 405, headers: CORS_HEADERS });
      }

      let body: any;
      try {
        body = await request.json();
      } catch {
        return new Response(JSON.stringify({
          error: 'Invalid JSON body',
          hint: 'Send valid JSON: { "message": "hello", "model": "claude" }',
        }), { status: 400, headers: CORS_HEADERS });
      }

      const { message, model, user_id } = body || {};

      if (!message || typeof message !== 'string') {
        return new Response(JSON.stringify({
          error: "Missing or invalid 'message' field",
          hint: 'Include a "message" string in your request body',
          available_models: Object.keys(MODELS),
        }), { status: 400, headers: CORS_HEADERS });
      }

      // @copilot / @lucidia / @blackboxprogramming / @ollama → always Ollama,
      // no external provider dependency.
      const ollamaMentioned = detectOllamaMention(message);
      const modelKey = ollamaMentioned ? 'lucidia' : (model || DEFAULT_MODEL).toLowerCase();
      const startTime = Date.now();

      try {
        const result = await routeToModel(env, modelKey, message);
        const latency = Date.now() - startTime;

        return new Response(JSON.stringify({
          response: result.response,
          model: {
            requested: ollamaMentioned ? 'ollama-via-mention' : modelKey,
            provider: result.provider,
            actual: result.model,
            mention_routed: ollamaMentioned,
          },
          edge: {
            location: (request.cf as any)?.colo || 'unknown',
            country: (request.cf as any)?.country || 'unknown',
            latency_ms: latency,
          },
          user_id: user_id || 'anonymous',
          ...ceceStamp(result.model),
        }, null, 2), { status: 200, headers: CORS_HEADERS });

      } catch (err: any) {
        console.error('CECE error:', err);

        // When routed by @mention, never fall back to an external provider.
        if (ollamaMentioned) {
          return new Response(JSON.stringify({
            error: 'Ollama unavailable',
            detail: err.message || 'Unknown error',
            hint: 'Ensure Ollama is running and OLLAMA_URL is reachable.',
            mention_routed: true,
            ...ceceStamp(),
          }), { status: 503, headers: CORS_HEADERS });
        }

        // Try fallback to another provider
        const fallbackProviders = ['anthropic', 'openai'];
        for (const fallback of fallbackProviders) {
          if (MODELS[modelKey as keyof typeof MODELS]?.provider !== fallback) {
            try {
              const fallbackModel = fallback === 'anthropic' ? 'claude' : 'chatgpt';
              const result = await routeToModel(env, fallbackModel, message);
              const latency = Date.now() - startTime;

              return new Response(JSON.stringify({
                response: result.response,
                model: {
                  requested: modelKey,
                  fallback_used: true,
                  provider: result.provider,
                  actual: result.model,
                },
                edge: {
                  location: (request.cf as any)?.colo || 'unknown',
                  latency_ms: latency,
                },
                ...ceceStamp(result.model),
              }, null, 2), { status: 200, headers: CORS_HEADERS });
            } catch {
              continue;
            }
          }
        }

        return new Response(JSON.stringify({
          error: 'All providers failed',
          detail: err.message || 'Unknown error',
          requested_model: modelKey,
          hint: 'Check API keys are configured. Try a different model.',
          available_models: Object.keys(MODELS),
          ...ceceStamp(),
        }), { status: 503, headers: CORS_HEADERS });
      }
    }

    // 404 for unknown paths
    return new Response(JSON.stringify({
      error: 'Not found',
      path,
      available: ['GET /', 'GET /health', 'GET /info', 'GET /models', 'POST /chat'],
      ...ceceStamp(),
    }), { status: 404, headers: CORS_HEADERS });
  },
};
