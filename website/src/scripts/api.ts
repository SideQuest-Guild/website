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
  is_gm: boolean;
  battletag: string | null;
  roster_confirmed: boolean;
};

export type EventKind = "raid" | "dungeon" | "leveling" | "pvp" | "social" | "transmog" | "other";

export const EVENT_KINDS: EventKind[] = ["raid", "dungeon", "leveling", "pvp", "social", "transmog", "other"];

export const EVENT_KIND_LABELS: Record<EventKind, string> = {
  raid: "Raid",
  dungeon: "Dungeon",
  leveling: "Leveling",
  pvp: "PvP",
  social: "Social",
  transmog: "Transmog",
  other: "Other",
};

/** Attendance EP per kind when an event has no override; mirrors `EVENT_KIND_EP` in sidequest_common. */
export const EVENT_KIND_EP: Record<EventKind, number> = {
  raid: 10,
  dungeon: 5,
  leveling: 3,
  pvp: 3,
  social: 2,
  transmog: 2,
  other: 2,
};

/** The highest attendance EP an officer can set on one event. */
export const MAX_EVENT_EP = 50;

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
  ep: number;
  ep_override: number | null;
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
  /** People who clicked Interested on the event in Discord. */
  interested: number;
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
  /** Attendance EP: `ep_override` if an officer set one, else the kind's preset. */
  ep: number;
  ep_override: number | null;
  status: EventStatus;
  /** `null` for anonymous visitors (no session, no bot `X-API-Key`). */
  notes: string | null;
  /** `null` for anonymous visitors (no session, no bot `X-API-Key`). */
  counts: EventCounts | null;
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

/** Discord "Interested" clicks: `members` lists only people who have signed in on the site. */
export type DiscordInterest = { count: number; members: SignupMember[] };

export type EventDetail = EventSummary & {
  /** Empty for anonymous visitors (no session, no bot `X-API-Key`). */
  signups: Signup[];
  my_signup: Signup | null;
  /** `null` for anonymous visitors (no session, no bot `X-API-Key`). */
  discord_interest: DiscordInterest | null;
  /** Members away (see `AwayRange`) on this event's start date, America/Chicago. `null` for anonymous visitors. */
  away: SignupMember[] | null;
};

export type AddonOrigin = "guild" | "community";

export const ADDON_ORIGINS: AddonOrigin[] = ["guild", "community"];

/** Mirrors `ADDON_ORIGIN_LABELS` in sidequest_common. */
export const ADDON_ORIGIN_LABELS: Record<AddonOrigin, string> = {
  guild: "Made by SideQuest",
  community: "Community pick",
};

export type Addon = {
  id: string;
  slug: string;
  name: string;
  summary: string;
  version: string;
  download_url: string;
  homepage_url: string | null;
  origin: AddonOrigin;
  updated_at: string;
};

/** A Discord role shown on a `GmMember`, highest position first; color `null` means Discord's default (no color). */
export type RoleTag = { id: string; name: string; color: string | null };

/** `GET /api/gm/members[/{id}]` row: everyone who has ever signed in, GM-eyes-only. */
export type GmMember = {
  id: number;
  discord_id: string;
  username: string;
  display_name: string;
  avatar_url: string | null;
  roles: RoleTag[];
  is_guild_member: boolean;
  is_officer: boolean;
  is_gm: boolean;
  roster_confirmed_at: string | null;
  battletag: string | null;
  battlenet_linked_at: string | null;
  first_seen_at: string;
  last_login_at: string | null;
  signup_count: number;
  case_count: number;
  level: number | null;
};

/** One of a member's event sign-ups, as listed on `GmMemberDetail`. */
export type GmSignup = {
  event_id: string;
  title: string;
  kind: EventKind;
  starts_at: string;
  event_status: EventStatus;
  status: SignupStatus;
  character: string | null;
  class: CharClass | null;
  role: Role | null;
  comment: string | null;
};

