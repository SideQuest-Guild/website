// Shared client-side helpers for the SideQuest member hub pages: typed fetch wrapper, API
// response shapes (mirrors packages/sidequest-common schemas), and small DOM/string utilities.
// Imported by the <script> tags on /events/, /events/detail/, /addons/, /account/ and /officers/.

export type Me = {
  id: number;
  discord_id: string;
  username: string;
  display_name: string;
  avatar_url: string | null;
  is_guild_member: boolean;
  is_officer: boolean;
  battletag: string | null;
  roster_confirmed: boolean;
};

/** Officers' member list row (`GET /api/members`). */
export type MemberListing = {
  id: number;
  username: string;
  display_name: string;
  avatar_url: string | null;
  is_guild_member: boolean;
  is_officer: boolean;
  battletag: string | null;
  last_login_at: string | null;
  roster_confirmed: boolean;
};

export type EventKind = "raid" | "dungeon" | "leveling" | "pvp" | "social" | "other";

export const EVENT_KINDS: EventKind[] = ["raid", "dungeon", "leveling", "pvp", "social", "other"];

export const EVENT_KIND_LABELS: Record<EventKind, string> = {
  raid: "Raid",
  dungeon: "Dungeon",
  leveling: "Leveling",
  pvp: "PvP",
  social: "Social",
  other: "Other",
};

/** Kinds whose sign-ups require character, class and role. */
export const ROLE_KINDS: EventKind[] = ["raid", "dungeon"];

export type Role = "tank" | "healer" | "dps";
export type SignupStatus = "signed" | "tentative" | "absent";
export type EventStatus = "scheduled" | "cancelled" | "completed";
export type CharClass = "warrior" | "paladin" | "hunter" | "rogue" | "priest" | "shaman" | "mage" | "warlock" | "druid";

/** A repeating event series' schedule rule, as read back on `EventSeriesSummary.rule`. */
export type SeriesRule = {
  weekdays: number[];
  interval_weeks: 1 | 2;
  /** "HH:MM", 24h, wall-clock in `timezone`. */
  start_time: string;
  timezone: string;
  duration_minutes: number | null;
  starts_on: string;
  until: string | null;
};

/** The lean series reference an occurrence carries on `EventSummary.series`. */
export type SeriesRef = {
  id: string;
  weekdays: number[];
  interval_weeks: 1 | 2;
  start_time: string;
  timezone: string;
};

/** `GET/POST/PATCH /api/event-series` response shape. */
export type EventSeriesSummary = {
  id: string;
  kind: EventKind;
  title: string;
  location: string;
  size: number | null;
  notes: string | null;
  rule: SeriesRule;
  active: boolean;
  next_starts_at: string | null;
};

export type EventCounts = {
  tank: number;
  healer: number;
  dps: number;
  signed: number;
  tentative: number;
  absent: number;
};

export type EventSummary = {
  id: string;
  kind: EventKind;
  title: string;
  /** `""` for events first created in Discord, or kinds that don't track a location. */
  location: string;
  starts_at: string;
  ends_at: string | null;
  /** `null` for events first created in Discord, or when no size was set. */
  size: number | null;
  status: EventStatus;
  notes: string | null;
  counts: EventCounts;
  /** Null for one-off events, or occurrences detached from their series. */
  series: SeriesRef | null;
};

export type SignupMember = { display_name: string; avatar_url: string | null };

export type Signup = {
  id: string;
  member: SignupMember;
  character: string | null;
  class: CharClass | null;
  role: Role | null;
  status: SignupStatus;
  comment: string | null;
  group: number | null;
  bench: boolean;
  updated_at: string;
};

export type EventDetail = EventSummary & { signups: Signup[]; my_signup: Signup | null };

export type Addon = {
  id: string;
  slug: string;
  name: string;
  summary: string;
  version: string;
  download_url: string;
  homepage_url: string | null;
  updated_at: string;
};

export type VoiceChannelCount = { name: string; count: number };

/** ``GET /api/discord/live``: empty counts (``online: null``, ``voice: []``) when the bot hasn't reported recently. */
export type DiscordLive = {
  online: number | null;
  members: number | null;
  voice: VoiceChannelCount[];
  reported_at: string | null;
};

export const CLASSES: CharClass[] = [
  "warrior",
  "paladin",
  "hunter",
  "rogue",
  "priest",
  "shaman",
  "mage",
  "warlock",
  "druid",
];

export const ROLES: Role[] = ["tank", "healer", "dps"];

/** Raised for any non-2xx/204 response; `status` 0 means the request never reached the network. */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Reads a JSON `detail` field out of an unknown parsed error body, if present. */
function readDetail(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const { detail } = data;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }
  return fallback;
}

/**
 * Same-origin JSON fetch with credentials. Throws `ApiError` on network failure or a non-ok
 * status; returns `undefined` for 204 No Content responses.
 */
export async function apiFetch<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: init?.body ? { "content-type": "application/json", ...init.headers } : init?.headers,
    });
  } catch {
    throw new ApiError(0, "network");
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  let data: unknown = null;
  if (text.length > 0) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, readDetail(data, response.statusText));
  }
  return data as T;
}

/** Plain-language copy for the error states the member hub can hit. */
export function statusMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 0:
        return "Couldn't reach the guild hall. Check your connection and try again.";
      case 401:
        return "Sign in with Discord on the account page to see this.";
      case 403:
        return "This is for guild members only.";
      case 404:
        return "That isn't here.";
      case 409:
        return err.detail || "That event isn't open for changes right now.";
      case 503:
        return "Discord login isn't set up yet.";
      default:
        return err.detail || "Something went wrong. Try again in a moment.";
    }
  }
  return "Something went wrong. Try again in a moment.";
}

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** Escapes text interpolated into `innerHTML` templates built from API data. */
export function escapeHtml(input: string): string {
  return input.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char] ?? char);
}

/** Uppercases the first letter only, for enum values like `"tank"` -> `"Tank"`. */
export function capitalize(input: string): string {
  return input.length > 0 ? input.charAt(0).toUpperCase() + input.slice(1) : input;
}

/** Looks up a required element by id, throwing early with a clear message if the markup drifts. */
export function requireElement<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) {
    throw new Error(`Missing #${id} in page markup`);
  }
  return node as T;
}
