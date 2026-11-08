// A pure, DOM-free EPGP projection calculator for the Ledger's "next raid" planner. Framework-free on purpose so
// it's unit-testable with `node --test` (see epgp-calculator.test.ts) without a browser. Mirrors the server's
// read-time decay exactly (api/src/sidequest_api/domain/epgp/services.py's `decayed_amount`/`resets_since`): every
// ledger entry is `amount * (1 - DECAY_PERCENT/100) ** resets`, and because that's a per-entry multiplication, the
// *sum* of all of one member's entries picks up exactly one more factor of `(1 - DECAY_PERCENT/100)` at the very
// next weekly reset — so projecting a member's current (already decayed-on-read) EP/GP totals forward through that
// one reset is exact, not an approximation, as long as no second reset is crossed. GP's floor (`MIN_GP`) is applied
// after decaying the part of GP above `BASE_GP`, matching `max(MIN_GP, BASE_GP + decayed_gp_entries)` server-side.
import type { EpgpRules } from "./api";

export type EpgpState = { ep: number; gp: number; pr: number };

function prOf(ep: number, gp: number): number {
  return gp > 0 ? ep / gp : 0;
}

/** Half-up rounding for GP charges (`OS_PERCENT` pay, per the rules' doc comment: "rounded half up"). GP amounts
 * here are never negative, so plain `Math.floor(value + 0.5)` is exact. */
export function roundHalfUp(value: number): number {
  return Math.floor(value + 0.5);
}

/** A member's current EP/GP (as served by `GET /api/epgp/standings`, already decayed as of now), projected forward
 * through exactly the next weekly reset, with no raid activity. */
export function projectDecayOnly(ep: number, gp: number, rules: EpgpRules): EpgpState {
  const factor = 1 - rules.decay_percent / 100;
  const nextEp = ep * factor;
  const aboveBase = gp - rules.base_gp;
  const nextGp = Math.max(rules.min_gp, rules.base_gp + aboveBase * factor);
  return { ep: nextEp, gp: nextGp, pr: prOf(nextEp, nextGp) };
}

export type RaidPlan = {
  onTime: boolean;
  fullNight: boolean;
  bossKills: number;
  progressAwards: number;
};

/** EP a raid plan would earn, using the rules' `ep` table. `standby` earns the same as attending, so it isn't a
 * separate input: ticking `onTime`/`fullNight` covers it either way. */
export function raidEp(plan: RaidPlan, rules: EpgpRules): number {
  return (
    (plan.onTime ? rules.ep.on_time : 0) +
    (plan.fullNight ? rules.ep.full_night : 0) +
    Math.max(0, plan.bossKills) * rules.ep.boss_kill +
    Math.max(0, plan.progressAwards) * rules.ep.progress
  );
}

export type LootResponse = "ms" | "os" | "alt" | "de" | "bank";

export type LootPlan = {
  /** `INVTYPE_*` key from `rules.gp`; ignored when `legendary` is set, overridden to the 2H weapon cost when
   * `mainCasterWeapon` is set. A tier token prices at the slot it represents, so pick that slot here. */
  slot: string;
  response: LootResponse;
  /** Slot cost (or the 2H override) times `rules.chase_multiplier`; no effect when `legendary` is set. */
  chase: boolean;
  /** A 1H weapon priced as the 2H slot, by officer toggle. */
  mainCasterWeapon: boolean;
  /** Legendary, special or rare: flat `rules.legendary_gp`, ignoring slot/chase/mainCasterWeapon. */
  legendary: boolean;
};

const TWO_HANDED_SLOT = "INVTYPE_2HWEAPON";

/** The main-spec GP an item would cost, before `response` is applied. */
export function lootMainSpecGp(loot: LootPlan, rules: EpgpRules): number {
  if (loot.legendary) {
    return rules.legendary_gp;
  }
  const slotKey = loot.mainCasterWeapon ? TWO_HANDED_SLOT : loot.slot;
  const base = rules.gp[slotKey] ?? 0;
  return loot.chase ? base * rules.chase_multiplier : base;
}

/** The GP an item actually charges once `response` (main/off spec, alt fill, disenchant/bank) is applied. */
export function lootGp(loot: LootPlan, rules: EpgpRules): number {
  const mainSpec = lootMainSpecGp(loot, rules);
  switch (loot.response) {
    case "ms":
      return mainSpec;
    case "os":
      return roundHalfUp((mainSpec * rules.os_percent) / 100);
    case "alt":
    case "de":
    case "bank":
      return 0;
  }
}

/** A member's next-raid projection: `preLoot` is their EP/GP/PR right after the reset and the raid's EP, the state
 * that decides priority for a contested drop; `postLoot` adds the optional item's GP charge, previewing the result
 * if they're the one who receives it. */
export type ProjectedMember = { preLoot: EpgpState; postLoot: EpgpState };

export function projectMember(
  current: { ep: number; gp: number },
  plan: RaidPlan,
  loot: LootPlan | null,
  rules: EpgpRules,
): ProjectedMember {
  const decayed = projectDecayOnly(current.ep, current.gp, rules);
  const preLootEp = decayed.ep + raidEp(plan, rules);
  const preLootGp = decayed.gp;
  const preLoot: EpgpState = { ep: preLootEp, gp: preLootGp, pr: prOf(preLootEp, preLootGp) };
  const addedGp = loot ? lootGp(loot, rules) : 0;
  const postLootGp = Math.max(rules.min_gp, preLootGp + addedGp);
  const postLoot: EpgpState = { ep: preLootEp, gp: postLootGp, pr: prOf(preLootEp, postLootGp) };
  return { preLoot, postLoot };
}

/** 1-based rank of `state` among `others`' current EP/GP projected through the same reset with no raid (the
 * standings' own tie-break: higher PR first, ties to higher EP). */
export function rankAmong(state: EpgpState, others: { ep: number; gp: number }[], rules: EpgpRules): number {
  let ahead = 0;
  for (const other of others) {
    const projected = projectDecayOnly(other.ep, other.gp, rules);
    if (projected.pr > state.pr || (projected.pr === state.pr && projected.ep > state.ep)) {
      ahead++;
    }
  }
  return ahead + 1;
}

/** Who wins a contested main-spec drop between two projections: higher PR, ties to higher EP, otherwise a tie. */
export function compareWinner(a: EpgpState, b: EpgpState): "a" | "b" | "tie" {
  if (a.pr !== b.pr) {
    return a.pr > b.pr ? "a" : "b";
  }
  if (a.ep !== b.ep) {
    return a.ep > b.ep ? "a" : "b";
  }
  return "tie";
}