/** `GET /api/gm/cases[?user_id=]`, and the cases listed on `GmMemberDetail`. */
export type GmCase = {
  case_number: number;
  action: string;
  user_id: string;
  user_name: string | null;
  moderator_id: string;
  moderator_name: string | null;
  reason: string | null;
  duration_seconds: number | null;
  created_at: string;
};

/** `GET /api/gm/members/{id}` full profile. */
export type GmMemberDetail = {
  member: GmMember;
  signups: GmSignup[];
  cases: GmCase[];
  xp: number | null;
  message_count: number | null;
};

export type GmLogKind = "signup" | "sign_in" | "battlenet" | "officer" | "moderation";

/** One row of `GET /api/gm/log`. */
export type LogEntry = {
  id: string;
  at: string;
  kind: GmLogKind;
  actor: { display_name: string; avatar_url: string | null } | null;
  summary: string;
  detail: string | null;
  member_id: number | null;
  event_id: string | null;
  case_number: number | null;
};

export type LogPage = { entries: LogEntry[]; next_before: string | null };

export type AttendanceRange = "last_30" | "season" | "all_time";

/** One past event on the attendance tab's event picker. */
export type AttendanceEventSummary = {
  id: string;
  title: string;
  kind: EventKind;
  starts_at: string;
  status: EventStatus;
  attendance_taken_at: string | null;
  needs_attendance: boolean;
};

/** A guild member not currently signed up for the event, offered as a walk-in. */
export type WalkInCandidate = { member_id: number; display_name: string; avatar_url: string | null };

/** One sign-up on the attendance marking screen (`GET/PUT /api/events/{id}/attendance`). */
export type AttendanceSignup = {
  signup_id: string;
  member_id: number;
  display_name: string;
  avatar_url: string | null;
  character: string | null;
  class: CharClass | null;
  role: Role | null;
  status: SignupStatus;
  attended: boolean | null;
  is_walk_in: boolean;
  voice_minutes: number;
  suggested_attended: boolean;
};

export type AttendanceDetail = {
  event: AttendanceEventSummary;
  signups: AttendanceSignup[];
  walk_in_candidates: WalkInCandidate[];
};

export type AttendanceMarkEntry = { signup_id: string; attended: boolean };

export type WalkInCreate = {
  member_id: number;
  character?: string | null;
  class?: CharClass | null;
  role?: Role | null;
};

export type AttendanceMark = { entries: AttendanceMarkEntry[]; walk_ins: WalkInCreate[] };

/** One member's line on `GET /api/attendance/report`. */
export type MemberAttendanceRow = {
  member_id: number;
  display_name: string;
  avatar_url: string | null;
  signed_up: number;
  came: number;
  no_shows: number;
  walk_ins: number;
  attendance_rate: number;
  last_attended: string | null;
};

export type AttendanceReport = { range: AttendanceRange; raids_only: boolean; rows: MemberAttendanceRow[] };

/** One week's point on `GET /api/attendance/trends`. */
export type AttendanceTrendPoint = { week_start: string; attendees: number; signed_up: number; show_rate: number };

export type AttendanceTrends = { range: AttendanceRange; raids_only: boolean; points: AttendanceTrendPoint[] };

export type VoiceChannelCount = { name: string; count: number };

/** ``GET /api/discord/live``: empty counts (``online: null``, ``voice: []``) when the bot hasn't reported recently. */
export type DiscordLive = {
  online: number | null;
  members: number | null;
  voice: VoiceChannelCount[];
  reported_at: string | null;
};

export type DiscordOnlineStatus = "online" | "idle" | "dnd";

export type DiscordOnlineMember = {
  name: string;
  status: DiscordOnlineStatus;
  avatar_url: string | null;
  activity: string | null;
};

/** ``GET /api/discord/online`` (members only): the guild widget's live roster, or empty when Discord didn't answer. */
export type DiscordOnline = {
  presence_count: number | null;
  members: DiscordOnlineMember[];
  ok: boolean;
};

export type RecruitingPriority = "normal" | "high";

export type RecruitingRoleWant = { role: Role; priority: RecruitingPriority; note: string | null };

export type RecruitingClassWant = { class: CharClass; priority: RecruitingPriority; note: string | null };

