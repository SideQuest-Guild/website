// Fills the homepage "In the Discord" line with live numbers: how many members are online, and a lit hearth for
// each voice channel someone is sitting in, with one ember per person. Counts only, never names. Any fetch
// failure, or a bot that hasn't reported recently, leaves the band as it is.
import { apiFetch, onFreshData, type DiscordLive, type VoiceChannelCount } from "./api";

const REFRESH_MS = 60_000;
/** More people than this in one channel: the rest are a "+N" after the embers. */
const MAX_EMBERS = 8;
/** Matches the longest exit transition in site.css (.hearth / .ember leaving). */
const EXIT_MS = 700;

const online = document.querySelector<HTMLElement>("[data-discord-online]");
const hearths = document.querySelector<HTMLUListElement>("[data-hearths]");

const FLAME_SVG = `<svg class="hearth-fire" viewBox="0 0 32 44" aria-hidden="true" focusable="false">
  <path class="flame-outer" d="M16 2c1.6 6.4 9 9.8 9 19.2C25 29 21.2 34 16 34S7 29 7 21.6c0-5.4 3.4-8 4.6-12.4 1.2 3 2.4 4.4 3.6 5.4.2-4.8-.6-8.4.8-12.6Z"/>
  <path class="flame-inner" d="M16 15.5c1 4.2 5 6 5 10.6 0 4.4-2.2 7.4-5 7.4s-5-3-5-6.6c0-3 1.8-4.4 2.8-7 .6 1.6 1.2 2.4 2 3 .2-2.6-.4-5 .2-7.4Z"/>
  <path class="brazier" d="M5 34.5h22l-3.6 4.5H8.6L5 34.5Zm6.5 4.5h9l1.5 4h-12l1.5-4Z"/>
</svg>`;

/** Drops `element` after its exit transition; the timeout covers browsers that skip `transitionend`. */
function leave(element: HTMLElement): void {
  if (element.classList.contains("out")) {
    return;
  }
  element.classList.add("out");
  window.setTimeout(() => element.remove(), EXIT_MS);
}

function syncEmbers(hearth: HTMLElement, count: number): void {
  const embers = hearth.querySelector<HTMLElement>(".hearth-embers");
  const more = hearth.querySelector<HTMLElement>(".hearth-more");
  const label = hearth.querySelector<HTMLElement>(".sr-only");
  if (!embers || !more || !label) {
    return;
  }
  const lit = Array.from(embers.querySelectorAll<HTMLElement>(".ember:not(.out)"));
  const wanted = Math.min(count, MAX_EMBERS);
  for (let index = lit.length; index < wanted; index++) {
    const ember = document.createElement("i");
    ember.className = "ember";
    ember.style.setProperty("--i", String(index));
    embers.append(ember);
  }
  for (const ember of lit.slice(wanted).toReversed()) {
    leave(ember);
  }
  more.hidden = count <= MAX_EMBERS;
  more.textContent = count > MAX_EMBERS ? `+${count - MAX_EMBERS}` : "";
  label.textContent = count === 1 ? "1 person in voice" : `${count} people in voice`;
}

function newHearth(channel: VoiceChannelCount, order: number): HTMLLIElement {
  const hearth = document.createElement("li");
  hearth.className = "hearth";
  hearth.dataset.channel = channel.name;
  // Each hearth flickers on its own clock so a row of them never pulses in step.
  hearth.style.setProperty("--flicker-delay", `${-(order * 0.73) % 2.3}s`);
  hearth.innerHTML = `${FLAME_SVG}<span class="hearth-name"></span><span class="hearth-people"><span class="hearth-embers" aria-hidden="true"></span><span class="hearth-more" aria-hidden="true" hidden></span><span class="sr-only"></span></span>`;
  const name = hearth.querySelector<HTMLElement>(".hearth-name");
  if (name) {
    name.textContent = channel.name;
  }
  return hearth;
}

function renderHearths(list: HTMLUListElement, voice: VoiceChannelCount[]): void {
  const busy = voice.filter((channel) => channel.count > 0).toSorted((a, b) => b.count - a.count);
  const existing = new Map(
    Array.from(list.querySelectorAll<HTMLLIElement>(".hearth:not(.out)"), (hearth) => [hearth.dataset.channel, hearth]),
  );
  busy.forEach((channel, order) => {
    const hearth = existing.get(channel.name) ?? newHearth(channel, order);
    existing.delete(channel.name);
    // Busiest first; appending an element already in the list moves it there.
    list.append(hearth);
    syncEmbers(hearth, channel.count);
  });
  for (const hearth of existing.values()) {
    leave(hearth);
  }
  if (busy.length > 0) {
    list.hidden = false;
  } else {
    window.setTimeout(() => {
      list.hidden = list.querySelector(".hearth:not(.out)") === null;
    }, EXIT_MS);
  }
}

function render(live: DiscordLive): void {
  if (online) {
    online.hidden = live.online === null;
    online.textContent = live.online === null ? "" : `${live.online.toLocaleString()} online`;
  }
  if (hearths) {
    renderHearths(hearths, live.voice);
  }
}

async function refresh(): Promise<void> {
  try {
    render(await apiFetch<DiscordLive>("/api/discord/live"));
  } catch {
    // Keep whatever is showing: no network error should surface on the homepage.
  }
}

if (hearths) {
  // Flames only burn while the band is on screen; off screen their animations pause.
  new IntersectionObserver(([entry]) => {
    hearths.classList.toggle("is-idle", !entry?.isIntersecting);
  }).observe(hearths);
}

if (online || hearths) {
  onFreshData("/api/discord/live", () => void refresh());
  void refresh();
  window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void refresh();
    }
  }, REFRESH_MS);
}
