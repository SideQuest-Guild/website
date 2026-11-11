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

export type EventKind = "raid" | "dungeon" | "world_boss" | "leveling" | "pvp" | "social" | "transmog" | "other";

export const EVENT_KINDS: EventKind[] = [
  "raid",
  "dungeon",
  "world_boss",
  "leveling",
  "pvp",
  "social",
  "transmog",
  "other",
];

export const EVENT_KIND_LABELS: Record<EventKind, string> = {
  raid: "Raid",
  dungeon: "Dungeon",
  world_boss: "World Boss",
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
  world_boss: 5,
  leveling: 3,
  pvp: 3,
  social: 2,
  transmog: 2,
  other: 2,
};

/** The highest attendance EP an officer can set on one event. */
export const MAX_EVENT_EP = 50;

/** Kinds whose sign-ups require character, class and role. */
export const ROLE_KINDS: EventKind[] = ["raid", "dungeon", "world_boss"];

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

// ——— Raid readiness (RaidReadinessUI) ———
/** A signed-up character's gear readiness for a raid, from the matched roster character's Battle.net profile. */
export type SignupReadiness = {
  slug: string;
  level: number;
  /** `null` when the character has no published Battle.net profile yet. */
  item_level: number | null;
  spec: string | null;
  below_minimum: boolean;
};

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
  /** `null` when the sign-up's character name matches no single roster character. */
  readiness?: SignupReadiness | null;
};

/** `PUT /api/raid-readiness` request/response body. */
export type RaidReadiness = { min_item_level: number | null };

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
  /** Raid gear floor officers set with `PUT /api/raid-readiness`. `null` when none is set. */
  min_item_level?: number | null;
};

export type AddonOrigin = "guild" | "community";

export const ADDON_ORIGINS: AddonOrigin[] = ["guild", "community"];

/** Mirrors `ADDON_ORIGIN_LABELS` in sidequest_common. */
export const ADDON_ORIGIN_LABELS: Record<AddonOrigin, string> = {
  guild: "Made by SideQuest",
  community: "Community pick",
};

export type AddonCategory = "raid_required" | "raid" | "general" | "leveling" | "pvp";

/** Contract (display) order: matches `AddonCategory` in sidequest_common. */
export const ADDON_CATEGORIES: AddonCategory[] = ["raid_required", "raid", "general", "leveling", "pvp"];

/** Mirrors `ADDON_CATEGORY_LABELS` in sidequest_common. */
export const ADDON_CATEGORY_LABELS: Record<AddonCategory, string> = {
  raid_required: "Required for raids",
  raid: "Suggested for raids",
  general: "Suggested for everyone",
  leveling: "Suggested for leveling",
  pvp: "Suggested for PvP",
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
  category: AddonCategory;
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
  party_animal: { name: "Party Animal" },
  party_leader: { name: "Party Leader" },
  open_road: { name: "Open Road" },
  crossroads_host: { name: "Crossroads Host" },
  caravan_master: { name: "Caravan Master" },
};

/** Badge id -> the `Sprites.astro` symbol id for its gold sigil (e.g. `raid_veteran` -> `i-badge-raid-veteran`). */
export function badgeIconId(id: string): string {
  return `i-badge-${id.replaceAll("_", "-")}`;
}

// ——— Group voice channels (#lfg): GET /api/groups/stats, /api/groups/sessions[/{id}], /api/groups/leaderboard.
// Mirrors sidequest_common.schemas.groups; snowflakes are strings on the wire.

/** The kinds the `#lfg` panel offers. Mirrors `GROUP_KINDS`/`GROUP_KIND_LABELS` in sidequest_common; `social` is
 * labeled "Hangout" here, unlike `EVENT_KIND_LABELS`' "Social". */
export type GroupKind = "dungeon" | "raid" | "world_boss" | "leveling" | "pvp" | "social";

export const GROUP_KINDS: GroupKind[] = ["dungeon", "raid", "world_boss", "leveling", "pvp", "social"];

export const GROUP_KIND_LABELS: Record<GroupKind, string> = {
  dungeon: "Dungeon",
  raid: "Raid",
  world_boss: "World Boss",
  leveling: "Leveling",
  pvp: "PvP",
  social: "Hangout",
};

/** Looks up a group's kind label, falling back to the event kind label for any kind groups never actually use. */
export function groupKindLabel(kind: EventKind): string {
  return (GROUP_KIND_LABELS as Record<string, string>)[kind] ?? EVENT_KIND_LABELS[kind];
}

export type GroupEndReason = "empty" | "unjoined" | "owner" | "lost";

/** Someone on a stats list. `member_id` is set when they have a site account (links to their profile). */
export type GroupPerson = { discord_id: string; display_name: string; member_id: number | null };

/** One person's line on a stats list: `value` is minutes, groups, or partners depending on the list. */
export type GroupPersonStat = { person: GroupPerson; value: number; sessions: number };

/** Two people who grouped together. */
export type GroupDuoStat = { a: GroupPerson; b: GroupPerson; minutes: number; sessions: number };

