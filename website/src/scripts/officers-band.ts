// Shows who to whisper for an invite on the homepage's join section: the current guild officers, name and rank,
// class-colored. Public (no sign-in required). Hidden while the list is empty or the fetch fails: nothing should
// surface a network error here, and the markup starts hidden so there's no layout shift either way.
import { apiFetch, escapeHtml, normalizeClass, onFreshData, type GuildOfficer, type GuildOfficers } from "./api";
import { onPage } from "./page";

const OFFICERS_PATH = "/api/guild/officers";

function officerMarkup(officer: GuildOfficer): string {
  const normalized = normalizeClass(officer.class);
  const nameClass = normalized ? ` class="cls-${normalized}"` : "";
  return `<li class="officers-invite-item"><span${nameClass}>${escapeHtml(officer.character)}</span><span class="officers-invite-rank">${escapeHtml(officer.rank)}</span></li>`;
}

onPage("#join", (signal) => {
  const section = document.querySelector<HTMLElement>("[data-officers-invite]");
  const list = document.querySelector<HTMLUListElement>("[data-officers-invite-list]");
  if (!section || !list) {
    return;
  }

  const load = (): void => {
    apiFetch<GuildOfficers>(OFFICERS_PATH, { signal })
      .then((data) => {
        section.hidden = data.officers.length === 0;
        if (data.officers.length === 0) {
          return;
        }
        list.innerHTML = data.officers.map(officerMarkup).join("");
      })
      .catch(() => {
        // Keep whatever is showing (hidden by default): a blip shouldn't surface on the homepage.
      });
  };
  onFreshData(OFFICERS_PATH, load);
  load();
});
