// Fixture data for the mocked API, typed against the site's own response shapes (src/scripts/api.ts) so a schema
// change that the pages depend on breaks the build here too. Times are relative to now so "upcoming" stays upcoming.
import type {
  Addon,
  AttendanceDetail,
  AttendanceEventSummary,
  AttendanceReport,
  AttendanceSignup,
  AttendanceTrends,
  CharacterPage,
  CharacterSummary,
  DiscordLive,
  DiscordOnline,
  EarnedBadge,
  EpgpCharacter,
  EpgpDeviceAuthorizationStatus,
  EpgpImportResult,
  EpgpLootItem,
  EpgpMemberNote,
  EpgpProgressionInstance,
  EpgpRecruit,
  EpgpRosterMember,
  EpgpRules,
  EpgpStandingRow,
  EpgpSyncToken,
  EventDetail,
  EventSummary,
  GmMember,
  GmMemberDetail,
  GroupLeaderboard,
  GroupSessionDetail,
  GroupSessionSummary,
  GroupStats,
  GuildAnnouncement,
  GuildBankRow,
  GuildCrafterProfession,
  GuildCrafterResult,
  GuildDirectory,
  GuildMarket,
  GuildNewsItem,
  GuildRoster,
  GuildStats,
  HeroActivity,
  HeroBoards,
  HeroDay,
  HeroLeaderboard,
  HeroProfile,
  HeroRow,
  Item,
  ItemSearch,
  ItemWisher,
  McpToken,
  Me,
  Recruiting,
  Signup,
  StatsPerson,
} from "../src/scripts/api";

const inDays = (days: number, hour = 20): string => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  date.setHours(hour, 0, 0, 0);
  return date.toISOString();
};

export const MEMBER: Me = {
  id: 7,
  discord_id: "700000000000000007",
  username: "wanderer",
  display_name: "Wanderer",
  avatar_url: null,
  is_guild_member: true,
  is_officer: false,
  is_gm: false,
  battletag: "Wanderer#1234",
  roster_confirmed: true,
};

export const OFFICER: Me = { ...MEMBER, id: 4, username: "guide", display_name: "Quest Guide", is_officer: true };
export const GM: Me = { ...OFFICER, id: 1, username: "master", display_name: "Quest Master", is_gm: true };

const counts = { tank: 2, healer: 3, dps: 9, signed: 14, tentative: 1, absent: 0, interested: 4 };

// The longest title the site has to fit on a phone; the event page uses it.
export const LONG_TITLE = "Molten Core: Ragnaros, Majordomo Executus and the whole Firelord's court";

export const EVENTS: EventSummary[] = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    kind: "raid",
    title: LONG_TITLE,
    location: "Molten Core",
    starts_at: inDays(2),
    ends_at: inDays(2, 23),
    size: 40,
    ep: 10,
    ep_override: null,
    status: "scheduled",
    notes:
      "Bring fire resistance. Invites at 7:45, pull at 8. https://example.com/a/very/long/link/to/a/raid/guide/that/must/wrap",
    counts,
    series: null,
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    kind: "dungeon",
    title: "Deadmines Run",
    location: "The Deadmines",
    starts_at: inDays(1, 19),
    ends_at: null,
    size: 5,
    ep: 5,
    ep_override: null,
    status: "scheduled",
    notes: null,
    counts: { ...counts, tank: 1, healer: 1, dps: 2, signed: 4, interested: 0 },
    series: null,
  },
  {
    id: "33333333-3333-4333-8333-333333333333",
    kind: "social",
    title: "Movie Night",
    location: "",
    starts_at: inDays(-3),
    ends_at: null,
    size: null,
    ep: 2,
    ep_override: null,
    status: "completed",
    notes: null,
    counts: { ...counts, signed: 6, tank: 0, healer: 0, dps: 0 },
    series: null,
  },
];

const signup = (id: string, name: string, overrides: Partial<Signup>): Signup => ({
  id,
  member: { display_name: name, avatar_url: null },
  character: name,
  class: "warrior",
  role: "dps",
  status: "signed",
  comment: null,
  group: null,
  bench: false,
  updated_at: inDays(-1),
  ...overrides,
});

export const SIGNUPS: Signup[] = [
  signup("s1", "Brannoc", {
    class: "warrior",
    role: "tank",
    group: 1,
    readiness: { slug: "brannoc-anvilheart", level: 60, item_level: 54, spec: "Protection", below_minimum: true },
  }),
  signup("s2", "Elowen", {
    class: "priest",
    role: "healer",
    group: 1,
    readiness: { slug: "elowen-dawnsworn", level: 60, item_level: 60, spec: "Holy", below_minimum: false },
  }),
  signup("s3", "Thistlewhit", {
    class: "mage",
    role: "dps",
    group: 2,
    readiness: { slug: "thistlewhit-sparkwhistle", level: 58, item_level: null, spec: null, below_minimum: false },
  }),
  signup("s4", "Kaelthasmaybe", { class: "shaman", role: "healer", status: "tentative" }),
  signup("s5", "Grimbold", { class: "hunter", role: "dps", bench: true }),
];

/** The raid chart's officer-set gear floor (PUT /api/raid-readiness); matches SIGNUPS' `below_minimum` values. */
export const MIN_ITEM_LEVEL = 58;

export function eventDetail(event: EventSummary, minItemLevel: number | null = MIN_ITEM_LEVEL): EventDetail {
  return {
    ...event,
    signups: SIGNUPS,
    my_signup: null,
    discord_interest: { count: 4, members: [] },
    away: [{ display_name: "Kaelthasmaybe", avatar_url: null }],
    min_item_level: minItemLevel,
  };
}