/** Counted sessions and member-minutes for one kind. */
export type GroupKindStat = { kind: EventKind; sessions: number; minutes: number };

/** How often a named group (an instance, usually) was run. */
export type GroupInstanceStat = { kind: EventKind; name: string; sessions: number };

/** Counted sessions that started in one weekday/hour slot, America/Chicago. `weekday` 0 is Monday. */
export type GroupHourStat = { weekday: number; hour: number; sessions: number };

/** `GET /api/groups/stats` (officer): who groups, with whom, and what, over the last `days` days. Only counted
 * sessions feed the lists; `sessions_total` includes the rest. Lists hold at most ten lines each. */
export type GroupStats = {
  days: number;
  sessions_total: number;
  sessions_counted: number;
  grouped_minutes: number;
  by_kind: GroupKindStat[];
  top_instances: GroupInstanceStat[];
  most_grouped: GroupPersonStat[];
  most_social: GroupPersonStat[];
  best_duos: GroupDuoStat[];
  most_led: GroupPersonStat[];
  busy_hours: GroupHourStat[];
};

/** One message from a group channel's text chat. */
export type GroupTranscriptMessage = {
  author_discord_id: string;
  author_name: string;
  content: string;
  created_at: string;
  attachments: string[];
};

/** One line on `GET /api/groups/sessions` (officer). */
export type GroupSessionSummary = {
  id: string;
  kind: EventKind;
  name: string | null;
  channel_name: string;
  creator: GroupPerson;
  event_id: string | null;
  started_at: string;
  ended_at: string | null;
  end_reason: GroupEndReason | null;
  peak_size: number;
  grouped_minutes: number;
  counted: boolean;
  has_transcript: boolean;
};

/** `GET /api/groups/sessions/{id}` (officer): one session with who was in it and its chat, if still kept.
 * `transcript` is `null` once purged or past `transcript_expires_at`. */
export type GroupSessionDetail = GroupSessionSummary & {
  note: string | null;
  needs: Role[];
  members: GroupPersonStat[];
  transcript: GroupTranscriptMessage[] | null;
  transcript_expires_at: string | null;
};

/** One line on the public "most grouped" board. Only members with a site account appear. */
export type GroupLeaderboardRow = { member_id: number; display_name: string; groups: number; minutes: number };

/** `GET /api/groups/leaderboard` (public): members by counted groups joined, last 30 days and all time. */
export type GroupLeaderboard = { month: GroupLeaderboardRow[]; all_time: GroupLeaderboardRow[] };

export type StatsRange = "7d" | "30d" | "90d" | "all";

export const STATS_RANGES: StatsRange[] = ["7d", "30d", "90d", "all"];

export const STATS_RANGE_LABELS: Record<StatsRange, string> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  all: "All time",
};

/** Someone on a stats leaderboard or the "gone quiet" list; `member_id` is set when they have a site account. */
export type StatsPerson = {
  discord_id: string;
  display_name: string;
  avatar_url: string | null;
  member_id: number | null;
};

/** One line on a guild stats leaderboard: `value` is messages, voice minutes, events, groups or XP depending on the
 * list. */
export type StatsLeader = { person: StatsPerson; value: number };

/** `GET /api/stats` totals for one window, reused for both `totals` and the same-length `previous` window. */
export type StatsTotals = {
  active_members: number;
  messages: number;
  voice_minutes: number;
  events_attended: number;
  groups_joined: number;
  xp_gained: number;
};

/** One bucket on the guild stats trend chart, oldest first, zero-filled across the window. */
export type StatsTrendPoint = { start: string; messages: number; voice_minutes: number; active_members: number };

/** One non-zero cell of a weekday/hour activity heatmap, America/Chicago. `weekday` 0 is Monday. Shared by the
 * officers' guild-wide heatmap and a hero's own 90-day heatmap. */
export type StatsHourCell = { weekday: number; hour: number; messages: number; voice_minutes: number };

/** One member with no tracked message, voice or event activity in the last 30 days, on the officers' "Gone quiet"
 * list. */
export type StatsQuietMember = { person: StatsPerson; last_active_at: string | null; level: number };

/** `GET /api/stats?range=7d|30d|90d|all` (officer): guild-wide activity totals, trend, heatmap and leaderboards. */
export type GuildStats = {
  range: StatsRange;
  since: string | null;
  /** Earliest tracked `member_activity_hour` row in the guild; `null` if tracking hasn't started. */
  tracking_since: string | null;
  totals: StatsTotals;
  /** The same-length window right before `since`; `null` for `"all"`. */
  previous: StatsTotals | null;
  trend_bucket: "day" | "week";
  trend: StatsTrendPoint[];
  /** Non-zero cells only. */
  heatmap: StatsHourCell[];
  top_chatters: StatsLeader[];
  top_voice: StatsLeader[];
  top_events: StatsLeader[];
  top_groups: StatsLeader[];
  top_xp: StatsLeader[];
  gone_quiet: StatsQuietMember[];
};

/** XP earned by source on a hero's activity profile; `earlier` is XP earned before tracking started (or from
 * sources the breakdown doesn't cover), floored at zero. */
