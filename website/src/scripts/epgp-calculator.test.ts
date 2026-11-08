// Run with `node --test src/scripts/*.test.ts` (see package.json's "test:unit"). Pure module, no browser needed.
import assert from "node:assert/strict";
import { test } from "node:test";

import type { EpgpRules } from "./api";
import {
  compareWinner,
  lootGp,
  lootMainSpecGp,
  projectDecayOnly,
  projectMember,
  raidEp,
  rankAmong,
  roundHalfUp,
  type LootPlan,
  type RaidPlan,
} from "./epgp-calculator.ts";

const RULES: EpgpRules = {
  ep: { boss_kill: 10, progress: 10, on_time: 5, full_night: 5 },
  gp: { INVTYPE_HEAD: 100, INVTYPE_TRINKET: 125, INVTYPE_2HWEAPON: 200 },
  chase_multiplier: 1.5,
  legendary_gp: 300,
  os_percent: 10,
  base_gp: 100,
  min_gp: 100,
  decay_percent: 15,
  trial_days: 14,
  weekly_reset_weekday: 1,
  weekly_reset_hour_utc: 15,
};

const NO_RAID: RaidPlan = { onTime: false, fullNight: false, bossKills: 0, progressAwards: 0 };

test("roundHalfUp rounds .5 up", () => {
  assert.equal(roundHalfUp(2.5), 3);
  assert.equal(roundHalfUp(2.4), 2);
  assert.equal(roundHalfUp(10), 10);
});

test("projectDecayOnly applies exactly one week of decay to EP and to GP above the floor", () => {
  const state = projectDecayOnly(100, 320, RULES);
  assert.equal(state.ep, 85); // 100 * 0.85
  assert.equal(state.gp, 287); // 100 + (320 - 100) * 0.85
  assert.ok(Math.abs(state.pr - 85 / 287) < 1e-9);
});

test("projectDecayOnly never drops GP below the floor", () => {
  const state = projectDecayOnly(50, 100, RULES);
  assert.equal(state.gp, 100);
});

test("raidEp sums on-time, full-night, boss kills and progress at the rules' EP values", () => {
  const plan: RaidPlan = { onTime: true, fullNight: true, bossKills: 3, progressAwards: 1 };
  assert.equal(raidEp(plan, RULES), 5 + 5 + 3 * 10 + 1 * 10);
  assert.equal(raidEp(NO_RAID, RULES), 0);
});

test("lootMainSpecGp prices a plain slot, a chase item, a main caster weapon and a legendary item", () => {
  const slot: LootPlan = {
    slot: "INVTYPE_HEAD",
    response: "ms",
    chase: false,
    mainCasterWeapon: false,
    legendary: false,
  };
  assert.equal(lootMainSpecGp(slot, RULES), 100);
  assert.equal(lootMainSpecGp({ ...slot, chase: true }, RULES), 150);
  assert.equal(lootMainSpecGp({ ...slot, mainCasterWeapon: true }, RULES), 200);
  assert.equal(lootMainSpecGp({ ...slot, legendary: true, chase: true }, RULES), 300); // legendary ignores chase
});

test("lootGp applies response: main spec full, off spec a rounded percent, alt/de/bank nothing", () => {
  const slot: LootPlan = {
    slot: "INVTYPE_HEAD",
    response: "ms",
    chase: false,
    mainCasterWeapon: false,
    legendary: false,
  };
  assert.equal(lootGp(slot, RULES), 100);
  assert.equal(lootGp({ ...slot, response: "os" }, RULES), 10); // round_half_up(100 * 10%)
  assert.equal(lootGp({ ...slot, response: "alt" }, RULES), 0);
  assert.equal(lootGp({ ...slot, response: "de" }, RULES), 0);
  assert.equal(lootGp({ ...slot, response: "bank" }, RULES), 0);
});

test("projectMember adds raid EP before the loot charge, and the loot charge only in postLoot", () => {
  const plan: RaidPlan = { onTime: true, fullNight: true, bossKills: 1, progressAwards: 0 }; // +20 EP
  const loot: LootPlan = {
    slot: "INVTYPE_HEAD",
    response: "ms",
    chase: false,
    mainCasterWeapon: false,
    legendary: false,
  };
  const { preLoot, postLoot } = projectMember({ ep: 100, gp: 200 }, plan, loot, RULES);
  assert.equal(preLoot.ep, 85 + 20);
  assert.equal(preLoot.gp, 185); // 100 + (200 - 100) * 0.85
  assert.equal(postLoot.ep, preLoot.ep);
  assert.equal(postLoot.gp, 285); // + 100 GP for the main-spec head item
});

test("projectMember with no loot leaves postLoot equal to preLoot", () => {
  const { preLoot, postLoot } = projectMember({ ep: 50, gp: 150 }, NO_RAID, null, RULES);
  assert.deepEqual(postLoot, preLoot);
});

test("rankAmong counts everyone projected ahead by PR, ties broken by EP", () => {
  const self = { ep: 50, gp: 100, pr: 0.5 };
  const others = [
    { ep: 100, gp: 100 }, // decays to pr 0.85, ahead
    { ep: 10, gp: 100 }, // decays to pr 0.085, behind
  ];
  assert.equal(rankAmong(self, others, RULES), 2);
  assert.equal(rankAmong(self, [], RULES), 1);
});

test("compareWinner picks the higher PR, ties going to the higher EP", () => {
  assert.equal(compareWinner({ ep: 10, gp: 100, pr: 0.5 }, { ep: 10, gp: 100, pr: 0.4 }), "a");
  assert.equal(compareWinner({ ep: 10, gp: 100, pr: 0.4 }, { ep: 10, gp: 100, pr: 0.5 }), "b");
  assert.equal(compareWinner({ ep: 20, gp: 100, pr: 0.5 }, { ep: 10, gp: 100, pr: 0.5 }), "a");
  assert.equal(compareWinner({ ep: 10, gp: 100, pr: 0.5 }, { ep: 10, gp: 100, pr: 0.5 }), "tie");
});
