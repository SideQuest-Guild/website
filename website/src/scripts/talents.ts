// Pure helpers for the talent calculator (`/talents/`): encoding/decoding a build's talent code, and checking
// whether a set of ranks is legal against a tree's rules (max rank, prerequisites, row gating). These mirror the
// API's own validation (`sidequest_api.domain.talents.services.validate_build_code`) so the page can give instant
// feedback; the API re-validates on save regardless, so drift here is a UX bug, never a correctness one.
import { MAX_TALENT_POINTS, type TalentNode, type TalentTree } from "./api";

const ROW_POINTS = 5;

/** Points spent on every node in `tree`, before `node`'s row (its own row and later rows don't count). */
function spentBeforeRow(tree: TalentTree, ranks: number[], row: number): number {
  let total = 0;
  for (const [index, node] of tree.nodes.entries()) {
    if (node.row < row) {
      total += ranks[index] ?? 0;
    }
  }
  return total;
}

/** Whether `ranks` (one entry per `tree.nodes`, same order) obeys every rule for that tree, on its own. */
export function treeRanksAreValid(tree: TalentTree, ranks: number[]): boolean {
  const byId = new Map(tree.nodes.map((node, index) => [node.id, ranks[index] ?? 0]));
  for (const [index, node] of tree.nodes.entries()) {
    const rank = ranks[index] ?? 0;
    if (rank < 0 || rank > node.max_rank) {
      return false;
    }
    if (rank === 0) {
      continue;
    }
    if (spentBeforeRow(tree, ranks, node.row) < ROW_POINTS * (node.row - 1)) {
      return false;
    }
    if (node.requires !== null) {
      const prereq = tree.nodes.find((candidate) => candidate.id === node.requires);
      if (!prereq || (byId.get(node.requires) ?? 0) < prereq.max_rank) {
        return false;
      }
    }
  }
  return true;
}

/** Total points spent across every tree's ranks. */
export function totalSpent(ranksByTree: number[][]): number {
  return ranksByTree.reduce((sum, ranks) => sum + ranks.reduce((a, b) => a + b, 0), 0);
}

/** Whether raising `nodeIndex` in `tree` by one point is currently legal. */
export function canAddPoint(
  trees: TalentTree[],
  ranksByTree: number[][],
  treeIndex: number,
  nodeIndex: number,
): boolean {
  if (totalSpent(ranksByTree) >= MAX_TALENT_POINTS) {
    return false;
  }
  const tree = trees[treeIndex];
  const ranks = ranksByTree[treeIndex];
  if (!tree || !ranks) {
    return false;
  }
  const next = ranks.slice();
  next[nodeIndex] = (next[nodeIndex] ?? 0) + 1;
  return treeRanksAreValid(tree, next);
}

/** Whether lowering `nodeIndex` in `tree` by one point is currently legal (won't orphan a dependent spend). */
export function canRemovePoint(
  trees: TalentTree[],
  ranksByTree: number[][],
  treeIndex: number,
  nodeIndex: number,
): boolean {
  const tree = trees[treeIndex];
  const ranks = ranksByTree[treeIndex];
  if (!tree || !ranks || (ranks[nodeIndex] ?? 0) <= 0) {
    return false;
  }
  const next = ranks.slice();
  next[nodeIndex] -= 1;
  return treeRanksAreValid(tree, next);
}

/** Builds the share/save code: one digit per node (row, col order, already the tree's node order), trees joined
 * by `-`, each tree's trailing zeros trimmed. */
export function encodeCode(ranksByTree: number[][]): string {
  return ranksByTree
    .map((ranks) => {
      const digits = ranks.map((rank) => String(Math.max(0, Math.min(9, rank))));
      while (digits.length > 0 && digits.at(-1) === "0") {
        digits.pop();
      }
      return digits.join("");
    })
    .join("-");
}

/** Decodes a talent code into one ranks array per tree, padded/truncated to each tree's node count. Malformed or
 * out-of-range digits are dropped to 0 rather than thrown, so a bad share link still opens the calculator. */
export function decodeCode(code: string, trees: TalentTree[]): number[][] {
  const segments = code.split("-");
  return trees.map((tree, treeIndex) => {
    const segment = segments[treeIndex] ?? "";
    return tree.nodes.map((node, nodeIndex) => {
      const digit = Number(segment[nodeIndex]);
      return Number.isInteger(digit) && digit >= 0 && digit <= node.max_rank ? digit : 0;
    });
  });
}

/** An empty ranks array (every node at 0) for each of `trees`. */
export function emptyRanks(trees: TalentTree[]): number[][] {
  return trees.map((tree) => tree.nodes.map(() => 0));
}

/** Whether the node is gated shut right now (not enough points spent in earlier rows of its tree). */
export function rowIsOpen(tree: TalentTree, ranks: number[], node: TalentNode): boolean {
  return spentBeforeRow(tree, ranks, node.row) >= ROW_POINTS * (node.row - 1);
}
