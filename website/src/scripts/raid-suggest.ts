// A pure, DOM-free raid chart heuristic: given who's signed for a raid, suggests a group/bench slot for each of
// them. Framework-free on purpose so it's unit-testable with `node --test` (see raid-suggest.test.ts) without a
// browser. The event detail page (src/pages/events/detail/index.astro) renders the result as a preview an officer
// can Apply (PATCH each changed signup) or Discard.
import type { CharClass, Role } from "./api";

export const GROUP_SIZE = 5;
export const MAX_GROUPS = 8;

/** The only fields the heuristic needs off a `Signup`. */
export type SuggestSignup = {
  id: string;
  class: CharClass | null;
  role: Role | null;
};

export type SuggestedAssignment = {
  signupId: string;
  group: number | null;
  bench: boolean;
};

/** Paladin auras and Shaman totems anchor a group's buffs under Classic/Forever rules; one per group covers it. */
const BUFF_ANCHOR_CLASS: Partial<Record<CharClass, true>> = { paladin: true, shaman: true };
/** Priest buffs (Fortitude, Shield) don't stack from a second priest, so spreading them covers more groups. */
const SPREAD_CLASS: Partial<Record<CharClass, true>> = { priest: true };
/** A Hunter's pet and Aspects pair best with a totem or Mark of the Wild already in the same group. */
const HUNTER_PARTNER_CLASS: Partial<Record<CharClass, true>> = { shaman: true, druid: true };

/** How many 5-player groups an event of this size can field; `null` (no size cap) uses all 8. */
export function groupCountForSize(size: number | null): number {
  if (size === null) {
    return MAX_GROUPS;
  }
  return Math.max(1, Math.min(MAX_GROUPS, Math.ceil(size / GROUP_SIZE)));
}

/**
 * Suggests a group (or the bench) for every signed player: tanks and healers spread one per group before anyone
 * doubles up, buff-anchor and spread classes do the same for their own buffs, Hunters join a group that already
 * has a totem or Mark source when one has room, everyone else fills groups out evenly, and anyone past the event's
 * capacity goes to the bench. Returns a slot for every player passed in, not just the ones that changed; diff
 * against the current chart with `diffAssignments` before applying.
 */
export function suggestGroups(signed: SuggestSignup[], size: number | null): SuggestedAssignment[] {
  const groupCount = groupCountForSize(size);
  const groups: SuggestSignup[][] = Array.from({ length: groupCount }, () => []);
  const bench: SuggestSignup[] = [];

  function leastFilledGroup(): number {
    let best = -1;
    for (let i = 0; i < groups.length; i++) {
      if (groups[i].length >= GROUP_SIZE) {
        continue;
      }
      if (best === -1 || groups[i].length < groups[best].length) {
        best = i;
      }
    }
    return best;
  }

  function place(players: SuggestSignup[], pick: (player: SuggestSignup) => number): void {
    for (const player of players) {
      const idx = pick(player);
      if (idx === -1) {
        bench.push(player);
      } else {
        groups[idx].push(player);
      }
    }
  }

  const tanks = signed.filter((s) => s.role === "tank");
  const healers = signed.filter((s) => s.role === "healer");
  const rest = signed.filter((s) => s.role !== "tank" && s.role !== "healer");
  const anchors = rest.filter((s) => s.class !== null && BUFF_ANCHOR_CLASS[s.class]);
  const spreadOut = rest.filter((s) => s.class !== null && SPREAD_CLASS[s.class]);
  const hunters = rest.filter((s) => s.class === "hunter");
  const placedSoFar = new Set([...anchors, ...spreadOut, ...hunters]);
  const others = rest.filter((s) => !placedSoFar.has(s));

  place(tanks, leastFilledGroup);
  place(healers, leastFilledGroup);
  place(anchors, leastFilledGroup);
  place(spreadOut, leastFilledGroup);
  place(hunters, () => {
    let candidate = -1;
    for (let i = 0; i < groups.length; i++) {
      if (groups[i].length >= GROUP_SIZE) {
        continue;
      }
      const hasPartner = groups[i].some((m) => m.class !== null && HUNTER_PARTNER_CLASS[m.class]);
      const hasHunter = groups[i].some((m) => m.class === "hunter");
      if (hasPartner && !hasHunter && (candidate === -1 || groups[i].length < groups[candidate].length)) {
        candidate = i;
      }
    }
    return candidate === -1 ? leastFilledGroup() : candidate;
  });
  place(others, leastFilledGroup);

  const assignments: SuggestedAssignment[] = [];
  groups.forEach((members, i) => {
    for (const member of members) {
      assignments.push({ signupId: member.id, group: i + 1, bench: false });
    }
  });
  for (const member of bench) {
    assignments.push({ signupId: member.id, group: null, bench: true });
  }
  return assignments;
}

/** Only the assignments that would actually change a signup's group or bench flag, so Apply sends the fewest PATCHes. */
export function diffAssignments(
  current: ReadonlyMap<string, { group: number | null; bench: boolean }>,
  suggested: SuggestedAssignment[],
): SuggestedAssignment[] {
  return suggested.filter((a) => {
    const existing = current.get(a.signupId);
    return !existing || existing.group !== a.group || existing.bench !== a.bench;
  });
}
