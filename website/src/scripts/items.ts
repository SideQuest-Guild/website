// Shared helpers for showing a WoW item anywhere on the site: an escaped link styled by quality that also wires up
// a Wowhead tooltip (see privacy#who-else: the tooltip script is a third party). Imported by any page that shows an
// item with an `item_id` — /ledger/, /guild/, /items/ and /items/detail/.
import { escapeHtml } from "./api";

declare global {
  interface Window {
    whTooltips?: { colorLinks: boolean; iconizeLinks: boolean; renameLinks: boolean };
    $WowheadPower?: { refreshLinks: () => void };
  }
}

/**
 * An escaped `<a>` to an item's detail page that Wowhead's script turns into a hover tooltip. `qualityClass` colors
 * the text (`qualityClass` from `scripts/api.ts`); omit it where the caller's data has no quality (guild bank,
 * market and crafter rows).
 */
export function itemLink(itemId: number, name: string, qualityClass?: string): string {
  const cls = qualityClass ? ` q-${qualityClass}` : "";
  return `<a class="item-link${cls}" href="/items/detail/?id=${itemId}" data-wowhead="item=${itemId}&domain=forever">${escapeHtml(name)}</a>`;
}

let wowheadLoad: Promise<void> | null = null;

const WOWHEAD_ORIGIN = "https://wow.zamimg.com/";

/**
 * Loads Wowhead's tooltip script once per visit (cached across page swaps, since the module stays loaded), setting
 * `window.whTooltips` first as its docs require. Call from a page that shows `itemLink`s before relying on hovers
 * to work; `refreshWowheadLinks` picks up links rendered after the script loads.
 */
export function loadWowheadTooltips(): Promise<void> {
  if (!wowheadLoad) {
    const { promise, resolve } = Promise.withResolvers<void>();
    window.whTooltips = { colorLinks: false, iconizeLinks: true, renameLinks: false };
    const script = document.createElement("script");
    script.src = `${WOWHEAD_ORIGIN}js/tooltips.js`;
    script.async = true;
    script.addEventListener("load", () => resolve(), { once: true });
    script.addEventListener("error", () => resolve(), { once: true });
    document.head.append(script);
    // The script runs once, but its stylesheet lives in <head>, which ClientRouter swaps for the next page's on every
    // navigation. Copying it into the incoming head makes Astro keep the live node; without it, tooltips shown after
    // a page swap come up unstyled.
    document.addEventListener("astro:before-swap", (event) => {
      for (const link of document.head.querySelectorAll(`link[rel=stylesheet][href^="${WOWHEAD_ORIGIN}"]`)) {
        event.newDocument.head.append(link.cloneNode());
      }
    });
    wowheadLoad = promise;
  }
  return wowheadLoad;
}

/** Re-scans the page for `data-wowhead` links Wowhead's script hasn't seen yet, after rendering new ones. */
export function refreshWowheadLinks(): void {
  window.$WowheadPower?.refreshLinks();
}
