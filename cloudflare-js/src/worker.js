const DEFAULT_MAX_AGE_SECONDS = 900;
const DEFAULT_POLL_SECONDS = 300;
const HTTP_TIMEOUT_MS = 8000;
const MAX_RESPONSE_BYTES = 1_000_000;
const MAX_JSON_NODES = 10_000;
const MAX_JSON_DEPTH = 64;

function normalizePair(value) {
  return String(value ?? "").toUpperCase().replace(/[-_]/g, "/").replace(/[ \t\r\n]/g, "");
}

function checkEnvelope(payload, endpoint) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(`INVALID_${endpoint.toUpperCase()}_ENVELOPE`);
  }
  if (payload.result !== "ok" || payload.status !== 200) {
    throw new Error(`BAD_${endpoint.toUpperCase()}_STATUS`);
  }
  return payload;
}

export function parseBlackBitPairId(payload) {
  const data = checkEnvelope(payload, "currency_pairs");
  if (!Array.isArray(data.currency_pairs) || data.currency_pairs.length > MAX_JSON_NODES) {
    throw new Error("MISSING_OR_OVERSIZED_CURRENCY_PAIRS");
  }
  const matches = [];
  for (const item of data.currency_pairs) {
    if (!item || typeof item !== "object") continue;
    const name = normalizePair(item.name ?? item.symbol ?? item.pair);
    const base = normalizePair(item.base_currency);
    const quote = normalizePair(item.quoted_currency ?? item.quote_currency);
    if (name && name !== "ECR/USDT") continue;
    if (base && base !== "ECR") continue;
    if (quote && quote !== "USDT") continue;
    if (name === "ECR/USDT" || (base === "ECR" && quote === "USDT")) {
      const id = String(item.id ?? item.currency_pair_id ?? "");
      if (/^[1-9][0-9]*$/.test(id)) matches.push(id);
    }
  }
  const unique = [...new Set(matches)];
  if (unique.length !== 1) throw new Error("AMBIGUOUS_ECR_USDT_PAIR");
  return unique[0];
}

export function parseBlackBitRate(payload, pairId, observedAt = new Date()) {
  const data = checkEnvelope(payload, "order_book");
  const rate = Number(data.last_rate);
  if (!Number.isFinite(rate) || rate <= 0) throw new Error("INVALID_BLACKBIT_LAST_RATE");
  return {
    source: "blackbit", pair: "ECR/USDT", base_currency: "ECR",
    quote_currency: "USDT", rate: String(data.last_rate),
    observed_at: observedAt.toISOString(), indicative_only: 1,
    source_pair_id: String(pairId),
  };
}

function* walk(value) {
  const stack = [{ value, depth: 0 }];
  const seen = new Set();
  let visited = 0;
  while (stack.length) {
    const current = stack.pop();
    const item = current.value;
    if (!item || typeof item !== "object") continue;
    if (seen.has(item)) continue;
    seen.add(item);
    if (++visited > MAX_JSON_NODES || current.depth > MAX_JSON_DEPTH) {
      throw new Error("WINANCE_PAYLOAD_TOO_COMPLEX");
    }
    yield item;
    const children = Array.isArray(item) ? item : Object.values(item);
    for (const child of children) {
      if (child && typeof child === "object") {
        stack.push({ value: child, depth: current.depth + 1 });
      }
    }
  }
}

function isWinancePair(item) {
  const id = item.id ?? item.currency_pair_id ?? item.pair_id;
  const pair = normalizePair(item.symbol ?? item.pair ?? item.name ?? item.currency_pair);
  const base = normalizePair(item.base_currency);
  const quote = normalizePair(item.quoted_currency ?? item.quote_currency);
  if (String(id) !== "18") return false;
  if (pair && !["ERUB/USDT", "ERUBUSDT"].includes(pair)) return false;
  if (base && base !== "ERUB") return false;
  if (quote && quote !== "USDT") return false;
  return Boolean(pair || (base === "ERUB" && quote === "USDT"));
}