/** ``GET /api/recruiting`` (public): what the guild is currently recruiting for, empty if nothing is wanted. */
export type Recruiting = {
  roles: RecruitingRoleWant[];
  classes: RecruitingClassWant[];
  updated_at: string | null;
};

/** `GET/POST /api/me/calendar`: the signed-in member's private calendar feed link. */
export type CalendarLink = { token: string; url: string };

/** One of the signed-in member's away ranges (`GET/POST /api/me/away`); `start_date`/`end_date` are inclusive. */
export type AwayRange = { id: string; start_date: string; end_date: string; note: string | null };

/** One competitive Hall of Heroes season; mirrors `sidequest_common.schemas.heroes.Season`. */
export type Season = { id: string; name: string; starts_at: string; ends_at: string | null };

/** `season-one` is the only entry today; append here (not computed) the day a second season ships. */
export const SEASONS: Season[] = [
  { id: "season-one", name: "Season One", starts_at: "2026-11-04T00:00:00+00:00", ends_at: null },
];

/** One member's stats for one season (or all time), on a leaderboard row or a profile. */
export type HeroSeasonStats = { ep: number; raids_attended: number; events_attended: number; attendance_rate: number };

/** One `GET /api/heroes` leaderboard row. */
export type HeroRow = {
  /** Position by EP this season; `null` for members listed with no EP yet. */
  rank: number | null;
  member_id: number;
  discord_id: string;
  display_name: string;
  avatar_url: string | null;
  wow_class: CharClass | null;
  chat_level: number;
  ep: number;
  raids_attended: number;
  events_attended: number;
  badge_ids: string[];
};

/** `GET /api/heroes?season=<id|all|month>`. Members only: 401 signed out. */
export type HeroLeaderboard = { season_id: string; season_name: string; rows: HeroRow[] };

/** One recent event on a profile's recent-events list. */
export type HeroRecentEvent = { id: string; kind: EventKind; title: string; starts_at: string; ep: number };

/** One badge a member has earned, for the profile's badge case; mirrors `sidequest_common.schemas.badges.EarnedBadge`. */
export type EarnedBadge = { id: string; name: string; description: string; icon: string; earned_at: string };

/** `GET /api/heroes/{member_id}`. Members only: 401 signed out, 404 unknown member. */
export type HeroProfile = {
  member_id: number;
  discord_id: string;
  display_name: string;
  avatar_url: string | null;
  wow_class: CharClass | null;
  rank: number | null;
  chat_level: number;
  chat_xp: number;
  chat_xp_into_level: number;
  chat_xp_for_next_level: number;
  seasons: Record<string, HeroSeasonStats>;
  all_time: HeroSeasonStats;
  first_event_date: string | null;
  recent_events: HeroRecentEvent[];
  badges: EarnedBadge[];
};

/** Badge id -> name, for the leaderboard's badge tooltips; mirrors `sidequest_common.schemas.badges.BADGES`
 * (id and name only — the website never needs the Discord role color or the earning thresholds. Icons are drawn
 * gold sigils in `Sprites.astro`, not sent by the API). */
export const BADGE_INFO: Record<string, { name: string }> = {
  first_steps: { name: "First Steps" },
  first_raid: { name: "First Raid" },
  raid_regular: { name: "Raid Regular" },
  raid_veteran: { name: "Raid Veteran" },
  perfect_month: { name: "Perfect Month" },
  founding_member: { name: "Founding Member" },
  chatterbox: { name: "Chatterbox" },
  top_helper: { name: "Top Helper" },
};

/** Badge id -> the `Sprites.astro` symbol id for its gold sigil (e.g. `raid_veteran` -> `i-badge-raid-veteran`). */
export function badgeIconId(id: string): string {
  return `i-badge-${id.replaceAll("_", "-")}`;
}

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

/** Lowercases a WoW class token as the addon reports it (e.g. `"WARRIOR"`) to match `CharClass` and the
 * `cls-*` color classes; `null`/empty stays `null` ("no class yet"). */
export function normalizeClass(cls: string | null | undefined): CharClass | null {
  return cls ? (cls.toLowerCase() as CharClass) : null;
}