export type HeroXPSources = { chat: number; voice: number; events: number; groups: number; earlier: number };

/** The next level-role reward above a hero's current level, if the guild has one configured. */
export type HeroLevelReward = { level: number; role_name: string };

/** One day on a hero's last-30-days activity chart, oldest first, zero-filled. */
export type HeroDay = { day: string; messages: number; voice_minutes: number };

/** `GET /api/heroes/{member_id}/activity` (member, same gate as `GET /api/heroes/{id}`): the Hall of Heroes
 * profile's MEE6-style stats section — level, XP bar, guild-wide rank, streaks, sources and activity charts. */
export type HeroActivity = {
  member_id: number;
  level: number;
  xp: number;
  xp_into_level: number;
  xp_for_next_level: number;
  /** Guild-wide rank by total XP, like `/rank`; `null` if the member has no XP yet. */
  xp_rank: number | null;
  ranked_members: number;
  next_reward: HeroLevelReward | null;
  /** Lifetime message count. */
  message_count: number;
  /** All tracked voice minutes, lifetime. */
  voice_minutes: number;
  events_attended: number;
  groups_joined: number;
  messages_30d: number;
  voice_minutes_30d: number;
  /** Position among members by 30-day messages/voice; `null` if the member has none in the window. */
  chat_rank_30d: number | null;
  voice_rank_30d: number | null;
  current_streak_days: number;
  longest_streak_days: number;
  xp_sources: HeroXPSources;
  days: HeroDay[];
  /** Last 90 days, non-zero cells only. */
  heatmap: StatsHourCell[];
  tracking_since: string | null;
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
  /** Python `datetime.weekday()` value the weekly reset lands on (1 = Tuesday, Monday = 0); see
   * `epgp-calculator.ts`'s `nextResetAt` for converting to a JS day index. */
  weekly_reset_weekday: number;
  weekly_reset_hour_utc: number;
};

/** One row of `GET /api/epgp/standings`; `member_id: null` means an imported character nobody has linked yet. */
export type EpgpStandingRow = {
  member_id: number | null;
  name: string;
  /** The main character's key, for `GET /api/epgp/ledger?character=`. Show `main_name` instead. */
  main: string | null;
  /** The main character's name as the game shows it (`First Surname`). */
  main_name: string | null;
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
  response: EpgpLootResponseKind | null;
  voided: boolean;
};

export type EpgpLedgerPage = { entries: EpgpLedgerEntry[] };

export type EpgpLootResponseKind = "ms" | "os" | "alt" | "council" | "de" | "bank";
export type EpgpCouncilKind = "chase" | "legendary" | "tier";

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
  council_reason: string | null;
  council_kind: EpgpCouncilKind | null;
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

export type EpgpCharacterSource = "claim" | "officer" | "signup" | "import" | "battlenet";

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

/** `GET /api/me/mcp-tokens` row; the token itself is only ever sent once, on creation. */
export type McpToken = { id: string; name: string; created_at: string; last_used_at: string | null };

export type McpTokens = { tokens: McpToken[] };

export type McpTokenCreated = { id: string; name: string; token: string };

/** `POST /api/epgp/device-authorizations` response: poll `.../token` with `device_code`. */
export type EpgpDeviceAuthorizationCreated = {
  device_code: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string;
  expires_in: number;
  interval: number;
};

export type DeviceAuthorizationPollStatus = "pending" | "slow_down" | "denied" | "expired" | "approved";

/** `POST /api/epgp/device-authorizations/token` response: always 200, never an oracle for a bad code. */
export type EpgpDeviceAuthorizationPollResult = {
  status: DeviceAuthorizationPollStatus;
  token: string | null;
  name: string | null;
};

export type DeviceAuthorizationStatus = "pending" | "approved" | "denied" | "expired";

/** `GET /api/epgp/device-authorizations/{user_code}` response (officer). */
export type EpgpDeviceAuthorizationStatus = {
  user_code: string;
  device_name: string;
  created_at: string;
  expires_at: string;
  status: DeviceAuthorizationStatus;
};
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

/** `GET /api/guild/roster` (member). `taken_at` is null until the addon has synced a roster. */
export type GuildRoster = {
  taken_at: string | null;
  members: GuildRosterMember[];
  unlinked: GuildRosterUnlinked[];
};

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
  /** The matching Battle.net recipe id, if Battle.net was reachable; links to `/recipes/detail/?id=`. */
  battlenet_recipe_id: number | null;
  crafters: GuildCrafter[];
};

/** One profession summary of `GET /api/guild/crafters`. */
export type GuildCrafterProfession = { profession: string; crafters: number };

/** `GET /api/guild/crafters?q=&profession=` (member). */
export type GuildCrafters = { results: GuildCrafterResult[]; professions: GuildCrafterProfession[] };

/** One profession on a `GET /api/guild/directory` character row. */
export type GuildDirectoryProfession = { name: string; skill: number; max_skill: number };

/** One tracked reputation on a `GET /api/guild/directory` character row. */
export type GuildDirectoryReputation = { faction_id: number; standing: number; value: number };