export const ADDONS: Addon[] = [
  {
    id: "a1",
    slug: "questie",
    name: "Questie",
    summary: "Quest helper.",
    version: "9.0",
    download_url: "https://example.com/questie.zip",
    homepage_url: "https://example.com/questie",
    origin: "community",
    updated_at: inDays(-10),
  },
  {
    id: "a2",
    slug: "sidequest-raid-helper",
    name: "SideQuest Raid Helper",
    summary: "Raid frames that know the plan.",
    version: "1.0.0",
    download_url: "https://example.com/sq.zip",
    homepage_url: null,
    origin: "guild",
    updated_at: inDays(-2),
  },
];

export const LIVE: DiscordLive = {
  online: 6,
  members: 41,
  voice: [
    { name: "Lobby", count: 3 },
    { name: "raid-1", count: 12 },
  ],
  reported_at: new Date().toISOString(),
};

export const ONLINE: DiscordOnline = {
  presence_count: 6,
  ok: true,
  members: [
    { name: "Wanderer", status: "online", avatar_url: null, activity: "World of Warcraft: Forever" },
    { name: "Quest Guide", status: "online", avatar_url: null, activity: null },
    { name: "Quest Master", status: "idle", avatar_url: null, activity: null },
    { name: "Lantern", status: "dnd", avatar_url: null, activity: "Raiding" },
    // Long single-word names side by side used to spill into each other; the last is Discord's 32-character max.
    { name: "Neonmancy", status: "online", avatar_url: null, activity: null },
    { name: "Norris", status: "online", avatar_url: null, activity: null },
    { name: "Thunderfuryblessedbladeofthewind", status: "online", avatar_url: null, activity: null },
  ],
};

export const RECRUITING: Recruiting = { roles: [], classes: [], updated_at: null };

export const GM_MEMBERS: GmMember[] = [MEMBER, OFFICER, GM].map((me) => ({
  id: me.id,
  discord_id: me.discord_id,
  username: me.username,
  display_name: me.display_name,
  avatar_url: null,
  roles: [{ id: "r1", name: me.is_gm ? "Quest Master" : "New Arrival", color: "#d8ab5c" }],
  is_guild_member: true,
  is_officer: me.is_officer,
  is_gm: me.is_gm,
  roster_confirmed_at: inDays(-5),
  battletag: me.battletag,
  battlenet_linked_at: inDays(-5),
  first_seen_at: inDays(-6),
  last_login_at: inDays(0, 9),
  signup_count: 3,
  case_count: 0,
  level: 5,
}));

export function gmMemberDetail(member: GmMember): GmMemberDetail {
  return { member, signups: [], cases: [], xp: 1200, message_count: 340 };
}

export const ATTENDANCE_EVENTS: AttendanceEventSummary[] = [
  {
    id: EVENTS[2].id,
    title: EVENTS[2].title,
    kind: EVENTS[2].kind,
    starts_at: EVENTS[2].starts_at,
    status: EVENTS[2].status,
    attendance_taken_at: null,
    needs_attendance: true,
  },
];

const attendanceSignup = (name: string, overrides: Partial<AttendanceSignup> = {}): AttendanceSignup => ({
  signup_id: `att-${name}`,
  member_id: 7,
  display_name: name,
  avatar_url: null,
  character: null,
  class: null,
  role: null,
  status: "signed",
  attended: null,
  is_walk_in: false,
  voice_minutes: 0,
  suggested_attended: true,
  ...overrides,
});

export function attendanceDetail(event: AttendanceEventSummary): AttendanceDetail {
  return {
    event,
    signups: [attendanceSignup("Wanderer", { member_id: MEMBER.id, voice_minutes: 42 })],
    walk_in_candidates: [{ member_id: OFFICER.id, display_name: OFFICER.display_name, avatar_url: null }],
  };
}

export const ATTENDANCE_REPORT: AttendanceReport = {
  range: "last_30",
  raids_only: false,
  rows: [
    {
      member_id: MEMBER.id,
      display_name: MEMBER.display_name,
      avatar_url: null,
      signed_up: 4,
      came: 3,
      no_shows: 1,
      walk_ins: 0,
      attendance_rate: 0.75,
      last_attended: inDays(-3),
    },
  ],
};

export const ATTENDANCE_TRENDS: AttendanceTrends = {
  range: "season",
  raids_only: false,
  points: [{ week_start: new Date().toISOString().slice(0, 10), attendees: 3, signed_up: 4, show_rate: 0.75 }],
};

export const HEROES: HeroRow[] = [
  {
    rank: 1,
    member_id: GM.id,
    discord_id: GM.discord_id,
    display_name: GM.display_name,
    avatar_url: null,
    wow_class: "paladin",
    chat_level: 14,
    ep: 240,
    raids_attended: 18,
    events_attended: 22,
    badge_ids: ["first_steps", "first_raid", "raid_veteran", "founding_member"],
  },
  {
    rank: 2,
    member_id: OFFICER.id,
    discord_id: OFFICER.discord_id,
    display_name: OFFICER.display_name,
    avatar_url: null,
    wow_class: "priest",
    chat_level: 11,
    ep: 180,
    raids_attended: 12,
    events_attended: 15,
    badge_ids: ["first_steps", "first_raid", "raid_regular"],
  },
  {
    rank: 3,
    member_id: MEMBER.id,
    discord_id: MEMBER.discord_id,
    display_name: MEMBER.display_name,
    avatar_url: null,
    wow_class: "warrior",
    chat_level: 6,
    ep: 60,
    raids_attended: 4,
    events_attended: 6,
    badge_ids: ["first_steps"],
  },
];