/** Display label for a class token in any casing, e.g. the addon's `"WARRIOR"` or the site's own `"warrior"`;
 * used wherever a character's class may be unknown (`null`): the ledger, the officer console's character links. */
export function classLabel(cls: string | null | undefined): string {
  const normalized = normalizeClass(cls);
  return normalized ? capitalize(normalized) : "No class yet";
}

// ——— EPGP loot system: GET/POST /api/epgp/*, GET/POST/DELETE /api/me/characters. Mirrors the shapes in the
// addon ↔ site contract (local://addon-contract.md): the site owns the numbers, the addon only records facts.

/** The site's current loot rules, served on `GET /api/epgp/standings` and embedded in the `SQI1:` import string. */
export type EpgpRules = {
  ep: { boss_kill: number; progress: number; on_time: number; full_night: number };
  /** Keyed by `INVTYPE_*` (e.g. `"INVTYPE_HEAD"`). */
  gp: Record<string, number>;
  chase_multiplier: number;
  legendary_gp: number;
  os_percent: number;
  base_gp: number;
  min_gp: number;
  decay_percent: number;
  trial_days: number;
};

/** One row of `GET /api/epgp/standings`; `member_id: null` means an imported character nobody has linked yet. */
export type EpgpStandingRow = {
  member_id: number | null;
  name: string;
  main: string | null;
  /** As the addon reports it (e.g. `"WARRIOR"`); lowercase before using a `cls-*` color class. */
  class: string | null;
  characters: string[];
  ep: number;
  gp: number;
  pr: number;
  trial: boolean;
};

export type EpgpStandings = { generated_at: string; rules: EpgpRules; rows: EpgpStandingRow[] };

export type EpgpLedgerKind = "ep" | "gp";
export type EpgpLedgerReason = "boss_kill" | "progress" | "on_time" | "full_night" | "standby" | "loot" | "adjust";

/** One row of `GET /api/epgp/ledger`, newest first. `decayed` is `amount` after weekly decay is applied on read. */
export type EpgpLedgerEntry = {
  id: string;
  at: string;
  kind: EpgpLedgerKind;
  amount: number;
  decayed: number;
  reason: EpgpLedgerReason;
  note: string | null;
  character: string | null;
  member_id: number | null;
  member_name: string | null;
  officer: string | null;
  item_name: string | null;
  voided: boolean;
};

export type EpgpLedgerPage = { entries: EpgpLedgerEntry[] };

export type EpgpLootResponseKind = "ms" | "os" | "alt" | "council" | "de" | "bank";

/** One row of `GET /api/epgp/loot`, newest first. */
export type EpgpLootItem = {
  id: string;
  at: string;
  item_id: number;
  item_name: string;
  /** 0-4, the game's item-quality scale (matches `--q-*` CSS vars from 1 up; 0 is poor and unused here). */
  quality: number;
  character: string;
  member_id: number | null;
  member_name: string | null;
  response: EpgpLootResponseKind;
  gp: number;
  instance_name: string | null;
  encounter_name: string | null;
  voided: boolean;
};

export type EpgpLootPage = { items: EpgpLootItem[] };

/** One encounter's attempt history on `GET /api/epgp/progression`. */
export type EpgpProgressionEncounter = {
  encounter_id: number;
  name: string;
  first_kill_at: string | null;
  kills: number;
  wipes: number;
  last_attempt_at: string | null;
};

export type EpgpProgressionInstance = {
  instance_id: number;
  name: string;
  size: number;
  encounters: EpgpProgressionEncounter[];
};

export type EpgpProgression = { instances: EpgpProgressionInstance[] };

/** `POST /api/epgp/imports` response: what an `SQX1:` export string changed on the ledger. */
export type EpgpImportResult = {
  recorder: string;
  sessions: { new: number; updated: number };
  encounters: { new: number; updated: number };
  loot: { new: number; updated: number; voided: number };
  awards: { new: number; updated: number; voided: number };
  unlinked_characters: string[];
  attendance: { event_id: string | null; marked: number };
  /** Session ids skipped because they overlapped another recorder's session for the same instance. */
  conflicts: string[];
};