/** One craft cooldown on a `GET /api/guild/directory` character row; `ready_at` in the past means ready now. */
export type GuildDirectoryCooldown = { key: string; ready_at: string };

/** When each directory section was last updated for a character; `null` means never shared. */
export type GuildDirectoryFreshness = {
  prof: string | null;
  char: string | null;
  cd: string | null;
  market: string | null;
  stock: string | null;
};

/** One character row of `GET /api/guild/directory` (member). */
export type GuildDirectoryCharacter = {
  character: string;
  member_id: number | null;
  member_name: string | null;
  professions: GuildDirectoryProfession[];
  level: number | null;
  class: string | null;
  race: string | null;
  spec: string | null;
  item_level: number | null;
  attunements: string[];
  reputations: GuildDirectoryReputation[];
  cooldowns: GuildDirectoryCooldown[];
  freshness: GuildDirectoryFreshness;
};

/** `GET /api/guild/directory` (member). */
export type GuildDirectory = { characters: GuildDirectoryCharacter[] };

/** One `sell` row of `GET /api/guild/market` (member). */
export type GuildMarketSellRow = {
  character: string;
  member_name: string | null;
  item_id: number;
  item_name: string | null;
  price: number | null;
  qty: number;
  crafted: boolean;
};

/** One `buy` row of `GET /api/guild/market` (member). */
export type GuildMarketBuyRow = {
  character: string;
  member_name: string | null;
  item_id: number;
  item_name: string | null;
  price: number | null;
};

/** One `requests` row of `GET /api/guild/market` (member). */
export type GuildMarketRequestRow = {
  id: string;
  character: string;
  member_name: string | null;
  item_id: number;
  item_name: string | null;
  qty: number;
  price: number | null;
  note: string | null;
  at: string;
};

/** `GET /api/guild/market` (member): everyone's sell/buy listings and open material requests. */
export type GuildMarket = {
  sell: GuildMarketSellRow[];
  buy: GuildMarketBuyRow[];
  requests: GuildMarketRequestRow[];
};

/** One character's holdings on `GET /api/guild/stock?item_id=` (member). */
export type GuildStockRow = {
  character: string;
  member_name: string | null;
  bags: number;
  bank: number;
  bank_at: string | null;
};

/** `GET /api/guild/stock?item_id=` (member): who holds the item, in bags or bank. */
export type GuildStock = { item_id: number; item_name: string | null; rows: GuildStockRow[] };

/** One row of `GET /api/guild/officers` (public), sorted by rank then name. */
export type GuildOfficer = {
  character: string;
  name: string;
  rank: string;
  rank_index: number;
  class: CharClass | null;
  level: number;
  online: boolean;
  last_seen_at: string | null;
};

/** `GET /api/guild/officers` (public): current members on an officer rank. */
export type GuildOfficers = { officers: GuildOfficer[] };

// ——— Item catalog: GET /api/items[?q=&page=&quality=&slot=], GET /api/items/{id}. Battle.net-backed, so a 503
// means Battle.net itself is down/unconfigured; mirrors `sidequest_common.schemas.items` (once it exists there).

/** Battle.net's quality constant, as `ItemSchema.quality` and the `quality` query filter use it. */
export type ItemQuality = "POOR" | "COMMON" | "UNCOMMON" | "RARE" | "EPIC" | "LEGENDARY";

export const ITEM_QUALITIES: ItemQuality[] = ["POOR", "COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY"];

/** Lowercases a Battle.net quality constant to match the `q-*` color classes (`citadel.css`). */
export function qualityClass(quality: string): string {
  return quality.toLowerCase();
}

/** The inventory-type constants `GET /api/items` accepts as `slot`, with plain-word labels for the search form's
 * slot picker. Covers the slots gear actually fills; omits the rarer ones (ammo, tabard, bag) nobody searches for. */
export const ITEM_SLOTS: { key: string; label: string }[] = [
  { key: "HEAD", label: "Head" },
  { key: "NECK", label: "Neck" },
  { key: "SHOULDER", label: "Shoulder" },
  { key: "CHEST", label: "Chest" },
  { key: "ROBE", label: "Chest (robe)" },
  { key: "WAIST", label: "Waist" },
  { key: "LEGS", label: "Legs" },
  { key: "FEET", label: "Feet" },
  { key: "WRIST", label: "Wrist" },
  { key: "HAND", label: "Hands" },
  { key: "FINGER", label: "Ring" },
  { key: "TRINKET", label: "Trinket" },
  { key: "CLOAK", label: "Cloak" },
  { key: "HOLDABLE", label: "Off-hand" },
  { key: "SHIELD", label: "Shield" },
  { key: "WEAPON", label: "One-hand weapon" },
  { key: "WEAPONMAINHAND", label: "Main-hand weapon" },
  { key: "WEAPONOFFHAND", label: "Off-hand weapon" },
  { key: "TWOHWEAPON", label: "Two-hand weapon" },
  { key: "RANGED", label: "Ranged" },
  { key: "THROWN", label: "Thrown" },
  { key: "RELIC", label: "Relic" },
];