export function heroLeaderboard(season: string): HeroLeaderboard {
  return {
    season_id: season === "season-one" ? "season-one" : season,
    season_name: season === "season-one" ? "Season One" : season === "month" ? "This month" : "All time",
    rows: HEROES,
  };
}

const badge = (id: string, name: string, description: string, icon: string, daysAgo: number): EarnedBadge => ({
  id,
  name,
  description,
  icon,
  earned_at: inDays(-daysAgo),
});

export function heroProfile(row: HeroRow): HeroProfile {
  const stats = {
    ep: row.ep,
    raids_attended: row.raids_attended,
    events_attended: row.events_attended,
    attendance_rate: 0.8,
  };
  return {
    member_id: row.member_id,
    discord_id: row.discord_id,
    display_name: row.display_name,
    avatar_url: row.avatar_url,
    wow_class: row.wow_class,
    rank: row.rank,
    chat_level: row.chat_level,
    chat_xp: row.chat_level * 1000 + 250,
    chat_xp_into_level: 250,
    chat_xp_for_next_level: 1000,
    seasons: { "season-one": stats },
    all_time: stats,
    first_event_date: inDays(-90).slice(0, 10),
    recent_events: [
      { id: EVENTS[0]!.id, kind: EVENTS[0]!.kind, title: EVENTS[0]!.title, starts_at: EVENTS[0]!.starts_at, ep: 10 },
      { id: EVENTS[1]!.id, kind: EVENTS[1]!.kind, title: EVENTS[1]!.title, starts_at: EVENTS[1]!.starts_at, ep: 5 },
    ],
    badges: [badge("first_steps", "First Steps", "Attended their first guild event.", "👣", 60)],
  };
}

export function heroActivity(row: HeroRow): HeroActivity {
  const days: HeroDay[] = Array.from({ length: 30 }, (_, i) => ({
    day: inDays(-(29 - i)).slice(0, 10),
    messages: 5 + ((i * 3) % 12),
    voice_minutes: (i % 4) * 15,
  }));
  return {
    member_id: row.member_id,
    level: row.chat_level,
    xp: row.chat_level * 1000 + 250,
    xp_into_level: 250,
    xp_for_next_level: 1000,
    xp_rank: row.rank,
    ranked_members: HEROES.length,
    next_reward: { level: row.chat_level + 5, role_name: "Chatterbox" },
    message_count: 480,
    voice_minutes: 2100,
    events_attended: row.events_attended,
    groups_joined: 12,
    messages_30d: 140,
    voice_minutes_30d: 360,
    chat_rank_30d: row.rank,
    voice_rank_30d: row.rank,
    current_streak_days: 4,
    longest_streak_days: 11,
    xp_sources: { chat: 1200, voice: 900, events: row.events_attended * 50, groups: 300, earlier: 150 },
    days,
    heatmap: [
      { weekday: 4, hour: 20, messages: 12, voice_minutes: 45 },
      { weekday: 5, hour: 21, messages: 8, voice_minutes: 30 },
    ],
    tracking_since: inDays(-60),
  };
}

// ——— Server stats (officer /officers/#statistics and hero profiles) ———
const statsPerson = (discord: Me, memberId: number | null = null): StatsPerson => ({
  discord_id: discord.discord_id,
  display_name: discord.display_name,
  avatar_url: null,
  member_id: memberId,
});

export const GUILD_STATS: GuildStats = {
  range: "30d",
  since: inDays(-30).slice(0, 10),
  tracking_since: inDays(-60).slice(0, 10),
  totals: {
    active_members: 3,
    messages: 820,
    voice_minutes: 2400,
    events_attended: 18,
    groups_joined: 14,
    xp_gained: 3200,
  },
  previous: {
    active_members: 2,
    messages: 650,
    voice_minutes: 2000,
    events_attended: 14,
    groups_joined: 9,
    xp_gained: 2600,
  },
  trend_bucket: "day",
  trend: Array.from({ length: 7 }, (_, i) => ({
    start: inDays(-(6 - i)).slice(0, 10),
    messages: 80 + i * 10,
    voice_minutes: 200 + i * 20,
    active_members: 2 + (i % 2),
  })),
  heatmap: [
    { weekday: 4, hour: 20, messages: 60, voice_minutes: 180 },
    { weekday: 5, hour: 21, messages: 40, voice_minutes: 120 },
    { weekday: 6, hour: 15, messages: 10, voice_minutes: 30 },
  ],
  top_chatters: [
    { person: statsPerson(GM, GM.id), value: 240 },
    { person: statsPerson(OFFICER, OFFICER.id), value: 180 },
  ],
  top_voice: [{ person: statsPerson(GM, GM.id), value: 600 }],
  top_events: [{ person: statsPerson(GM, GM.id), value: 18 }],
  top_groups: [{ person: statsPerson(OFFICER, OFFICER.id), value: 7 }],
  top_xp: [{ person: statsPerson(GM, GM.id), value: 1200 }],
  gone_quiet: [{ person: statsPerson(MEMBER, MEMBER.id), last_active_at: inDays(-35), level: 6 }],
};

