// Reveals the homepage's RECRUITING band only when officers have marked at least one role or class as wanted.
// Any fetch failure, or nothing wanted, leaves the band hidden as the markup has it. Every card links to the Discord
// invite: joining the Discord is how anyone signs up.
import { apiFetch, escapeHtml, onFreshData, type Recruiting } from "./api";
import { DISCORD_INVITE } from "../config";
import { onPage } from "./page";

const RECRUITING_PATH = "/api/recruiting";

const ROLE_LABELS: Record<string, string> = { tank: "Tank", healer: "Healer", dps: "DPS" };
const CLASS_LABELS: Record<string, string> = {
  warrior: "Warrior",
  paladin: "Paladin",
  hunter: "Hunter",
  rogue: "Rogue",
  priest: "Priest",
  shaman: "Shaman",
  mage: "Mage",
  warlock: "Warlock",
  druid: "Druid",
};
const ROLE_ICONS: Record<string, string> = { tank: "i-tank", healer: "i-healer", dps: "i-dps" };

function card(markEl: string, label: string, priority: string, note: string | null): string {
  const high = priority === "high";
  const priorityEl = high ? `<span class="recruit-card-priority">High priority</span>` : "";
  const noteEl = note ? `<span class="recruit-card-note">${escapeHtml(note)}</span>` : "";
  return `<li><a class="recruit-card${high ? " is-high" : ""}" href="${DISCORD_INVITE}">${markEl}<span class="recruit-card-name">${escapeHtml(label)}</span>${priorityEl}${noteEl}<span class="sr-only"> — join the Discord</span></a></li>`;
}

function group(title: string, cards: string[], gridClass = ""): string {
  if (cards.length === 0) {
    return "";
  }
  return `<div class="recruit-group"><h3 class="recruit-group-title caps">${title}</h3><ul class="recruit-grid ${gridClass}" aria-label="${title} wanted">${cards.join("")}</ul></div>`;
}

onPage("#recruiting", () => {
  const band = document.getElementById("recruiting");
  const list = document.getElementById("recruiting-want-list");
  if (!band || !list) {
    return;
  }

  // Runs again when the service worker has a newer answer than the one it showed first, so it can hide as well.
  const load = (): void => {
    apiFetch<Recruiting>(RECRUITING_PATH)
      .then((recruiting) => {
        const wanted = recruiting.roles.length > 0 || recruiting.classes.length > 0;
        band.hidden = !wanted;
        if (!wanted) {
          return;
        }
        const roleCards = recruiting.roles.map((want) =>
          card(
            `<svg class="ico" aria-hidden="true"><use href="#${ROLE_ICONS[want.role]}"></use></svg>`,
            ROLE_LABELS[want.role] ?? want.role,
            want.priority,
            want.note,
          ),
        );
        const classCards = recruiting.classes.map((want) =>
          card(
            `<span class="recruit-card-dot cls-${want.class}" aria-hidden="true"></span>`,
            CLASS_LABELS[want.class] ?? want.class,
            want.priority,
            want.note,
          ),
        );
        list.innerHTML = group("Roles", roleCards) + group("Classes", classCards, "recruit-grid-classes");
      })
      .catch(() => {
        // Keep whatever is showing: no JS network error should surface on the homepage.
      });
  };
  onFreshData(RECRUITING_PATH, load);
  load();
});
