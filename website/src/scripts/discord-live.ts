// Fills the homepage "In the Discord" label with how many members are online. A count only, never
// names. Any fetch failure, or a bot that hasn't reported recently, leaves the label as the markup has it.
import { apiFetch, type DiscordLive } from "./api";

const REFRESH_MS = 60_000;

const online = document.querySelector<HTMLElement>("[data-discord-online]");

async function refresh(target: HTMLElement): Promise<void> {
  try {
    const live = await apiFetch<DiscordLive>("/api/discord/live");
    target.hidden = live.online === null;
    target.textContent = live.online === null ? "" : `${live.online.toLocaleString()} online`;
  } catch {
    // Keep whatever is showing: no network error should surface on the homepage.
  }
}

if (online) {
  void refresh(online);
  window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void refresh(online);
    }
  }, REFRESH_MS);
}