/** One `GET /api/items` search result row. */
export type ItemSummary = {
  item_id: number;
  name: string;
  quality: ItemQuality;
  quality_name: string;
  inventory_type: string;
  inventory_type_name: string;
  item_level: number;
  required_level: number;
};

/** `GET /api/items?q=&page=&quality=&slot=` (public): `q` min 3 chars. 50 results per page, 20 pages max. */
export type ItemSearch = { page: number; page_count: number; results: ItemSummary[] };

/** What SQL charges for an item before an officer's choices; `null` when the loot rules don't price its slot. */
export type ItemLootPrice = { main_spec: number; off_spec: number; chase: number };

/** `GET /api/items/{item_id}` (public): the full item sheet, tooltip lines in game order. 404 unknown item. */
export type Item = ItemSummary & {
  item_class: string;
  item_subclass: string;
  sell_price: number;
  is_equippable: boolean;
  icon_url: string | null;
  tooltip: string[];
  loot_price: ItemLootPrice | null;
};

// ——— Professions, recipes, and class/spec art: GET /api/professions[/{id}], GET /api/recipes/{id},
// GET /api/game/classes. Battle.net-backed reference data; mirrors `sidequest_common.schemas.recipes`. A 503
// means Battle.net itself is down or unconfigured.

/** One `GET /api/professions` row. */
export type Profession = {
  id: number;
  name: string;
  type: "PRIMARY" | "SECONDARY";
  icon_url: string | null;
  skill_tier_id: number;
};

/** A recipe reference in a skill tier category: just enough to list and link it. */
export type RecipeRef = { id: number; name: string };

/** A group of recipes in a profession's skill tier, such as Weapon Stones. */
export type RecipeCategory = { name: string; recipes: RecipeRef[] };

/** `GET /api/professions/{id}` (public): one profession's skill tier, its categories and recipes. 404 unknown. */
export type ProfessionSkillTier = { profession_id: number; profession_name: string; categories: RecipeCategory[] };

/** The item a recipe makes. */
export type RecipeCraftedItem = { item_id: number; name: string; quality: string | null };

/** One reagent a recipe uses, and how many. */
export type RecipeReagent = { item_id: number; name: string; quantity: number; quality: string | null };

/** A guild character that knows a recipe, matched from the addon's profession data by profession and name. */
export type RecipeCrafter = { character: string; member_id: number | null; member_name: string | null; skill: number };

/** `GET /api/recipes/{id}` (public): a single recipe, with its reagents and the guild characters who know it. */
export type RecipeDetailInfo = {
  recipe_id: number;
  name: string;
  description: string | null;
  rank: number | null;
  profession: string | null;
  icon_url: string | null;
  crafted_item: RecipeCraftedItem | null;
  crafted_quantity: string | null;
  reagents: RecipeReagent[];
  crafters: RecipeCrafter[];
};

/** One specialization on a `GameClass`, for the site's small class/spec icons. */
export type GameSpec = { id: number; name: string; icon_url: string | null };

/** `GET /api/game/classes` (public): one playable class, its specs and small art. */
export type GameClass = { class: CharClass; name: string; icon_url: string | null; specs: GameSpec[] };

// ——— Characters: GET /api/characters/[?q=], GET /api/characters/{slug}, GET /api/characters/boards. A
// Battle.net-backed roster + public character sheet; mirrors `sidequest_common.schemas.characters` (once it
// exists there). A 503 means Battle.net itself is down and the character was never stored; a 404 means Battle.net
// has never heard of that name and surname.

/** One `GET /api/characters/[?q=]` row, and the roster/summary half of `CharacterPage`. */
export type CharacterSummary = {
  slug: string;
  name: string;
  surname: string;
  level: number;
  class: CharClass | null;
  race: string | null;
  faction: string | null;
  guild_name: string | null;
  guild_slug: string | null;
  in_roster: boolean;
  guild_rank: number | null;
  rank_name: string | null;
  item_level: number | null;
  spec: string | null;
  achievement_points: number | null;
  honorable_kills: number | null;
  pvp_rank: number | null;
  last_login_at: string | null;
  profile_found: boolean;
  fetched_at: string | null;
};

/** One piece of gear on a `CharacterSheet`; `quality` colors it with the same `q-*` classes as `ItemQuality`. */
export type CharacterGearSlot = {
  slot: string;
  slot_name: string;
  item_id: number;
  name: string;
  quality: ItemQuality;
  item_level: number | null;
  enchantments: string[];
};

export type CharacterStat = { label: string; value: string };
export type CharacterTalent = { name: string; points: number };
export type CharacterProfession = { name: string; skill: number; max_skill: number; recipes: number };
export type CharacterReputation = { faction: string; standing: string; value: number; max: number };
export type CharacterAchievement = { id: number | null; name: string; completed_at: string };
/** One tamed pet on a hunter's `CharacterSheet`; empty for non-hunters. */
export type CharacterHunterPet = { name: string; level: number; creature: string; creature_id: number; active: boolean };