// ——— Group voice channel fixtures (#lfg) ———
export const GROUP_STATS: GroupStats = {
  days: 30,
  sessions_total: 14,
  sessions_counted: 9,
  grouped_minutes: 540,
  by_kind: [
    { kind: "dungeon", sessions: 5, minutes: 220 },
    { kind: "raid", sessions: 2, minutes: 180 },
    { kind: "world_boss", sessions: 1, minutes: 40 },
    { kind: "social", sessions: 1, minutes: 100 },
  ],
  top_instances: [
    { kind: "dungeon", name: "Deadmines", sessions: 3 },
    { kind: "raid", name: "Molten Core", sessions: 2 },
  ],
  most_grouped: [
    { person: { discord_id: GM.discord_id, display_name: GM.display_name, member_id: GM.id }, value: 240, sessions: 7 },
    {
      person: { discord_id: OFFICER.discord_id, display_name: OFFICER.display_name, member_id: OFFICER.id },
      value: 180,
      sessions: 5,
    },
  ],
  most_social: [
    {
      person: { discord_id: MEMBER.discord_id, display_name: MEMBER.display_name, member_id: MEMBER.id },
      value: 4,
      sessions: 6,
    },
  ],
  best_duos: [
    {
      a: { discord_id: GM.discord_id, display_name: GM.display_name, member_id: GM.id },
      b: { discord_id: OFFICER.discord_id, display_name: OFFICER.display_name, member_id: OFFICER.id },
      minutes: 160,
      sessions: 4,
    },
  ],
  most_led: [
    { person: { discord_id: GM.discord_id, display_name: GM.display_name, member_id: GM.id }, value: 6, sessions: 6 },
  ],
  busy_hours: [
    { weekday: 4, hour: 20, sessions: 5 },
    { weekday: 5, hour: 21, sessions: 3 },
    { weekday: 6, hour: 15, sessions: 1 },
  ],
};

export const GROUP_SESSIONS: GroupSessionSummary[] = [
  {
    id: "aaaaaaaa-1111-4111-8111-111111111111",
    kind: "dungeon",
    name: "Deadmines",
    channel_name: "dungeon-deadmines",
    creator: { discord_id: GM.discord_id, display_name: GM.display_name, member_id: GM.id },
    event_id: null,
    started_at: inDays(-2, 19),
    ended_at: inDays(-2, 20),
    end_reason: "owner",
    peak_size: 5,
    grouped_minutes: 45,
    counted: true,
    has_transcript: true,
  },
  {
    id: "aaaaaaaa-2222-4111-8111-111111111111",
    kind: "raid",
    name: null,
    channel_name: "raid-3",
    creator: { discord_id: OFFICER.discord_id, display_name: OFFICER.display_name, member_id: OFFICER.id },
    event_id: null,
    started_at: inDays(-5, 20),
    ended_at: inDays(-5, 22),
    end_reason: "empty",
    peak_size: 18,
    grouped_minutes: 110,
    counted: true,
    has_transcript: true,
  },
  {
    id: "aaaaaaaa-3333-4111-8111-111111111111",
    kind: "social",
    name: null,
    channel_name: "hangout-1",
    creator: { discord_id: MEMBER.discord_id, display_name: MEMBER.display_name, member_id: MEMBER.id },
    event_id: null,
    started_at: inDays(-1, 18),
    ended_at: null,
    end_reason: null,
    peak_size: 2,
    grouped_minutes: 5,
    counted: false,
    has_transcript: false,
  },
];

export function groupSessionDetail(session: GroupSessionSummary): GroupSessionDetail {
  return {
    ...session,
    note: session.kind === "dungeon" ? "Need one more for the last boss" : null,
    needs: session.kind === "dungeon" ? ["healer"] : [],
    members: [
      { person: session.creator, value: session.grouped_minutes, sessions: 1 },
      {
        person: { discord_id: MEMBER.discord_id, display_name: MEMBER.display_name, member_id: MEMBER.id },
        value: 30,
        sessions: 1,
      },
    ],
    transcript: session.has_transcript
      ? [
          {
            author_discord_id: session.creator.discord_id,
            author_name: session.creator.display_name,
            content: "Ready when you are",
            created_at: session.started_at,
            attachments: [],
          },
        ]
      : null,
    transcript_expires_at: session.has_transcript ? inDays(28) : null,
  };
}

export const GROUP_LEADERBOARD: GroupLeaderboard = {
  month: [
    { member_id: GM.id, display_name: GM.display_name, groups: 7, minutes: 240 },
    { member_id: OFFICER.id, display_name: OFFICER.display_name, groups: 5, minutes: 180 },
  ],
  all_time: [
    { member_id: GM.id, display_name: GM.display_name, groups: 40, minutes: 1800 },
    { member_id: OFFICER.id, display_name: OFFICER.display_name, groups: 22, minutes: 900 },
    { member_id: MEMBER.id, display_name: MEMBER.display_name, groups: 6, minutes: 150 },
  ],
};

// ——— EPGP loot system fixtures ———
export const EPGP_RULES: EpgpRules = {
  ep: { boss_kill: 10, progress: 10, on_time: 5, full_night: 5 },
  gp: {
    INVTYPE_HEAD: 100,
    INVTYPE_CHEST: 100,
    INVTYPE_LEGS: 100,
    INVTYPE_SHOULDER: 75,
    INVTYPE_HAND: 75,
    INVTYPE_WAIST: 75,
    INVTYPE_FEET: 75,
    INVTYPE_NECK: 55,
    INVTYPE_WRIST: 55,
    INVTYPE_CLOAK: 55,
    INVTYPE_FINGER: 55,
    INVTYPE_TRINKET: 125,
    INVTYPE_WEAPON: 150,
    INVTYPE_2HWEAPON: 200,
    INVTYPE_RANGED: 50,
  },
  chase_multiplier: 1.5,
  legendary_gp: 300,
  os_percent: 10,
  base_gp: 100,
  min_gp: 100,
  decay_percent: 15,
  trial_days: 14,
};

