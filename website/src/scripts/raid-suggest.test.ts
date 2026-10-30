// Run with `node --test src/scripts/*.test.ts` (see package.json's "test:unit"). Pure module, no browser needed.
import assert from "node:assert/strict";
import { test } from "node:test";

import { diffAssignments, groupCountForSize, suggestGroups, type SuggestSignup } from "./raid-suggest.ts";

function player(id: string, role: SuggestSignup["role"], cls: SuggestSignup["class"]): SuggestSignup {
  return { id, role, class: cls };
}

test("groupCountForSize caps at 8 and floors at 1, rounding up by 5s", () => {
  assert.equal(groupCountForSize(null), 8);
  assert.equal(groupCountForSize(40), 8);
  assert.equal(groupCountForSize(10), 2);
  assert.equal(groupCountForSize(11), 3);
  assert.equal(groupCountForSize(1), 1);
});

test("spreads tanks one per group before doubling up", () => {
  const signed = Array.from({ length: 3 }, (_, i) => player(`t${i}`, "tank", "warrior"));
  const groups = new Set(suggestGroups(signed, null).map((a) => a.group));
  assert.equal(groups.size, 3);
});

test("spreads healers one per group before doubling up", () => {
  const signed = Array.from({ length: 4 }, (_, i) => player(`h${i}`, "healer", "priest"));
  const groups = new Set(suggestGroups(signed, null).map((a) => a.group));
  assert.equal(groups.size, 4);
});

test("spreads priests across groups rather than stacking them", () => {
  const signed = Array.from({ length: 5 }, (_, i) => player(`p${i}`, "dps", "priest"));
  const groups = suggestGroups(signed, null).map((a) => a.group);
  assert.equal(new Set(groups).size, 5);
});

test("places a hunter with a shaman or druid already in the group when room allows", () => {
  const signed = [
    player("shaman-1", "dps", "shaman"),
    player("hunter-1", "dps", "hunter"),
    ...Array.from({ length: 3 }, (_, i) => player(`filler${i}`, "dps", "warrior")),
  ];
  const assignments = suggestGroups(signed, null);
  const byId = new Map(assignments.map((a) => [a.signupId, a]));
  assert.equal(byId.get("hunter-1")?.group, byId.get("shaman-1")?.group);
});

test("overflow past the event's capacity goes to the bench", () => {
  // size 10 -> 2 groups -> 10 seats; 13 signed means 3 on the bench.
  const signed = Array.from({ length: 13 }, (_, i) => player(`d${i}`, "dps", "warrior"));
  const assignments = suggestGroups(signed, 10);
  const benched = assignments.filter((a) => a.bench);
  assert.equal(benched.length, 3);
  assert.equal(assignments.length, 13);
  for (const a of assignments) {
    if (!a.bench) {
      assert.ok(a.group !== null && a.group >= 1 && a.group <= 2);
    }
  }
});

test("every signed player gets exactly one suggested slot", () => {
  const signed = [
    ...Array.from({ length: 8 }, (_, i) => player(`tank${i}`, "tank", "warrior")),
    ...Array.from({ length: 8 }, (_, i) => player(`heal${i}`, "healer", "priest")),
    ...Array.from({ length: 24 }, (_, i) => player(`dps${i}`, "dps", "mage")),
  ];
  const assignments = suggestGroups(signed, null);
  assert.equal(assignments.length, signed.length);
  assert.equal(new Set(assignments.map((a) => a.signupId)).size, signed.length);
  for (let group = 1; group <= 8; group++) {
    assert.equal(assignments.filter((a) => a.group === group).length, 5);
  }
});

test("diffAssignments only returns signups whose group or bench changed", () => {
  const suggested = [
    { signupId: "a", group: 1, bench: false },
    { signupId: "b", group: 2, bench: false },
    { signupId: "c", group: null, bench: true },
  ];
  const current = new Map([
    ["a", { group: 1, bench: false }],
    ["b", { group: 1, bench: false }],
    // "c" has no current entry: treated as changed.
  ]);
  const diff = diffAssignments(current, suggested);
  assert.deepEqual(
    diff.map((a) => a.signupId),
    ["b", "c"],
  );
});