/** The Battle.net-fetched half of `CharacterPage`; `null` when `profile_found` is false. */
export type CharacterSheet = {
  gear: CharacterGearSlot[];
  stats: CharacterStat[];
  talents: CharacterTalent[];
  professions: CharacterProfession[];
  reputations: CharacterReputation[];
  recent_achievements: CharacterAchievement[];
  hunter_pets: CharacterHunterPet[];
  mounts: number;
  pets: number;
  toys: number;
  quests_completed: number | null;
};

/** `GET /api/characters/{slug}` (public): the roster summary plus the full sheet, or `sheet: null` when
 * Battle.net hasn't published this character's profile yet. */
export type CharacterPage = CharacterSummary & { sheet: CharacterSheet | null };

/** One name on a `HeroBoards` top-10 list. */
export type HeroBoardEntry = { slug: string; name: string; surname: string; class: CharClass | null; value: number };

/** `GET /api/characters/boards` (public): the guild's top 10 roster characters by item level, honorable kills,
 * PvP rank and achievement points. Any list may be empty. */
export type HeroBoards = {
  item_level: HeroBoardEntry[];
  honorable_kills: HeroBoardEntry[];
  pvp_rank: HeroBoardEntry[];
  achievement_points: HeroBoardEntry[];
};

/** One row of `GET /api/characters/milestones` (public): a roster character that reached level 40 or 60. */
export type CharacterMilestone = {
  id: string;
  slug: string;
  name: string;
  surname: string;
  class: CharClass | null;
  level: 40 | 60;
  reached_at: string;
  posted_at: string | null;
};

/** A roster character's rank for display: the addon-reported rank name when known, else "Guild Master" for rank 0
 * or "Rank N". Empty string for a character not currently in the roster (`guild_rank` is `null` then). */
export function rankLabel(guildRank: number | null, rankName: string | null): string {
  if (guildRank === null) {
    return "";
  }
  if (rankName) {
    return rankName;
  }
  return guildRank === 0 ? "Guild Master" : `Rank ${guildRank}`;
}

/** Plain-language relative time ("just now", "5 minutes ago", "3 days ago", "2 months ago"), for a character's
 * last login and similar timestamps the site shows informally rather than as an exact date. */
export function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const minute = 60_000;
  const hour = 3_600_000;
  const day = 86_400_000;
  if (ms < minute) {
    return "just now";
  }
  if (ms < hour) {
    const n = Math.max(1, Math.round(ms / minute));
    return `${n} minute${n === 1 ? "" : "s"} ago`;
  }
  if (ms < day) {
    const n = Math.round(ms / hour);
    return `${n} hour${n === 1 ? "" : "s"} ago`;
  }
  const days = Math.round(ms / day);
  if (days < 30) {
    return `${days} day${days === 1 ? "" : "s"} ago`;
  }
  if (days < 365) {
    const months = Math.round(days / 30);
    return `${months} month${months === 1 ? "" : "s"} ago`;
  }
  const years = Math.round(days / 365);
  return `${years} year${years === 1 ? "" : "s"} ago`;
}

// ——— Quests: GET /api/quests/areas[/{id}], GET /api/quests/{id}. Public, Battle.net-backed reference data;
// mirrors `sidequest_common.schemas.reference`. A 503 means Battle.net itself is down/unconfigured; a 404 means
// Battle.net has no such zone or quest.

export type QuestAreaSummary = { id: number; name: string };

export type QuestSummary = { id: number; title: string };

/** `GET /api/quests/areas/{id}` (public): a quest zone and the quests that take place there. 404 unknown zone. */
export type QuestArea = { id: number; name: string; quests: QuestSummary[] };

export type QuestRewardItem = { item_id: number; name: string };

export type QuestReputationReward = { faction: string; value: number };

/** What completing a quest gives; `money` is copper. */
export type QuestRewards = {
  experience: number | null;
  money: number | null;
  items: QuestRewardItem[];
  reputations: QuestReputationReward[];
};

/** `GET /api/quests/{id}` (public): a single quest. Description placeholders like `{class}` appear as Battle.net
 * sends them. 404 unknown quest. */
export type Quest = {
  id: number;
  title: string;
  description: string | null;
  area: string | null;
  category: string | null;
  type: string | null;
  min_level: number | null;
  max_level: number | null;
  is_repeatable: boolean;
  is_daily: boolean;
  is_weekly: boolean;
  rewards: QuestRewards;
};

// ——— Achievements: GET /api/achievements/categories[/{id}], GET /api/achievements/{id}. Public, Battle.net-backed
// reference data; mirrors `sidequest_common.schemas.reference`.

export type AchievementCategorySummary = { id: number; name: string };

/** One root category of `GET /api/achievements/categories` (public), with its subcategories. */
export type AchievementCategoryTree = { id: number; name: string; children: AchievementCategorySummary[] };

export type AchievementSummary = { id: number; name: string; points: number; icon_url: string | null };

/** `GET /api/achievements/categories/{id}` (public): a category and the achievements in it. 404 unknown category. */
export type AchievementCategory = { id: number; name: string; achievements: AchievementSummary[] };

