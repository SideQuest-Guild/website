// Shared helpers for linking to a quest or achievement's reference page anywhere on the site: an escaped link that
// also wires up a Wowhead hover tooltip, same idea as `itemLink` in `scripts/items.ts` (see privacy#who-else: the
// tooltip script is a third party). Reused by /quests/, /achievements/ and the character page's recent
// achievements list; pair with `loadWowheadTooltips`/`refreshWowheadLinks` from `scripts/items.ts`.
import { escapeHtml } from "./api";

/** An escaped `<a>` to a quest's detail page that Wowhead's script turns into a hover tooltip. */
export function questLink(questId: number, title: string): string {
  return `<a class="ref-link" href="/quests/detail/?id=${questId}" data-wowhead="quest=${questId}&domain=forever">${escapeHtml(title)}</a>`;
}

/** An escaped `<a>` to an achievement's detail page that Wowhead's script turns into a hover tooltip. */
export function achievementLink(achievementId: number, name: string): string {
  return `<a class="ref-link" href="/achievements/detail/?id=${achievementId}" data-wowhead="achievement=${achievementId}&domain=forever">${escapeHtml(name)}</a>`;
}