export const EPGP_STANDINGS: EpgpStandingRow[] = [
  {
    member_id: 4,
    name: "Quest Guide",
    main: "Guideline-Whitemane",
    class: "PALADIN",
    characters: ["Guideline-Whitemane"],
    ep: 185.2,
    gp: 320.5,
    pr: 0.578,
    trial: false,
  },
  {
    member_id: 7,
    name: "Wanderer",
    main: "Wanderer-Whitemane",
    class: "HUNTER",
    characters: ["Wanderer-Whitemane", "Wanderalt-Whitemane"],
    ep: 120.0,
    gp: 150.0,
    pr: 0.8,
    trial: false,
  },
  {
    member_id: 9,
    name: "Freshface",
    main: "Freshface-Whitemane",
    class: "ROGUE",
    characters: ["Freshface-Whitemane"],
    ep: 25.0,
    gp: 100.0,
    pr: 0.25,
    trial: true,
  },
  {
    member_id: null,
    name: "Strayalt-Whitemane",
    main: null,
    class: "MAGE",
    characters: ["Strayalt-Whitemane"],
    ep: 10.0,
    gp: 100.0,
    pr: 0.1,
    trial: false,
  },
];

export const EPGP_LOOT: EpgpLootItem[] = [
  {
    id: "loot-1",
    at: inDays(-3),
    item_id: 30896,
    item_name: "Glory of the Defender",
    quality: 4,
    character: "Guideline-Whitemane",
    member_id: 4,
    member_name: "Quest Guide",
    response: "ms",
    gp: 100,
    instance_name: "Hyjal Summit",
    encounter_name: "Rage Winterchill",
    voided: false,
  },
  {
    id: "loot-2",
    at: inDays(-3),
    item_id: 29179,
    item_name: "Cloak of Autumn's Child",
    quality: 3,
    character: "Wanderer-Whitemane",
    member_id: 7,
    member_name: "Wanderer",
    response: "os",
    gp: 5,
    instance_name: "Hyjal Summit",
    encounter_name: "Rage Winterchill",
    voided: false,
  },
  {
    id: "loot-3",
    at: inDays(-10),
    item_id: 29176,
    item_name: "Signet of Unshakable Faith",
    quality: 2,
    character: "Freshface-Whitemane",
    member_id: 9,
    member_name: "Freshface",
    response: "de",
    gp: 0,
    instance_name: "Hyjal Summit",
    encounter_name: "Anetheron",
    voided: true,
  },
];

export const EPGP_PROGRESSION: EpgpProgressionInstance[] = [
  {
    instance_id: 534,
    name: "Hyjal Summit",
    size: 20,
    encounters: [
      {
        encounter_id: 620,
        name: "Rage Winterchill",
        first_kill_at: inDays(-10),
        kills: 2,
        wipes: 3,
        last_attempt_at: inDays(-3),
      },
      {
        encounter_id: 652,
        name: "Anetheron",
        first_kill_at: null,
        kills: 0,
        wipes: 5,
        last_attempt_at: inDays(-3),
      },
    ],
  },
];

export const EPGP_CHARACTERS: EpgpCharacter[] = [
  {
    id: "char-1",
    name: "Wanderer",
    realm: "Whitemane",
    class: "HUNTER",
    member_id: 7,
    member_name: "Wanderer",
    is_main: true,
    source: "claim",
    last_seen_at: inDays(-3),
  },
  {
    id: "char-2",
    name: "Strayalt",
    realm: "Whitemane",
    class: "MAGE",
    member_id: null,
    member_name: null,
    is_main: false,
    source: "import",
    last_seen_at: inDays(-3),
  },
];

export const EPGP_ROSTER: EpgpRosterMember[] = [
  { member_id: 4, name: "Quest Guide", raid_status: "raider", trial_started_at: null },
  { member_id: 7, name: "Wanderer", raid_status: "raider", trial_started_at: null },
  { member_id: 9, name: "Freshface", raid_status: "trial", trial_started_at: inDays(-5) },
];

export const EPGP_SYNC_TOKENS: EpgpSyncToken[] = [
  { id: "token-1", name: "Guide's laptop", created_at: inDays(-20), last_used_at: inDays(-2) },
];

export const MCP_TOKENS: McpToken[] = [
  { id: "mcp-token-1", name: "Guide's laptop", created_at: inDays(-10), last_used_at: inDays(-1) },
];

export const DEVICE_AUTH_USER_CODE = "ABCD-EFGH";

export const EPGP_DEVICE_AUTHORIZATION: EpgpDeviceAuthorizationStatus = {
  user_code: DEVICE_AUTH_USER_CODE,
  device_name: "Office PC",
  created_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 600_000).toISOString(),
  status: "pending",
};
export function epgpImportResult(): EpgpImportResult {
  return {
    recorder: "Guideline-Whitemane",
    sessions: { new: 1, updated: 0 },
    encounters: { new: 2, updated: 0 },
    loot: { new: 2, updated: 0, voided: 0 },
    awards: { new: 6, updated: 0, voided: 0 },
    unlinked_characters: ["Strayalt-Whitemane"],
    attendance: { event_id: EVENTS[0]!.id, marked: 18 },
    conflicts: [],
  };
}

