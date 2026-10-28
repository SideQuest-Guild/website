// Fills the homepage "In the Discord" band with live numbers: how many people are in each voice
// channel and how many members are online. Counts only, never names. Any fetch failure, or a bot
// that hasn't reported recently, leaves the band exactly as the markup has it.
import { apiFetch, type DiscordLive } from "./api";

const REFRESH_MS = 60_000;

const online = document.querySelector<HTMLElement>("[data-discord-online]");
const voiceItems = new Map(
  Array.from(document.querySelectorAll<HTMLElement>("[data-voice]"), (item) => [item.dataset.voice ?? "", item]),
);

function render(live: DiscordLive): void {
  if (online) {
    online.hidden = live.online === null;
    online.textContent = live.online === null ? "" : `${live.online.toLocaleString()} online`;
  }
  const counts = new Map(live.voice.map((channel) => [channel.name.toLowerCase(), channel.count]));
  for (const [name, item] of voiceItems) {
    const count = counts.get(name) ?? 0;
    const badge = item.querySelector<HTMLElement>(".voice-count");
    if (!badge) {
      continue;
    }
    item.classList.toggle("live", count > 0);
    badge.hidden = count === 0;
    badge.textContent = count > 0 ? String(count) : "";
    badge.setAttribute("aria-label", count === 1 ? "1 person in voice" : `${count} people in voice`);
  }
}

async function refresh(): Promise<void> {
  try {
    render(await apiFetch<DiscordLive>("/api/discord/live"));
  } catch {
    // Keep whatever is showing: no network error should surface on the homepage.
  }
}

if (online || voiceItems.size > 0) {
  void refresh();
  window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void refresh();
    }
  }, REFRESH_MS);
}
