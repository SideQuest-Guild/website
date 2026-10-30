// Reveals the homepage's RECRUITING band only when officers have marked at least one role or class as wanted.
// Any fetch failure, or nothing wanted, leaves the band hidden as the markup has it.
import { apiFetch, escapeHtml, onFreshData, type Recruiting } from "./api";
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

function chip(markEl: string, label: string, priority: string, note: string | null): string {
  const priorityEl = priority === "high" ? `<span class="recruit-chip-priority">High priority</span>` : "";
  const noteEl = note ? `<span class="recruit-chip-note">· ${escapeHtml(note)}</span>` : "";
  return `<li class="recruit-chip">${markEl}<span>${escapeHtml(label)}</span>${priorityEl}${noteEl}</li>`;
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
        const roleChips = recruiting.roles.map((want) =>
          chip(
            `<svg class="ico" aria-hidden="true"><use href="#${ROLE_ICONS[want.role]}"></use></svg>`,
            ROLE_LABELS[want.role] ?? want.role,
            want.priority,
            want.note,
          ),
        );
        const classChips = recruiting.classes.map((want) =>
          chip(
            `<span class="recruit-chip-dot cls-${want.class}" aria-hidden="true"></span>`,
            CLASS_LABELS[want.class] ?? want.class,
            want.priority,
            want.note,
          ),
        );
        list.innerHTML = [...roleChips, ...classChips].join("");
      })
      .catch(() => {
        // Keep whatever is showing: no JS network error should surface on the homepage.
      });
  };
  onFreshData(RECRUITING_PATH, load);
  load();
});