// ——— Guild app v2 fixtures ———
export const GUILD_ROSTER: GuildRoster = {
  taken_at: inDays(0, 10),
  members: [
    {
      member_id: 4,
      name: "Quest Guide",
      rank: "Officer",
      raid_status: "raider",
      main: "Guideline-Whitemane",
      characters: [
        {
          name: "Guideline",
          class: "PALADIN",
          level: 60,
          zone: "Ironforge",
          last_seen_at: inDays(0, 9),
          is_main: true,
        },
        {
          name: "Guidealt",
          class: "ROGUE",
          level: 40,
          zone: "Stormwind City",
          last_seen_at: inDays(-2),
          is_main: false,
        },
      ],
    },
    {
      member_id: 7,
      name: "Wanderer",
      rank: "Member",
      raid_status: "raider",
      main: "Wanderer-Whitemane",
      characters: [
        {
          name: "Wanderer",
          class: "HUNTER",
          level: 60,
          zone: "Hyjal Summit",
          last_seen_at: inDays(0, 10),
          is_main: true,
        },
        { name: "Wanderalt", class: "MAGE", level: 22, zone: "Darnassus", last_seen_at: inDays(-5), is_main: false },
      ],
    },
    {
      member_id: 9,
      name: "Freshface",
      rank: "New Arrival",
      raid_status: "trial",
      main: "Freshface-Whitemane",
      characters: [
        { name: "Freshface", class: "ROGUE", level: 58, zone: "Orgrimmar", last_seen_at: inDays(-1), is_main: true },
      ],
    },
  ],
  unlinked: [{ name: "Driftwood", class: "WARLOCK", level: 35, rank: "Member", last_seen_at: inDays(-3) }],
};

const CRAFTER_RESULTS: GuildCrafterResult[] = [
  {
    recipe_id: 2662,
    recipe_name: "Copper Chain Pants",
    item_id: 2852,
    crafters: [
      {
        character: "Guideline-Whitemane",
        member_id: 4,
        member_name: "Quest Guide",
        profession: "Blacksmithing",
        skill: 150,
      },
    ],
  },
  {
    recipe_id: 3372,
    recipe_name: "Flask of the Titans",
    item_id: 13510,
    crafters: [
      { character: "Wanderalt-Whitemane", member_id: 7, member_name: "Wanderer", profession: "Alchemy", skill: 275 },
    ],
  },
];

const CRAFTER_PROFESSIONS: GuildCrafterProfession[] = [
  { profession: "Blacksmithing", crafters: 1 },
  { profession: "Alchemy", crafters: 1 },
];

export const GUILD_CRAFTERS = { results: CRAFTER_RESULTS, professions: CRAFTER_PROFESSIONS };

export const GUILD_DIRECTORY: GuildDirectory = {
  characters: [
    {
      character: "Guideline-Whitemane",
      member_id: 4,
      member_name: "Quest Guide",
      professions: [{ name: "Blacksmithing", skill: 150, max_skill: 300 }],
      level: 60,
      class: "PALADIN",
      race: "Human",
      spec: "Protection",
      item_level: 58.2,
      attunements: ["onyxia"],
      reputations: [{ faction_id: 529, standing: 6, value: 4200 }],
      cooldowns: [],
      freshness: { prof: inDays(-1), char: inDays(-1), cd: null, market: null, stock: null },
    },
  ],
};

export const GUILD_MARKET: GuildMarket = {
  sell: [
    {
      character: "Wanderalt-Whitemane",
      member_name: "Wanderer",
      item_id: 13510,
      item_name: "Flask of the Titans",
      price: 120000,
      qty: 3,
      crafted: true,
    },
  ],
  buy: [
    {
      character: "Guideline-Whitemane",
      member_name: "Quest Guide",
      item_id: 2852,
      item_name: "Heavy Grinding Stone",
      price: 500,
    },
  ],
  requests: [],
};

export const GUILD_NEWS: GuildNewsItem[] = [
  {
    id: "n-1",
    at: inDays(-1),
    kind: "boss_kill",
    text: "Rage Winterchill defeated (Hyjal Summit)",
    character: "Guideline-Whitemane",
    item_id: null,
    quality: null,
  },
  {
    id: "n-2",
    at: inDays(-2),
    kind: "announcement",
    text: "Flasks for Friday please",
    character: null,
    item_id: null,
    quality: null,
  },
];

export const GUILD_BANK: GuildBankRow[] = [
  {
    id: "bank-1",
    at: inDays(-1),
    character: "Guideline-Whitemane",
    member_name: "Quest Guide",
    kind: "deposit",
    item_id: 2589,
    item_name: "Linen Cloth",
    count: 20,
    money: 0,
    tab: 1,
  },
  {
    id: "bank-2",
    at: inDays(-3),
    character: "Wanderer-Whitemane",
    member_name: "Wanderer",
    kind: "withdraw_money",
    item_id: null,
    item_name: null,
    count: null,
    money: 50000,
    tab: null,
  },
];

export const GUILD_ANNOUNCEMENTS: GuildAnnouncement[] = [
  {
    id: "ann-1",
    text: "Flasks for Friday please",
    author: "Quest Guide",
    at: inDays(-2),
    source: "game",
    posted_at: inDays(-2),
  },
];

