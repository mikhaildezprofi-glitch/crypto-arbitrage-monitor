import { performance } from "node:perf_hooks";
import {
  parseBlackBitPairId, parseBlackBitRate, parseWinanceRate,
} from "../src/worker.js";

const blackbitPairs = {
  result: "ok",
  status: 200,
  currency_pairs: [
    ...Array.from({ length: 80 }, (_, index) => ({
      id: index + 1,
      name: `PAIR${index}/USDT`,
    })),
    { id: 842, name: "ECR/USDT" },
  ],
};
const blackbitBook = { result: "ok", status: 200, last_rate: "0.052341" };
const winancePayload = {
  result: "ok",
  data: {
    markets: Array.from({ length: 120 }, (_, index) => ({
      id: index + 100,
      symbol: `TOKEN${index}/USDT`,
      last_price: "1.23",
    })),
    target: { id: 18, symbol: "ERUB/USDT", last_price: "0.04125" },
  },
};

function summarize(name, fn, iterations = 10000) {
  const samples = [];
  for (let index = 0; index < iterations; index += 1) {
    const start = performance.now();
    fn();
    samples.push((performance.now() - start) * 1000);
  }
  samples.sort((a, b) => a - b);
  const percentile = (p) => samples[Math.min(samples.length - 1, Math.floor(samples.length * p))];
  const total = samples.reduce((sum, value) => sum + value, 0);
  console.log(JSON.stringify({
    benchmark: name,
    iterations,
    unit: "microseconds",
    mean: Number((total / iterations).toFixed(2)),
    p50: Number(percentile(0.50).toFixed(2)),
    p95: Number(percentile(0.95).toFixed(2)),
    p99: Number(percentile(0.99).toFixed(2)),
    max: Number(samples.at(-1).toFixed(2)),
  }));
}

const pairId = parseBlackBitPairId(blackbitPairs);
summarize("blackbit_pair_resolution_81_items", () => parseBlackBitPairId(blackbitPairs));
summarize("blackbit_rate_normalization", () => parseBlackBitRate(blackbitBook, pairId));
summarize("winance_recursive_parse_121_items", () => parseWinanceRate(winancePayload));

console.log("NOTE: Node/V8 synthetic microbenchmark only. Not Cloudflare Workers CPU-time telemetry or a production quota guarantee.");
