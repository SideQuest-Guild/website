// An addon drawn as a WoW item tooltip, with its inventory icon beside it and its buttons beneath. Shared by the
// Armory (/addons/) and SideQuest Companion's page, which shows the addon Companion keeps up to date.
import { ADDON_ORIGIN_LABELS, escapeHtml, type Addon } from "./api";

const updatedFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });

/** One `<li>` per addon. `crestSrc` is the guild crest, used as the inventory icon of guild-made addons. */
export function addonTooltip(addon: Addon, crestSrc: string | undefined): string {
  const guild = addon.origin === "guild";
  const icon =
    guild && crestSrc
      ? `<span class="tt-icon" aria-hidden="true"><img src="${escapeHtml(crestSrc)}" alt="" loading="lazy" decoding="async" /></span>`
      : "";
  const homepage = addon.homepage_url
    ? `<a class="btn-quiet btn-small" href="${escapeHtml(addon.homepage_url)}">Homepage</a>`
    : "";
  const updated = updatedFormat.format(new Date(addon.updated_at));
  return `
    <li class="addon-item${icon ? "" : " addon-item-plain"}">
      ${icon}
      <div class="tooltip-card">
        <p class="tt-name">${escapeHtml(addon.name)}</p>
        <p class="tt-origin ${guild ? "tt-origin-guild" : "tt-origin-community"}">${escapeHtml(ADDON_ORIGIN_LABELS[addon.origin])}</p>
        <p class="tt-line"><span>Version ${escapeHtml(addon.version)}</span><span>Updated ${escapeHtml(updated)}</span></p>
        <p class="tt-flavor">“${escapeHtml(addon.summary)}”</p>
      </div>
      <div class="addon-actions">
        <a class="btn btn-small" href="${escapeHtml(addon.download_url)}">Download</a>
        ${homepage}
      </div>
    </li>`;
}