/** `GET /api/epgp/game-import`: the `SQI1:` string an officer pastes into `/sq import`. */
export type EpgpGameImport = { payload: string; generated_at: string };

export type EpgpAdjustmentCreate = { member_id: number; kind: EpgpLedgerKind; amount: number; reason: string };

export type EpgpCharacterSource = "claim" | "officer" | "signup" | "import";

/** A character linked (or not yet linked) to a member; same shape on `GET /api/epgp/characters` and
 * `GET/POST /api/me/characters`. */
export type EpgpCharacter = {
  id: string;
  name: string;
  realm: string;
  class: string | null;
  member_id: number | null;
  member_name: string | null;
  is_main: boolean;
  source: EpgpCharacterSource;
  last_seen_at: string | null;
};

export type EpgpCharacters = { characters: EpgpCharacter[] };

export type EpgpRosterStatus = "trial" | "raider" | null;

/** One row of `GET /api/epgp/roster`: every guild member, with their raid status for bid order and GP charges. */
export type EpgpRosterMember = {
  member_id: number;
  name: string;
  raid_status: EpgpRosterStatus;
  trial_started_at: string | null;
};

export type EpgpRoster = { members: EpgpRosterMember[] };

/** `GET /api/epgp/sync-tokens` row; the token itself is only ever sent once, on creation. */
export type EpgpSyncToken = { id: string; name: string; created_at: string; last_used_at: string | null };

export type EpgpSyncTokens = { tokens: EpgpSyncToken[] };

export type EpgpSyncTokenCreated = { id: string; name: string; token: string };

// ——— Guild app v2: the addon as the guild's all-round app (local://addon-contract-v2.md). ———

/** One linked character on a `GuildRosterMember` row. */
export type GuildRosterCharacter = {
  name: string;
  class: string | null;
  level: number | null;
  zone: string | null;
  last_seen_at: string | null;
  is_main: boolean;
};

/** One member row of `GET /api/guild/roster`. */
export type GuildRosterMember = {
  member_id: number;
  name: string;
  rank: string | null;
  raid_status: EpgpRosterStatus;
  main: string | null;
  characters: GuildRosterCharacter[];
};

/** A character seen in the guild roster snapshot with no linked member. */
export type GuildRosterUnlinked = {
  name: string;
  class: string | null;
  level: number | null;
  rank: string | null;
  last_seen_at: string | null;
};

/** `GET /api/guild/roster` (member). */
export type GuildRoster = { taken_at: string; members: GuildRosterMember[]; unlinked: GuildRosterUnlinked[] };

/** One crafter on a `GET /api/guild/crafters` recipe result, or the `crafters` count on a profession summary. */
export type GuildCrafter = {
  character: string;
  member_id: number | null;
  member_name: string | null;
  profession: string;
  skill: number;
};

/** One recipe match of `GET /api/guild/crafters`. */
export type GuildCrafterResult = {
  recipe_id: number;
  recipe_name: string;
  item_id: number | null;
  crafters: GuildCrafter[];
};

/** One profession summary of `GET /api/guild/crafters`. */
export type GuildCrafterProfession = { profession: string; crafters: number };

/** `GET /api/guild/crafters?q=&profession=` (member). */
export type GuildCrafters = { results: GuildCrafterResult[]; professions: GuildCrafterProfession[] };

export type GuildNewsKind = "boss_kill" | "first_kill" | "loot" | "level" | "joined" | "announcement" | "badge";

/** One row of `GET /api/guild/news`, newest first; mirrors the import string's `news` shape. */
export type GuildNewsItem = {
  id: string;
  at: string;
  kind: GuildNewsKind;
  text: string;
  character: string | null;
  item_id: number | null;
  quality: number | null;
};

export type GuildNews = { items: GuildNewsItem[] };

export type GuildBankKind = "deposit" | "withdraw" | "move" | "repair" | "buy_tab" | "deposit_money" | "withdraw_money";