export const EPGP_RECRUITS: EpgpRecruit[] = [
  {
    id: "recruit-1",
    character: "Hopeful-Whitemane",
    class: "MAGE",
    status: "trial",
    note: "Found in LFG, geared well",
    member_id: null,
    checklist: { talked: true, gear_check: true, first_raid: false, vouched: false },
    votes: [{ officer: "Quest Guide", vote: "yes", at: inDays(-4) }],
    at: inDays(-5),
  },
];

export const EPGP_MEMBER_NOTES: Record<number, EpgpMemberNote[]> = {
  7: [
    {
      id: "note-1",
      character: "Wanderer",
      note: "Prefers healing",
      officer: "Quest Guide",
      at: inDays(-6),
      voided: false,
    },
  ],
};

// Item catalog (GET /api/items[?...], GET /api/items/{id}): reuses item_ids already seen on the ledger, guild
// bank and market fixtures above, so an item's own page agrees with where else the site shows it.
export const ITEMS: Item[] = [
  {
    item_id: 30896,
    name: "Glory of the Defender",
    quality: "EPIC",
    quality_name: "Epic",
    item_class: "Armor",
    item_subclass: "Miscellaneous",
    inventory_type: "TRINKET",
    inventory_type_name: "Trinket",
    item_level: 232,
    required_level: 80,
    sell_price: 150000,
    is_equippable: true,
    icon_url: null,
    tooltip: ["Binds when picked up", "Unique", "+96 Stamina", "+64 Critical Strike", "Requires Level 80"],
    loot_price: { main_spec: 125, off_spec: 13, chase: 188 },
  },
  {
    item_id: 29179,
    name: "Cloak of Autumn's Child",
    quality: "RARE",
    quality_name: "Rare",
    item_class: "Armor",
    item_subclass: "Cloth",
    inventory_type: "CLOAK",
    inventory_type_name: "Back",
    item_level: 141,
    required_level: 70,
    sell_price: 42000,
    is_equippable: true,
    icon_url: null,
    tooltip: ["Binds when picked up", "+22 Intellect", "+18 Spirit", "Requires Level 70"],
    loot_price: { main_spec: 55, off_spec: 6, chase: 83 },
  },
  {
    item_id: 29176,
    name: "Signet of Unshakable Faith",
    quality: "UNCOMMON",
    quality_name: "Uncommon",
    item_class: "Miscellaneous",
    item_subclass: "Junk",
    inventory_type: "FINGER",
    inventory_type_name: "Finger",
    item_level: 128,
    required_level: 68,
    sell_price: 18000,
    is_equippable: true,
    icon_url: null,
    tooltip: ["Binds when picked up", "Unique", "+14 Stamina", "Requires Level 68"],
    loot_price: { main_spec: 55, off_spec: 6, chase: 83 },
  },
  {
    item_id: 13510,
    name: "Flask of the Titans",
    quality: "UNCOMMON",
    quality_name: "Uncommon",
    item_class: "Consumable",
    item_subclass: "Flask",
    inventory_type: "",
    inventory_type_name: "",
    item_level: 60,
    required_level: 55,
    sell_price: 2500,
    is_equippable: false,
    icon_url: null,
    tooltip: ["Use: Increases total health by 2000 for 2 hours.", "Requires Level 55"],
    loot_price: null,
  },
  {
    item_id: 2852,
    name: "Heavy Grinding Stone",
    quality: "COMMON",
    quality_name: "Common",
    item_class: "Trade Goods",
    item_subclass: "Materials",
    inventory_type: "",
    inventory_type_name: "",
    item_level: 1,
    required_level: 0,
    sell_price: 150,
    is_equippable: false,
    icon_url: null,
    tooltip: ['"Used by blacksmiths to sharpen weapons."'],
    loot_price: null,
  },
  {
    item_id: 2589,
    name: "Linen Cloth",
    quality: "COMMON",
    quality_name: "Common",
    item_class: "Trade Goods",
    item_subclass: "Cloth",
    inventory_type: "",
    inventory_type_name: "",
    item_level: 1,
    required_level: 0,
    sell_price: 25,
    is_equippable: false,
    icon_url: null,
    tooltip: ['"Harvested from Linen Cloth bolts."'],
    loot_price: null,
  },
  {
    item_id: 19019,
    name: "Thunderfury, Blessed Blade of the Windseeker",
    quality: "LEGENDARY",
    quality_name: "Legendary",
    item_class: "Weapon",
    item_subclass: "Sword",
    inventory_type: "WEAPON",
    inventory_type_name: "One-Hand",
    item_level: 80,
    required_level: 60,
    sell_price: 500000,
    is_equippable: true,
    icon_url: null,
    tooltip: ["Binds when picked up", "Unique", "+10 Agility", "+10 Stamina", "Requires Level 60"],
    loot_price: { main_spec: 300, off_spec: 30, chase: 300 },
  },
];

export function itemSearch(items: Item[], page: number): ItemSearch {
  const perPage = 2;
  const start = (page - 1) * perPage;
  return {
    page,
    page_count: Math.max(1, Math.ceil(items.length / perPage)),
    results: items.slice(start, start + perPage).map((item) => ({
      item_id: item.item_id,
      name: item.name,
      quality: item.quality,
      quality_name: item.quality_name,
      inventory_type: item.inventory_type,
      inventory_type_name: item.inventory_type_name,
      item_level: item.item_level,
      required_level: item.required_level,
    })),
  };
}

