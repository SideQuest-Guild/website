// Reveals the homepage's RAIDS band, hero-nav link and footer link only once a raid is actually
// scheduled. Any fetch failure, or no scheduled raids, leaves all three hidden as the markup has them.
import { apiFetch, escapeHtml, type EventSummary } from "./api";
import { seriesRefText } from "./series";

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

  apiFetch<EventSummary[]>("/api/events?when=upcoming&kind=raid")
    .then((raids) => {
      const next = raids[0];
      if (!next) {
        return;
      }
      heroLink.hidden = false;
      footerLink.hidden = false;
      band.hidden = false;
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
      // Stay hidden: no JS network error should surface on the homepage.
    });
}
