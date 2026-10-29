// Reveals the homepage's RAIDS band, hero-nav link and footer link only once a raid is actually
// scheduled. Any fetch failure, or no scheduled raids, leaves all three hidden as the markup has them.
import { apiFetch, escapeHtml, onFreshData, type EventSummary } from "./api";
import { seriesRefText } from "./series";

const RAIDS_PATH = "/api/events?when=upcoming&kind=raid";

const heroLink = document.getElementById("hero-raid-nav");
const footerLink = document.getElementById("footer-raid-nav");
const band = document.getElementById("raids");
const nextDate = document.getElementById("raid-next-date");

if (heroLink && footerLink && band && nextDate) {
  const dateFormat = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  const dateOnlyFormat = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  // Runs again when the service worker has a newer answer than the one it showed first, so it can hide as well.
  const load = (): void => {
    apiFetch<EventSummary[]>(RAIDS_PATH)
      .then((raids) => {
        const next = raids[0];
        heroLink.hidden = !next;
        footerLink.hidden = !next;
        band.hidden = !next;
        if (!next) {
          return;
        }
        nextDate.classList.remove("tbd");
        if (next.series) {
          const ruleText = seriesRefText(next.series, next.starts_at);
          const dateText = dateOnlyFormat.format(new Date(next.starts_at));
          nextDate.innerHTML = `${escapeHtml(ruleText)} — next: <a href="/events/detail/?id=${escapeHtml(next.id)}">${escapeHtml(dateText)}</a>`;
        } else {
          const when = dateFormat.format(new Date(next.starts_at));
          nextDate.innerHTML = `<a href="/events/detail/?id=${escapeHtml(next.id)}">${escapeHtml(when)}</a>`;
        }
      })
      .catch(() => {
        // Keep whatever is showing: no JS network error should surface on the homepage.
      });
  };
  onFreshData(RAIDS_PATH, load);
  load();
}