/** One condition (or branch of conditions) that completes an achievement. */
export type AchievementCriterion = { description: string | null; amount: number; children: AchievementCriterion[] };

/** `GET /api/achievements/{id}` (public): a single achievement. 404 unknown achievement. */
export type Achievement = {
  id: number;
  name: string;
  description: string;
  points: number;
  icon_url: string | null;
  category: string | null;
  reward_description: string | null;
  criteria: AchievementCriterion;
};

// ——— Item wishlist: GET/PUT/DELETE /api/me/wishlist[/{item_id}], GET /api/items/{item_id}/wishers (officer). A
// wish never changes the loot rules or the SQL addon; it only lets officers see who wants an item next.

/** One row of `GET/PUT /api/me/wishlist[/{item_id}]`, newest first: the signed-in member's own wishlist. */
export type ItemWish = {
  item_id: number;
  name: string;
  quality: ItemQuality;
  inventory_type_name: string;
  note: string | null;
  added_at: string;
};

/** `PUT /api/me/wishlist/{item_id}` body: adds the item, or changes the note if it's already on the list. */
export type ItemWishUpdate = { note?: string | null };

/** One row of `GET /api/items/{item_id}/wishers` (officer only), highest priority first. `ep`/`gp` are after
 * decay; `pr` is `ep / gp`. */
export type ItemWisher = {
  member_id: number;
  member_name: string;
  note: string | null;
  added_at: string;
  ep: number;
  gp: number;
  pr: number;
  trial: boolean;
};

// ——— Auction house prices: GET /api/auctions/prices/{item_id}[?ids=] (public), GET/POST/DELETE
// /api/me/auction-watches (member). Mirrors sidequest_common.schemas.auctions. Money is copper; format it with
// copperToGold, parse user input with parseGoldInput.

export const MAX_AUCTION_WATCHES = 25;
export const MAX_PRICE_IDS = 200;
export const AUCTION_TREND_DAYS = 14;

/** One house's current price for an item, on `ItemAuctionPrice.houses`. */
export type AuctionHousePrice = {
  house_id: number;
  house_name: string;
  unit_price: number;
  quantity: number;
  listings: number;
  updated_at: string;
};

/** One day's lowest price on `ItemAuctionPrice.trend`, oldest first, last `AUCTION_TREND_DAYS` days. */
export type AuctionTrendPoint = { day: string; unit_price: number };

/** `GET /api/auctions/prices/{item_id}` (public): the lowest price across the guild's faction houses, every
 * house's own price, and the recent trend. `unit_price` is null when nobody lists it (still a 200). */
export type ItemAuctionPrice = {
  item_id: number;
  unit_price: number | null;
  quantity_total: number;
  houses: AuctionHousePrice[];
  trend: AuctionTrendPoint[];
  updated_at: string | null;
};

/** One entry of `GET /api/auctions/prices?ids=`, in request order. */
export type ItemPriceSummary = {
  item_id: number;
  unit_price: number | null;
  quantity_total: number;
  updated_at: string | null;
};

export type AuctionPriceMap = { prices: ItemPriceSummary[] };

/** One row of `GET /api/me/auction-watches`: a "tell me when it drops below" alert on an item. */
export type AuctionWatch = {
  id: string;
  item_id: number;
  item_name: string | null;
  icon_url: string | null;
  max_unit_price: number;
  current_unit_price: number | null;
  created_at: string;
  last_alerted_at: string | null;
};

/** `POST /api/me/auction-watches` body: upserts by `item_id`. */
export type AuctionWatchCreate = { item_id: number; max_unit_price: number };

/** `GET /api/auctions/prices?ids=1,2,3` for up to `MAX_PRICE_IDS` item ids at once, deduped; returns an empty map
 * without a request for an empty list. Used by the wishlist, recipe crafting cost and guild market panels. */
export async function fetchAuctionPrices(
  itemIds: number[],
  init?: RequestInit,
): Promise<Map<number, ItemPriceSummary>> {
  const ids = [...new Set(itemIds)].slice(0, MAX_PRICE_IDS);
  if (ids.length === 0) {
    return new Map();
  }
  const { prices } = await apiFetch<AuctionPriceMap>(`/api/auctions/prices?ids=${ids.join(",")}`, init);
  return new Map(prices.map((price) => [price.item_id, price]));
}

/** Parses a "1g 20s 5c" style price (any subset, with or without spaces, e.g. "1g20s" or "500c") into copper, the
 * reverse of `copperToGold`. Returns null for empty, malformed, zero or out-of-range (silver/bronze over 99) input. */
export function parseGoldInput(input: string): number | null {
  const trimmed = input.trim().toLowerCase();
  if (!trimmed) {
    return null;
  }
  const match = /^(?:(\d+)\s*g)?\s*(?:(\d+)\s*s)?\s*(?:(\d+)\s*c)?$/.exec(trimmed);
  if (!match || (!match[1] && !match[2] && !match[3])) {
    return null;
  }
  const gold = Number(match[1] ?? 0);
  const silver = Number(match[2] ?? 0);
  const bronze = Number(match[3] ?? 0);
  if (silver > 99 || bronze > 99) {
    return null;
  }
  const copper = gold * 10000 + silver * 100 + bronze;
  return copper > 0 ? copper : null;
}

