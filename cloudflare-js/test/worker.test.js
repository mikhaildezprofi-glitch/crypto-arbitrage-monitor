import test from "node:test";
import assert from "node:assert/strict";
import {
  parseBlackBitPairId, parseBlackBitRate, parseWinanceRate, scheduledHandler,
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