/** One row of `GET /api/guild/bank`, newest first. */
export type GuildBankRow = {
  id: string;
  at: string;
  character: string;
  member_name: string | null;
  kind: GuildBankKind;
  item_id: number | null;
  item_name: string | null;
  count: number | null;
  money: number;
  tab: number | null;
};

export type GuildBank = { rows: GuildBankRow[]; totals: { deposits_30d: number; withdrawals_30d: number } };

/** One row of `GET /api/guild/announcements`, newest first (last 20). */
export type GuildAnnouncement = {
  id: string;
  text: string;
  author: string;
  at: string;
  source: "game" | "site";
  posted_at: string | null;
};

export type GuildAnnouncements = { items: GuildAnnouncement[] };

export type GuildAnnouncementCreate = { text: string; discord: boolean };

export type EpgpRecruitStatus = "applicant" | "trial" | "accepted" | "declined";

/** An officer's talked/gear_check/first_raid/vouched checklist on a recruit. */
export type EpgpRecruitChecklist = { talked: boolean; gear_check: boolean; first_raid: boolean; vouched: boolean };

export type EpgpRecruitVoteValue = "yes" | "no" | "wait";

export type EpgpRecruitVote = { officer: string; vote: EpgpRecruitVoteValue; at: string };

/** One row of `GET /api/epgp/recruits` (officer-only). */
export type EpgpRecruit = {
  id: string;
  character: string;
  class: string | null;
  status: EpgpRecruitStatus;
  note: string | null;
  member_id: number | null;
  checklist: EpgpRecruitChecklist;
  votes: EpgpRecruitVote[];
  at: string;
};

export type EpgpRecruits = { recruits: EpgpRecruit[] };

export type EpgpRecruitUpdate = { status?: EpgpRecruitStatus; note?: string; checklist?: EpgpRecruitChecklist };

export type EpgpRecruitVoteCreate = { vote: EpgpRecruitVoteValue };

/** One row of `GET /api/epgp/member-notes?member_id=` (officer-only). */
export type EpgpMemberNote = {
  id: string;
  character: string;
  note: string;
  officer: string;
  at: string;
  voided: boolean;
};

export type EpgpMemberNotes = { notes: EpgpMemberNote[] };

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

let sharedMe: Promise<Me> | null = null;

/**
 * ``GET /api/me``, asked once per page load: the nav's Officers link and the page's own script share the answer
 * (and the head's preload of it). Pass ``fresh`` after something changed the account.
 */
export function fetchMe({ fresh = false }: { fresh?: boolean } = {}): Promise<Me> {
  if (fresh || sharedMe === null) {
    sharedMe = apiFetch<Me>("/api/me");
  }
  return sharedMe;
}

// Page scripts register what they show; the router swapping the page away drops them all (scripts/page.ts).
const freshListeners = new Map<string, Set<() => void>>();
let listeningForFresh = false;

function listenForFresh(): void {
  listeningForFresh = true;
  document.addEventListener("astro:before-swap", () => freshListeners.clear());
  navigator.serviceWorker.addEventListener("message", (event: MessageEvent<{ type?: string; url?: string }>) => {
    if (event.data?.type !== "sq-fresh" || !event.data.url) {
      return;
    }
    if (event.data.url === "*") {
      sharedMe = null;
    }
    const targets = event.data.url === "*" ? [...freshListeners.values()] : [freshListeners.get(event.data.url)];
    for (const reloads of targets) {
      reloads?.forEach((run) => run());
    }
  });
}

/**
 * Re-runs ``reload`` when the service worker has a newer copy of ``path`` than the one it just answered from the
 * device (or ``"*"``: everything changed, e.g. a sign-out). Only pages listed in ``STALE_FIRST`` in
 * ``service-worker/sw.js`` get device-first answers, and each of them must register here for what it shows.
 */
export function onFreshData(path: string, reload: () => void): void {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  if (!listeningForFresh) {
    listenForFresh();
  }
  let reloads = freshListeners.get(path);
  if (!reloads) {
    reloads = new Set();
    freshListeners.set(path, reloads);
  }
  reloads.add(reload);
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