export function parseWinanceRate(payload, observedAt = new Date()) {
  for (const item of walk(payload)) {
    if (!isWinancePair(item)) continue;
    for (const key of ["rate", "price", "last_price", "value"]) {
      if (item[key] === undefined || item[key] === null) continue;
      const rate = Number(item[key]);
      if (Number.isFinite(rate) && rate > 0) {
        return {
          source: "winance", pair: "ERUB/USDT", base_currency: "ERUB",
          quote_currency: "USDT", rate: String(item[key]),
          observed_at: observedAt.toISOString(), indicative_only: 0,
          source_pair_id: "18",
        };
      }
    }
  }
  throw new Error("MISSING_WINANCE_ERUB_USDT_RATE");
}

export async function readBoundedBody(response, maxBytes = MAX_RESPONSE_BYTES) {
  const declaredLength = Number(response.headers.get("content-length") ?? 0);
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    await response.body?.cancel();
    throw new Error("HTTP_RESPONSE_TOO_LARGE");
  }
  if (!response.body) throw new Error("EMPTY_HTTP_RESPONSE");
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw new Error("HTTP_RESPONSE_TOO_LARGE");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

async function getJson(url) {
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json", "User-Agent": "CryptoArbitrageMonitor/0.1" },
    signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`HTTP_${response.status}`);
  let body;
  try {
    body = await readBoundedBody(response);
  } catch (error) {
    if (error?.message === "HTTP_RESPONSE_TOO_LARGE" ||
        error?.message === "EMPTY_HTTP_RESPONSE") throw error;
    throw new Error("INVALID_HTTP_RESPONSE_BODY");
  }
  try {
    return JSON.parse(body);
  } catch {
    throw new Error("INVALID_JSON_RESPONSE");
  }
}

async function fetchBlackBit(env, now) {
  let base = String(env.BLACKBIT_API_BASE_URL);
  while (base.endsWith("/")) base = base.slice(0, -1);
  const pairs = await getJson(`${base}/currency_pairs`);
  const pairId = parseBlackBitPairId(pairs);
  const query = new URLSearchParams({ currency_pair: pairId, depth: "100" });
  const book = await getJson(`${base}/v2/orders/book?${query}`);
  return parseBlackBitRate(book, pairId, now);
}

async function fetchWinance(env, now) {
  return parseWinanceRate(await getJson(String(env.WINANCE_API_URL)), now);
}

function positiveInteger(value, fallback, name) {
  const parsed = Number(value ?? fallback);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`INVALID_${name}`);
  return parsed;
}

async function isDue(db, source, intervalSeconds, now) {
  const row = await db.prepare(
    "SELECT last_attempt_at FROM source_status WHERE source = ?",
  ).bind(source).first();
  if (!row) return true;
  const last = Date.parse(row.last_attempt_at);
  return !Number.isFinite(last) || (now.getTime() - last) / 1000 >= intervalSeconds;
}

async function recordSuccess(db, quote, attemptedAt) {
  const observation = db.prepare(`INSERT INTO quote_observations
    (source, pair, base_currency, quote_currency, rate, observed_at, indicative_only, source_pair_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)`)
    .bind(quote.source, quote.pair, quote.base_currency, quote.quote_currency,
      quote.rate, quote.observed_at, quote.indicative_only, quote.source_pair_id);
  const status = db.prepare(`INSERT INTO source_status
    (source, status, last_attempt_at, last_success_at, error_type)
    VALUES (?, 'fresh', ?, ?, NULL)
    ON CONFLICT(source) DO UPDATE SET status='fresh',
    last_attempt_at=excluded.last_attempt_at, last_success_at=excluded.last_success_at,
    error_type=NULL`)
    .bind(quote.source, attemptedAt.toISOString(), quote.observed_at);
  await db.batch([observation, status]);
}