// Item wishlist (GET/PUT/DELETE /api/me/wishlist[/{item_id}], GET /api/items/{item_id}/wishers): who wants
// ITEMS[0] (Glory of the Defender), highest priority first, reusing EPGP_STANDINGS' EP/GP so the numbers agree
// with the Ledger. The member's own wishlist starts empty; a test adds to it through the API.
export const ITEM_WISHERS: ItemWisher[] = [
  {
    member_id: 7,
    member_name: "Wanderer",
    note: "For my hunter off-spec",
    added_at: inDays(-2),
    ep: 120.0,
    gp: 150.0,
    pr: 0.8,
    trial: false,
  },
  {
    member_id: 9,
    member_name: "Freshface",
    note: null,
    added_at: inDays(-1),
    ep: 25.0,
    gp: 100.0,
    pr: 0.25,
    trial: true,
  },
];

// ——— Characters (GET /api/characters/[?q=], GET /api/characters/{slug}, GET /api/characters/boards) ———
// Two roster members (one with a published Battle.net profile, one without) and one non-roster character found
// only by exact name and surname, so a test can exercise all three states.
export const CHARACTERS: CharacterSummary[] = [
  {
    slug: "nox-zul",
    name: "Nox",
    surname: "Zul",
    level: 60,
    class: "warrior",
    race: "Human",
    faction: "Alliance",
    guild_name: "SideQuest",
    guild_slug: "sidequest",
    in_roster: true,
    guild_rank: 0,
    rank_name: "Guild Master",
    item_level: 272,
    spec: "Protection",
    achievement_points: 4820,
    honorable_kills: 312,
    pvp_rank: 6,
    last_login_at: inDays(-1),
    profile_found: true,
    fetched_at: inDays(-1),
  },
  {
    slug: "mira-ashbrook",
    name: "Mira",
    surname: "Ashbrook",
    level: 58,
    class: "priest",
    race: "Night Elf",
    faction: "Alliance",
    guild_name: "SideQuest",
    guild_slug: "sidequest",
    in_roster: true,
    guild_rank: 2,
    rank_name: "Raider",
    item_level: null,
    spec: null,
    achievement_points: null,
    honorable_kills: null,
    pvp_rank: null,
    last_login_at: null,
    profile_found: false,
    fetched_at: null,
  },
  {
    slug: "thal-windrunner",
    name: "Thal",
    surname: "Windrunner",
    level: 60,
    class: "hunter",
    race: "Dwarf",
    faction: "Alliance",
    guild_name: null,
    guild_slug: null,
    in_roster: false,
    guild_rank: null,
    rank_name: null,
    item_level: 265,
    spec: "Marksmanship",
    achievement_points: 3100,
    honorable_kills: 50,
    pvp_rank: 3,
    last_login_at: inDays(-5),
    profile_found: true,
    fetched_at: inDays(-5),
  },
];

function characterSheet(overrides: Partial<CharacterPage["sheet"]> = {}): NonNullable<CharacterPage["sheet"]> {
  return {
    gear: [
      {
        slot: "HEAD",
        slot_name: "Head",
        item_id: 1001,
        name: "Lionheart Helm",
        quality: "EPIC",
        item_level: 78,
        enchantments: [],
      },
      {
        slot: "CHEST",
        slot_name: "Chest",
        item_id: 1002,
        name: "Breastplate of Valor",
        quality: "RARE",
        item_level: 70,
        enchantments: ["+8 Stamina"],
      },
    ],
    stats: [
      { label: "Health", value: "4820" },
      { label: "Armor", value: "3120" },
      { label: "Strength", value: "210" },
    ],
    talents: [
      { name: "Protection", points: 31 },
      { name: "Arms", points: 15 },
    ],
    professions: [
      { name: "Blacksmithing", skill: 300, max_skill: 300, recipes: 48 },
      { name: "Mining", skill: 300, max_skill: 300, recipes: 0 },
    ],
    reputations: [
      { faction: "Ironforge", standing: "Exalted", value: 42000, max: 42000 },
      { faction: "Argent Dawn", standing: "Honored", value: 18000, max: 21000 },
    ],
    recent_achievements: [{ name: "Onyxia's Downfall", completed_at: inDays(-3) }],
    mounts: 12,
    pets: 5,
    toys: 3,
    quests_completed: 980,
    ...overrides,
  };
}

export const CHARACTER_PAGES: CharacterPage[] = [
  { ...CHARACTERS[0]!, sheet: characterSheet() },
  { ...CHARACTERS[1]!, sheet: null },
  {
    ...CHARACTERS[2]!,
    sheet: characterSheet({
      professions: [],
      reputations: [],
      recent_achievements: [],
      mounts: 2,
      pets: 0,
      toys: 0,
      quests_completed: null,
    }),
  },
];

// Honorable kills and PvP rank are left empty on purpose, to exercise a board's "No one yet" state.
export const HERO_BOARDS: HeroBoards = {
  item_level: CHARACTERS.filter((c) => c.in_roster && c.item_level !== null)
    .toSorted((a, b) => (b.item_level ?? 0) - (a.item_level ?? 0))
    .map((c) => ({ slug: c.slug, name: c.name, surname: c.surname, class: c.class, value: c.item_level ?? 0 })),
  honorable_kills: [],
  pvp_rank: [],
  achievement_points: CHARACTERS.filter((c) => c.in_roster && c.achievement_points !== null)
    .toSorted((a, b) => (b.achievement_points ?? 0) - (a.achievement_points ?? 0))
    .map((c) => ({ slug: c.slug, name: c.name, surname: c.surname, class: c.class, value: c.achievement_points ?? 0 })),
};
