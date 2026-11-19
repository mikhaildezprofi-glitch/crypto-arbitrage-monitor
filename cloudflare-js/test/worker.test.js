import test from "node:test";
import assert from "node:assert/strict";
import {
  parseBlackBitPairId, parseBlackBitRate, parseWinanceRate, readBoundedBody, scheduledHandler,
} from "../src/worker.js";

test("BlackBit resolves one exact ECR/USDT pair", () => {
  assert.equal(parseBlackBitPairId({
    result: "ok", status: 200,
    currency_pairs: [
      { id: 17, name: "BTC/USDT" },
      { id: 42, name: "ECR/USDT" },
    ],
  }), "42");
});

test("BlackBit rejects ambiguous pair metadata and invalid rates", () => {
  assert.throws(() => parseBlackBitPairId({
    result: "ok", status: 200,
    currency_pairs: [{ id: 42, name: "ECR/USDT" }, { id: 43, name: "ECR/USDT" }],
  }), /AMBIGUOUS/);
  assert.throws(() => parseBlackBitRate({ result: "ok", status: 200, last_rate: "0" }, "42"));
});

test("Winance requires pair ID 18 and ERUB/USDT identity", () => {
  const quote = parseWinanceRate({ pairs: [
    { id: 19, symbol: "ERUB/USDT", rate: "0.03" },
    { id: 18, symbol: "ERUB/USDT", rate: "0.041" },
  ]});
  assert.equal(quote.rate, "0.041");
  assert.equal(quote.indicative_only, 0);
  assert.throws(() => parseWinanceRate({ id: 18, symbol: "BTC/USDT", rate: "1" }), /MISSING/);
});

test("scheduled handler persists only deterministic mock quotes to D1", async () => {
  const calls = [];
  const db = {
    prepare(sql) {
      return {
        bind(...args) {
          return {
            first: async () => null,
            run: async () => { calls.push({ sql, args }); return {}; },
          };
        },
      };
    },
    batch: async (statements) => Promise.all(statements.map((statement) => statement.run())),
  };
  await scheduledHandler({ DB: db, MOCK_QUOTES: "true" }, new Date("2026-11-19T00:00:00Z"));
  assert.equal(calls.filter(x => x.sql.includes("INSERT INTO quote_observations")).length, 2);
  assert.equal(calls.filter(x => x.sql.includes("INSERT INTO source_status")).length, 2);
  assert.deepEqual(calls.map(x => x.args[0]).filter(x => ["blackbit", "winance"].includes(x)).sort(),
    ["blackbit", "blackbit", "winance", "winance"]);
});

test("mock mode never contacts providers", async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = async () => { fetchCalls += 1; throw new Error("unexpected network call"); };
  const db = {
    prepare(sql) {
      return { bind(...args) {
        return {
          first: async () => null,
          run: async () => ({ sql, args }),
        };
      }};
    },
    batch: async (statements) => Promise.all(statements.map((statement) => statement.run())),
  };
  try {
    await scheduledHandler({ DB: db, MOCK_QUOTES: "true" }, new Date("2026-11-19T00:00:00Z"));
    assert.equal(fetchCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("failure of one provider does not prevent polling the other", async () => {
  const originalFetch = globalThis.fetch;
  const requested = [];
  globalThis.fetch = async (url) => {
    requested.push(String(url));
    if (requested.length === 1) {
      return new Response(JSON.stringify({ result: "error", status: 500 }), {
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ pairs: [
      { id: 18, symbol: "ERUB/USDT", rate: "0.041" },
    ]}), { headers: { "content-type": "application/json" } });
  };
  const writes = [];
  const db = {
    prepare(sql) {
      return { bind(...args) {
        return {
          first: async () => null,
          run: async () => { writes.push({ sql, args }); return {}; },
        };
      }};
    },
    batch: async (statements) => Promise.all(statements.map((statement) => statement.run())),
  };
  try {
    await scheduledHandler({
      DB: db,
      MOCK_QUOTES: "false",
      BLACKBIT_API_BASE_URL: "https://blackbit.test/site",
      WINANCE_API_URL: "https://winance.test/site/currency_pairs",
    }, new Date("2026-11-19T00:00:00Z"));
    assert.equal(requested.length, 2);
    assert.equal(writes.some(x => x.sql.includes("INSERT INTO source_status") && x.args[0] === "blackbit" && x.args[2] === "Error"), true);
    assert.equal(writes.some(x => x.sql.includes("INSERT INTO quote_observations") && x.args[0] === "winance"), true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("scheduled handler fails closed without D1", async () => {
  await assert.rejects(() => scheduledHandler({}, new Date()), /D1_BINDING_UNAVAILABLE/);
});


test("Winance parser rejects excessively complex payloads", () => {
  const root = {};
  let cursor = root;
  for (let i = 0; i < 70; i++) {
    cursor.next = {};
    cursor = cursor.next;
  }
  assert.throws(() => parseWinanceRate(root), /PAYLOAD_TOO_COMPLEX/);
});

test("scheduled handler rejects invalid polling configuration", async () => {
  const calls = [];
  const db = {
    prepare(sql) {
      return { bind(...args) {
        return {
          first: async () => null,
          run: async () => { calls.push({ sql, args }); return {}; },
        };
      }};
    },
    batch: async (statements) => Promise.all(statements.map((statement) => statement.run())),
  };
  await assert.rejects(
    () => scheduledHandler({ DB: db, MOCK_QUOTES: "true", QUOTE_MAX_AGE_SECONDS: "NaN" },
      new Date("2026-11-19T00:00:00Z")),
    /INVALID_MAX_AGE/,
  );
  assert.equal(calls.length, 0);
});


test("bounded response reader accepts small bodies and rejects oversized streams", async () => {
  const small = new Response(new TextEncoder().encode('{"ok":true}'));
  assert.equal(await readBoundedBody(small, 32), '{"ok":true}');

  let cancelled = false;
  const stream = new ReadableStream({
    pull(controller) {
      controller.enqueue(new Uint8Array(8));
      controller.enqueue(new Uint8Array(8));
    },
    cancel() { cancelled = true; },
  });
  const oversized = new Response(stream);
  await assert.rejects(() => readBoundedBody(oversized, 10), /HTTP_RESPONSE_TOO_LARGE/);
  assert.equal(cancelled, true);
});

test("bounded response reader rejects a declared oversized body before reading", async () => {
  const response = new Response("{}", { headers: { "content-length": "100" } });
  await assert.rejects(() => readBoundedBody(response, 10), /HTTP_RESPONSE_TOO_LARGE/);
});