// ——— Talent calculator: GET /api/talents/{class}, GET/POST/DELETE /api/me/talent-builds[/{id}], GET
// /api/talent-builds?class=, PUT /api/talent-builds/{id}/pin (officer). A build's `code` holds one digit per
// talent node (its spent rank), node order sorted by (row, col) within each tree, the three trees joined by `-`.

export const MAX_TALENT_POINTS = 51;
export const FIRST_TALENT_LEVEL = 10;

export type TalentRank = { spell_id: number; description: string };

/** One node in a talent tree, positioned on its (row, col) grid. `requires` is a prerequisite node id, or null. */
export type TalentNode = {
  id: number;
  row: number;
  col: number;
  max_rank: number;
  talent_id: number;
  name: string;
  ranks: TalentRank[];
  requires: number | null;
};

export type TalentTree = { spec_id: number; name: string; icon_url: string | null; nodes: TalentNode[] };

/** `GET /api/talents/{class}`: a class's three specialization trees, in spec order. */
export type ClassTalents = { class: CharClass; trees: TalentTree[]; max_points: number; first_level: number };

/** Body for `POST /api/me/talent-builds`. */
export type TalentBuildCreate = { class: CharClass; name: string; code: string; note?: string | null };

/** One saved talent build, from `GET /api/me/talent-builds` or `GET /api/talent-builds?class=`. */
export type TalentBuild = {
  id: string;
  class: CharClass;
  name: string;
  code: string;
  note: string | null;
  pinned: boolean;
  member_id: number;
  member_name: string;
  created_at: string;
};

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
  slug: string | null;
  battlenet: CharacterSummary | null;
};

export type EpgpRecruits = { recruits: EpgpRecruit[] };

export type EpgpRecruitUpdate = {
  status?: EpgpRecruitStatus;
  note?: string;
  checklist?: EpgpRecruitChecklist;
  slug?: string | null;
};

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

// ——— PvP: GET /api/pvp/matches[?page=], GET /api/pvp/matches/{id}, GET /api/pvp/boards. Members only. Mirrors
// `sidequest_common.schemas.pvp`; built from the addon's recorded battleground scoreboards.

export type BattlegroundFaction = "alliance" | "horde";
export type BattlegroundWinner = "alliance" | "horde" | "draw";

/** One scoreboard row on a match's full detail. `guild_member` is true for a SideQuest character; `character_slug`
 * links to its character page when known. */
export type PvpPlayerRow = {
  name: string;
  faction: BattlegroundFaction;
  race: string | null;
  class: CharClass | null;
  killing_blows: number;
  honorable_kills: number;
  deaths: number;
  honor_gained: number;
  damage_done: number;
  healing_done: number;
  guild_member: boolean;
  character_slug: string | null;
};

/** One battleground in the match history. `won` is null when the winner is unknown or a draw. */
export type PvpMatchSummary = {
  id: string;
  map: string;
  ended_at: string;
  duration: number;
  winner: BattlegroundWinner | null;
  guild_faction: BattlegroundFaction;
  won: boolean | null;
  guild_players: string[];
  recorded_by: string;
};

/** `GET /api/pvp/matches/{id}` (member). 404 unknown match. Players are sorted highest honorable kills first. */
export type PvpMatchDetail = PvpMatchSummary & { players: PvpPlayerRow[] };

/** `GET /api/pvp/matches?page=` (member): newest first, 25 matches a page. */
export type PvpMatchPage = { page: number; page_count: number; matches: PvpMatchSummary[] };

/** One name on a `PvpBoards` top-10 list. */
export type PvpBoardEntry = { name: string; class: CharClass | null; character_slug: string | null; value: number };

/** `GET /api/pvp/boards` (member): totals over every recorded battleground for SideQuest characters, ten to a
 * board. Any list may be empty. */
export type PvpBoards = {
  matches: number;
  wins: PvpBoardEntry[];
  honorable_kills: PvpBoardEntry[];
  killing_blows: PvpBoardEntry[];
  honor_gained: PvpBoardEntry[];
  damage_done: PvpBoardEntry[];
  healing_done: PvpBoardEntry[];
};

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

/** Formats copper into `"Ng Ns Nc"`, used by the guild bank/market and item sell prices. */
export function copperToGold(copper: number): string {
  const sign = copper < 0 ? "-" : "";
  const abs = Math.abs(copper);
  const gold = Math.floor(abs / 10000);
  const silver = Math.floor((abs % 10000) / 100);
  const bronze = abs % 100;
  return `${sign}${gold}g ${silver}s ${bronze}c`;
}

/** Looks up a required element by id, throwing early with a clear message if the markup drifts. */
export function requireElement<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) {
    throw new Error(`Missing #${id} in page markup`);
  }
  return node as T;
}
