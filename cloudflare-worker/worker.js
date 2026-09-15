const OPENAI_URL = 'https://api.openai.com/v1/responses';
const MODEL = 'gpt-5.6-terra';
const ALLOWED_ORIGIN = 'https://phill55188-ops.github.io';
const MAX_BODY_BYTES = 220000;

function cors(origin) {
  const h = {
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, X-SignalBrief-Access',
    'Access-Control-Max-Age': '86400',
    'Cache-Control': 'no-store',
    'Vary': 'Origin'
  };
  if (origin === ALLOWED_ORIGIN) h['Access-Control-Allow-Origin'] = origin;
  return h;
}

function json(data, status, origin) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...cors(origin)
    }
  });
}

function validAccess(request, env) {
  const supplied = request.headers.get('X-SignalBrief-Access') || '';
  return Boolean(env.SIGNALBRIEF_ACCESS_TOKEN) &&
         supplied === env.SIGNALBRIEF_ACCESS_TOKEN;
}

function extractText(response) {
  const chunks = [];
  for (const item of response.output || []) {
    if (item && item.type === 'message') {
      for (const part of item.content || []) {
        if (part && part.type === 'output_text' && part.text) {
          chunks.push(part.text);
        }
      }
    }
  }
  return chunks.join('').trim();
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin') || '';

    if (request.method === 'OPTIONS') {
      if (origin !== ALLOWED_ORIGIN) {
        return new Response(null, { status: 403, headers: cors(origin) });
      }
      return new Response(null, { status: 204, headers: cors(origin) });
    }

    if (origin && origin !== ALLOWED_ORIGIN) {
      return json({ error: 'Origin not allowed.' }, 403, origin);
    }

    if (!validAccess(request, env)) {
      return json({ error: 'Invalid SignalBrief access code.' }, 401, origin);
    }

    if (url.pathname === '/health' && request.method === 'GET') {
      return json({
        ok: true,
        service: 'SignalBrief secure OpenAI bridge',
        model: MODEL
      }, 200, origin);
    }

    if (url.pathname !== '/api/analyze' || request.method !== 'POST') {
      return json({ error: 'Not found.' }, 404, origin);
    }

    if (!env.OPENAI_API_KEY) {
      return json({ error: 'Backend secret OPENAI_API_KEY is missing.' }, 500, origin);
    }

    const contentLength = Number(request.headers.get('Content-Length') || 0);
    if (contentLength && contentLength > MAX_BODY_BYTES) {
      return json({ error: 'Request too large.' }, 413, origin);
    }

    let body;
    try {
      const raw = await request.text();
      if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
        return json({ error: 'Request too large.' }, 413, origin);
      }
      body = JSON.parse(raw);
    } catch {
      return json({ error: 'Invalid JSON request.' }, 400, origin);
    }

    if (typeof body.system !== 'string' || !body.system.trim()) {
      return json({ error: 'System instructions are required.' }, 400, origin);
    }
    if (typeof body.payload !== 'string' || !body.payload.trim()) {
      return json({ error: 'Payload is required.' }, 400, origin);
    }

    const openaiRequest = {
      model: MODEL,
      reasoning: { effort: 'medium' },
      max_output_tokens: 1800,
      input: [
        {
          role: 'developer',
          content: [{ type: 'input_text', text: body.system }]
        },
        {
          role: 'user',
          content: [{ type: 'input_text', text: body.payload }]
        }
      ]
    };

    let upstream;
    try {
      upstream = await fetch(OPENAI_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + env.OPENAI_API_KEY
        },
        body: JSON.stringify(openaiRequest)
      });
    } catch {
      return json({ error: 'Could not reach OpenAI.' }, 502, origin);
    }

    let data;
    try {
      data = await upstream.json();
    } catch {
      return json({ error: 'OpenAI returned unreadable data.' }, 502, origin);
    }

    if (!upstream.ok) {
      const detail = data?.error?.message || 'OpenAI request failed.';
      const status = upstream.status === 429 ? 429 : 502;
      return json({ error: String(detail) }, status, origin);
    }

    const text = extractText(data);
    if (!text) {
      return json({ error: 'OpenAI returned no text output.' }, 502, origin);
    }

    return json({
      text,
      model: MODEL,
      response_id: data.id || null
    }, 200, origin);
  }
};
