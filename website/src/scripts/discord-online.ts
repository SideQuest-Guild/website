// Fills the homepage "Online now" roster, under the hearths, with who's in the Discord right now — for signed-in
// guild members only. Pulled from Discord's own public server widget via `/api/discord/online`, never cached on the
// device (it's members-only and varies by session), and never fetched at all for a signed-out visitor, so the
// roster stays hidden and there's no layout shift.
import { apiFetch, escapeHtml, fetchMe, type DiscordOnline, type DiscordOnlineMember } from "./api";
import { onPage } from "./page";

const REFRESH_MS = 60_000;
/** More members than this: the rest fold into a "+N more" line, like the hearths' "+N" embers. */
const MAX_SHOWN = 16;

function memberMarkup(member: DiscordOnlineMember): string {
  const avatar = member.avatar_url
    ? `<img class="online-now-avatar" src="${escapeHtml(member.avatar_url)}" alt="${escapeHtml(member.name)}" width="40" height="40" loading="lazy" decoding="async" />`
    : `<span class="online-now-avatar online-now-avatar-empty" role="img" aria-label="${escapeHtml(member.name)}"></span>`;
  const activity = member.activity ? `<span class="online-now-activity">${escapeHtml(member.activity)}</span>` : "";
  return `<li class="online-now-member" data-status="${escapeHtml(member.status)}" title="${escapeHtml(member.name)}">
    <span class="online-now-ring">${avatar}</span>
    <span class="online-now-name caps">${escapeHtml(member.name)}</span>
    ${activity}
  </li>`;
}

function render(data: DiscordOnline, container: HTMLElement, list: HTMLUListElement, more: HTMLElement): void {
  if (!data.ok) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  const shown = data.members.slice(0, MAX_SHOWN);
  const overflow = data.members.length - shown.length;
  list.innerHTML = shown.map(memberMarkup).join("");
  more.hidden = overflow <= 0;
  more.textContent = overflow > 0 ? `+${overflow} more` : "";
}

onPage("[data-online-now]", (signal) => {
  const container = document.querySelector<HTMLElement>("[data-online-now]");
  const list = document.querySelector<HTMLUListElement>("[data-online-now-list]");
  const more = document.querySelector<HTMLElement>("[data-online-now-more]");
  if (!container || !list || !more) {
    return;
  }

  // Set once `/api/me` confirms a signed-in guild member; a signed-out visitor never reaches the fetch below.
  let isMember = false;

  const refresh = async (): Promise<void> => {
    if (!isMember) {
      return;
    }
    try {
      render(await apiFetch<DiscordOnline>("/api/discord/online", { signal }), container, list, more);
    } catch {
      // Keep whatever is showing: a blip shouldn't hide an already-rendered roster or surface on the homepage.
    }
  };

  fetchMe()
    .then((me) => {
      isMember = me.is_guild_member;
      void refresh();
    })
    .catch(() => {
      // Signed out (401) or offline: the roster stays hidden, same as a visitor who never signed in.
    });

  const timer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void refresh();
    }
  }, REFRESH_MS);
  signal.addEventListener("abort", () => window.clearInterval(timer));
});