async function recordFailure(db, source, error, attemptedAt) {
  await db.prepare(`INSERT INTO source_status
    (source, status, last_attempt_at, last_success_at, error_type)
    VALUES (?, 'unavailable', ?, NULL, ?)
    ON CONFLICT(source) DO UPDATE SET status='unavailable',
    last_attempt_at=excluded.last_attempt_at, error_type=excluded.error_type`)
    .bind(source, attemptedAt.toISOString(), error?.name || "Error").run();
}

function mockQuote(source, now) {
  return source === "blackbit"
    ? { source, pair: "ECR/USDT", base_currency: "ECR", quote_currency: "USDT",
        rate: "0.05", observed_at: now.toISOString(), indicative_only: 1, source_pair_id: "ci-mock" }
    : { source, pair: "ERUB/USDT", base_currency: "ERUB", quote_currency: "USDT",
        rate: "0.04", observed_at: now.toISOString(), indicative_only: 0, source_pair_id: "18" };
}

export async function scheduledHandler(env, now = new Date()) {
  if (!env?.DB) throw new Error("D1_BINDING_UNAVAILABLE");
  const maxAge = positiveInteger(env.QUOTE_MAX_AGE_SECONDS, DEFAULT_MAX_AGE_SECONDS, "MAX_AGE");
  const providers = {
    blackbit: [positiveInteger(env.BLACKBIT_POLL_SECONDS, DEFAULT_POLL_SECONDS, "BLACKBIT_INTERVAL"), fetchBlackBit],
    winance: [positiveInteger(env.WINANCE_POLL_SECONDS, DEFAULT_POLL_SECONDS, "WINANCE_INTERVAL"), fetchWinance],
  };
  for (const [source, [interval, fetcher]] of Object.entries(providers)) {
    try {
      if (!(await isDue(env.DB, source, interval, now))) continue;
      const quote = String(env.MOCK_QUOTES).toLowerCase() === "true"
        ? mockQuote(source, now) : await fetcher(env, now);
      const observed = Date.parse(quote.observed_at);
      const age = (now.getTime() - observed) / 1000;
      if (!Number.isFinite(Number(quote.rate)) || Number(quote.rate) <= 0 ||
          !Number.isFinite(observed) || age < 0 || age > maxAge) {
        throw new Error("INVALID_OR_STALE_QUOTE");
      }
      await recordSuccess(env.DB, quote, now);
    } catch (error) {
      try {
        await recordFailure(env.DB, source, error, now);
      } catch {
        // A D1 status-write failure must not prevent polling the other provider.
      }
    }
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/health") {
      return new Response("Not found", { status: 404 });
    }
    if (!env?.DB) return Response.json({ error: "D1_BINDING_UNAVAILABLE" }, { status: 503 });
    try {
      const result = await env.DB.prepare(
        "SELECT source, status, last_attempt_at, last_success_at, error_type FROM source_status ORDER BY source",
      ).all();
      const maxAge = positiveInteger(env.QUOTE_MAX_AGE_SECONDS, DEFAULT_MAX_AGE_SECONDS, "MAX_AGE");
      const now = Date.now();
      const sources = (result.results ?? []).map((row) => {
        const lastSuccess = row.last_success_at ? Date.parse(row.last_success_at) : NaN;
        const ageSeconds = Number.isFinite(lastSuccess) ? (now - lastSuccess) / 1000 : null;
        const isFresh = ageSeconds !== null && ageSeconds >= 0 && ageSeconds <= maxAge;
        const status = row.status === "unavailable" ? "unavailable" : isFresh ? "fresh" : "stale";
        return { ...row, status, age_seconds: ageSeconds === null ? null : Math.max(0, Math.floor(ageSeconds)) };
      });
      return Response.json({ sources });
    } catch {
      return Response.json({ error: "D1_QUERY_FAILED" }, { status: 503 });
    }
  },
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(scheduledHandler(env));
  },
};
