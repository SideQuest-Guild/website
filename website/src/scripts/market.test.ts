// Run with `node --test src/scripts/*.test.ts` (see package.json's "test:unit"). Pure module, no browser needed.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  changeArrow,
  cooldownLabel,
  formatCount,
  formatMarketMoney,
  levelBandOverlaps,
  marketSparkline,
  zoneLine,
} from "./market.ts";

test('levelBandOverlaps: "all" always matches', () => {
  assert.equal(levelBandOverlaps("all", 1, 5), true);
  assert.equal(levelBandOverlaps("all", 50, 60), true);
});

test("levelBandOverlaps: a band matches a pick whose range overlaps it", () => {
  assert.equal(levelBandOverlaps("1-24", 1, 10), true);
  assert.equal(levelBandOverlaps("1-24", 20, 30), true);
  assert.equal(levelBandOverlaps("1-24", 25, 44), false);
  assert.equal(levelBandOverlaps("45-60", 40, 50), true);
  assert.equal(levelBandOverlaps("45-60", 1, 20), false);
});

test("levelBandOverlaps: an unknown band id matches everything", () => {
  assert.equal(levelBandOverlaps("no-such-band", 1, 5), true);
});

test("formatCount: under 10 keeps one decimal", () => {
  assert.equal(formatCount(8), "8.0");
  assert.equal(formatCount(1.7), "1.7");
});

test("formatCount: 10 and up rounds to a whole number", () => {
  assert.equal(formatCount(55), "55");
  assert.equal(formatCount(213.3), "213");
});

test("formatCount: large counts get a thousands separator", () => {
  assert.equal(formatCount(3847), "3,847");
  assert.equal(formatCount(40775.4), "40,775");
  assert.equal(formatCount(12040.1), "12,040");
});

test("cooldownLabel: no cooldown means no note", () => {
  assert.equal(cooldownLabel(null), "");
});

test("cooldownLabel: common transmute cooldowns read in plain words", () => {
  assert.equal(cooldownLabel(24), "Once a day");
  assert.equal(cooldownLabel(48), "Once every 2 days");
  assert.equal(cooldownLabel(96), "Once every 4 days");
});

test("cooldownLabel: a cooldown under a day reads in hours", () => {
  assert.equal(cooldownLabel(12), "Once every 12 hours");
});

test("changeArrow: null means no history yet", () => {
  const result = changeArrow(null);
  assert.equal(result.direction, "flat");
  assert.equal(result.symbol, "");
});

test("changeArrow: a rise is signed and arrows up", () => {
  const result = changeArrow(12.34);
  assert.equal(result.direction, "up");
  assert.equal(result.symbol, "\u25b2");
  assert.equal(result.text, "+12.3%");
});

test("changeArrow: a drop arrows down without a plus sign", () => {
  const result = changeArrow(-8);
  assert.equal(result.direction, "down");
  assert.equal(result.symbol, "\u25bc");
  assert.equal(result.text, "-8%");
});

test("changeArrow: under 1% reads steady, not up or down 0%", () => {
  const result = changeArrow(0.9);
  assert.equal(result.direction, "flat");
  assert.equal(result.text, "Steady");
});

test("changeArrow: 1% or more still arrows, even rounded", () => {
  const result = changeArrow(1.04);
  assert.equal(result.direction, "up");
  assert.equal(result.text, "+1%");
});

test("formatMarketMoney: under 10 silver shows silver and copper, or just copper", () => {
  assert.equal(formatMarketMoney(33), "33c");
  assert.equal(formatMarketMoney(190), "1s 90c");
});

test("formatMarketMoney: a round silver amount drops the zero copper", () => {
  assert.equal(formatMarketMoney(100), "1s");
});

test("formatMarketMoney: 10 silver and up shows whole silver", () => {
  assert.equal(formatMarketMoney(1000), "10s");
  assert.equal(formatMarketMoney(3500), "35s");
});

test("formatMarketMoney: 1 gold and up shows gold and silver, rounded", () => {
  assert.equal(formatMarketMoney(14350), "1g 44s");
  assert.equal(formatMarketMoney(90000), "9g");
});

test("formatMarketMoney: 100 gold and up shows whole gold with a thousands separator", () => {
  assert.equal(formatMarketMoney(1_280_000), "128g");
  assert.equal(formatMarketMoney(12_350_000), "1,235g");
});

test("formatMarketMoney: rounding into the next bucket promotes format", () => {
  assert.equal(formatMarketMoney(999_999), "100g");
});

test("zoneLine: joins zones with their level range, lowest first", () => {
  const line = zoneLine([
    { name: "Westfall", min_level: 10, max_level: 20 },
    { name: "Redridge Mountains", min_level: 15, max_level: 25 },
  ]);
  assert.equal(line, "Westfall 10-20, Redridge Mountains 15-25");
});

test("marketSparkline: fewer than two points draws nothing", () => {
  assert.equal(marketSparkline([]), "");
  assert.equal(marketSparkline([{ day: "2026-11-01", price: 100 }]), "");
});

test("marketSparkline: two or more points draws a polyline svg", () => {
  const svg = marketSparkline([
    { day: "2026-11-01", price: 100 },
    { day: "2026-11-02", price: 150 },
  ]);
  assert.match(svg, /<svg class="market-sparkline"/);
  assert.match(svg, /<polyline points="/);
});
