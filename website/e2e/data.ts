// Fixture data for the mocked API, typed against the site's own response shapes (src/scripts/api.ts) so a schema
// change that the pages depend on breaks the build here too. Times are relative to now so "upcoming" stays upcoming.
import type {
  Achievement,
  AchievementCategory,
  AchievementCategoryTree,
  Addon,
  AttendanceDetail,
  AttendanceEventSummary,
  AttendanceReport,
  AttendanceSignup,
  AttendanceTrends,
  AuctionWatch,
  CharacterMilestone,
  CharacterPage,
  CharacterSummary,
  ClassTalents,
  DiscordLive,
  DiscordOnline,
  EarnedBadge,
  EpgpCharacter,
  EpgpDeviceAuthorizationStatus,
  EpgpImportResult,
  EpgpLedgerEntry,
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
  GameClass,
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
  GuildOfficer,
  GuildRoster,
  GuildStats,
  HeroActivity,
  HeroBoards,
  HeroDay,
  HeroLeaderboard,
  HeroProfile,
  HeroRow,
  Item,
  ItemAuctionPrice,
  ItemPriceSummary,
  ItemSearch,
  ItemWisher,
  McpToken,
  Me,
  Profession,
  ProfessionSkillTier,
  PvpBoards,
  PvpMatchDetail,
  PvpMatchPage,
  Quest,
  QuestArea,
  RecipeDetailInfo,
  Recruiting,
  Signup,
  StatsPerson,
  TalentBuild,
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
    category: "leveling",
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
    category: "raid_required",
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
  weekly_reset_weekday: 1,
  weekly_reset_hour_utc: 15,
};

export const EPGP_STANDINGS: EpgpStandingRow[] = [
  {
    member_id: 4,
    name: "Quest Guide",
    main: "Guideline-Whitemane",
    main_name: "Guideline Brightwater",
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
    main_name: "Wanderer Brightwater",
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
    main_name: "Freshface Brightwater",
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
    main_name: null,
    class: "MAGE",
    characters: ["Strayalt-Whitemane"],
    ep: 10.0,
    gp: 100.0,
    pr: 0.1,
    trial: false,
  },
  {
    // Rostered but hasn't raided yet: the "everyone listed" rule still shows them, at 0 EP and the GP floor.
    member_id: 11,
    name: "Rookie",
    main: "Rookie-Whitemane",
    main_name: "Rookie Brightwater",
    class: "WARRIOR",
    characters: ["Rookie-Whitemane"],
    ep: 0.0,
    gp: 100.0,
    pr: 0.0,
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
    council_reason: null,
    council_kind: null,
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
    council_reason: null,
    council_kind: null,
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
    council_reason: null,
    council_kind: null,
  },
  {
    id: "loot-4",
    at: inDays(-3),
    item_id: 19019,
    item_name: "Thunderfury",
    quality: 4,
    character: "Tank1-Whitemane",
    member_id: 4,
    member_name: "Quest Guide",
    response: "council",
    gp: 300,
    instance_name: "Hyjal Summit",
    encounter_name: "Rage Winterchill",
    voided: false,
    council_reason: "Only one in the raid with the quest chain started.",
    council_kind: "legendary",
  },
];

export const EPGP_LEDGER: EpgpLedgerEntry[] = [
  {
    id: "ledger-1",
    at: inDays(-3),
    kind: "ep",
    amount: 10,
    decayed: 10,
    reason: "boss_kill",
    note: null,
    character: "Guideline-Whitemane",
    member_id: 4,
    member_name: "Quest Guide",
    officer: "Officername-Whitemane",
    item_name: null,
    response: null,
    voided: false,
  },
  {
    id: "ledger-2",
    at: inDays(-3),
    kind: "ep",
    amount: 5,
    decayed: 5,
    reason: "on_time",
    note: null,
    character: "Guideline-Whitemane",
    member_id: 4,
    member_name: "Quest Guide",
    officer: "Officername-Whitemane",
    item_name: null,
    response: null,
    voided: false,
  },
  {
    id: "ledger-3",
    at: inDays(-3),
    kind: "gp",
    amount: 100,
    decayed: 100,
    reason: "loot",
    note: null,
    character: "Guideline-Whitemane",
    member_id: 4,
    member_name: "Quest Guide",
    officer: "Officername-Whitemane",
    item_name: "Glory of the Defender",
    response: "ms",
    voided: false,
  },
  {
    id: "ledger-4",
    at: inDays(-20),
    kind: "gp",
    amount: -50,
    decayed: -38.3,
    reason: "adjust",
    note: "Attendance credit",
    character: null,
    member_id: 4,
    member_name: "Quest Guide",
    officer: "Officername-Whitemane",
    item_name: null,
    response: null,
    voided: false,
  },
  {
    id: "ledger-5",
    at: inDays(-3),
    kind: "gp",
    amount: 5,
    decayed: 5,
    reason: "loot",
    note: null,
    character: "Wanderer-Whitemane",
    member_id: 7,
    member_name: "Wanderer",
    officer: "Officername-Whitemane",
    item_name: "Cloak of Autumn's Child",
    response: "os",
    voided: false,
  },
  {
    id: "ledger-6",
    at: inDays(-10),
    kind: "gp",
    amount: 0,
    decayed: 0,
    reason: "loot",
    note: null,
    character: "Freshface-Whitemane",
    member_id: 9,
    member_name: "Freshface",
    officer: "Officername-Whitemane",
    item_name: "Signet of Unshakable Faith",
    response: "de",
    voided: true,
  },
  {
    id: "ledger-7",
    at: inDays(-6),
    kind: "ep",
    amount: 10,
    decayed: 7.65,
    reason: "boss_kill",
    note: null,
    character: "Strayalt-Whitemane",
    member_id: null,
    member_name: null,
    officer: "Officername-Whitemane",
    item_name: null,
    response: null,
    voided: false,
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
    battlenet_recipe_id: 101,
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
    battlenet_recipe_id: null,
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

// ——— Class/spec art (GET /api/game/classes, public): small icons the site draws next to class-colored names. ———
export const GAME_CLASSES: GameClass[] = [
  {
    class: "warrior",
    name: "Warrior",
    icon_url: null,
    specs: [
      { id: 71, name: "Arms", icon_url: null },
      { id: 72, name: "Fury", icon_url: null },
      { id: 73, name: "Protection", icon_url: null },
    ],
  },
  {
    class: "paladin",
    name: "Paladin",
    icon_url: null,
    specs: [
      { id: 65, name: "Holy", icon_url: null },
      { id: 66, name: "Protection", icon_url: null },
      { id: 70, name: "Retribution", icon_url: null },
    ],
  },
  {
    class: "hunter",
    name: "Hunter",
    icon_url: null,
    specs: [
      { id: 254, name: "Marksmanship", icon_url: null },
      { id: 255, name: "Survival", icon_url: null },
      { id: 253, name: "Beast Mastery", icon_url: null },
    ],
  },
  {
    class: "rogue",
    name: "Rogue",
    icon_url: null,
    specs: [
      { id: 259, name: "Assassination", icon_url: null },
      { id: 260, name: "Combat", icon_url: null },
      { id: 261, name: "Subtlety", icon_url: null },
    ],
  },
  {
    class: "priest",
    name: "Priest",
    icon_url: null,
    specs: [
      { id: 256, name: "Discipline", icon_url: null },
      { id: 257, name: "Holy", icon_url: null },
      { id: 258, name: "Shadow", icon_url: null },
    ],
  },
  {
    class: "shaman",
    name: "Shaman",
    icon_url: null,
    specs: [
      { id: 262, name: "Elemental", icon_url: null },
      { id: 263, name: "Enhancement", icon_url: null },
      { id: 264, name: "Restoration", icon_url: null },
    ],
  },
  {
    class: "mage",
    name: "Mage",
    icon_url: null,
    specs: [
      { id: 62, name: "Arcane", icon_url: null },
      { id: 63, name: "Fire", icon_url: null },
      { id: 64, name: "Frost", icon_url: null },
    ],
  },
  {
    class: "warlock",
    name: "Warlock",
    icon_url: null,
    specs: [
      { id: 265, name: "Affliction", icon_url: null },
      { id: 266, name: "Demonology", icon_url: null },
      { id: 267, name: "Destruction", icon_url: null },
    ],
  },
  {
    class: "druid",
    name: "Druid",
    icon_url: null,
    specs: [
      { id: 102, name: "Feral Combat", icon_url: null },
      { id: 573, name: "Balance", icon_url: null },
      { id: 105, name: "Restoration", icon_url: null },
    ],
  },
];

// ——— Professions and recipes (GET /api/professions/[/{id}], GET /api/recipes/{id}, public): the recipes room. ———
export const PROFESSIONS: Profession[] = [
  { id: 164, name: "Blacksmithing", type: "PRIMARY", icon_url: null, skill_tier_id: 2938 },
  { id: 171, name: "Alchemy", type: "PRIMARY", icon_url: null, skill_tier_id: 2940 },
];

export const PROFESSION_SKILL_TIERS: Record<number, ProfessionSkillTier> = {
  164: {
    profession_id: 164,
    profession_name: "Blacksmithing",
    categories: [
      {
        name: "Armor",
        recipes: [
          { id: 101, name: "Copper Chain Pants" },
          { id: 102, name: "Heavy Grinding Stone" },
        ],
      },
      { name: "Weapons", recipes: [{ id: 103, name: "Rough Sharpening Stone" }] },
    ],
  },
  171: {
    profession_id: 171,
    profession_name: "Alchemy",
    categories: [{ name: "Potions", recipes: [{ id: 104, name: "Minor Healing Potion" }] }],
  },
};

export const RECIPES: RecipeDetailInfo[] = [
  {
    recipe_id: 101,
    name: "Copper Chain Pants",
    description: "A sturdy set of copper chain leggings.",
    rank: null,
    profession: "Blacksmithing",
    icon_url: null,
    crafted_item: { item_id: 2852, name: "Copper Chain Pants", quality: "Common" },
    crafted_quantity: null,
    reagents: [
      { item_id: 2840, name: "Copper Bar", quantity: 6, quality: null },
      { item_id: 2841, name: "Tin Bar", quantity: 2, quality: null },
    ],
    crafters: [{ character: "Guideline-Whitemane", member_id: 4, member_name: "Quest Guide", skill: 150 }],
  },
  {
    recipe_id: 102,
    name: "Heavy Grinding Stone",
    description: null,
    rank: null,
    profession: "Blacksmithing",
    icon_url: null,
    crafted_item: null,
    crafted_quantity: null,
    reagents: [{ item_id: 2842, name: "Heavy Stone", quantity: 2, quality: null }],
    crafters: [],
  },
];

export const GUILD_DIRECTORY: GuildDirectory = {
  characters: [
    {
      character: "Guideline-Whitemane",
      member_id: 4,
      member_name: "Quest Guide",
      professions: [
        { name: "Mining", skill: 300, max_skill: 300 },
        { name: "Blacksmithing", skill: 150, max_skill: 300 },
        { name: "Cooking", skill: 75, max_skill: 75 },
      ],
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
    {
      character: "Wanderer-Whitemane",
      member_id: 7,
      member_name: "Wanderer",
      professions: [
        { name: "Herbalism", skill: 300, max_skill: 300 },
        { name: "Alchemy", skill: 275, max_skill: 300 },
        { name: "Fishing", skill: 150, max_skill: 300 },
      ],
      level: 60,
      class: "HUNTER",
      race: "Orc",
      spec: "Beast Mastery",
      item_level: 60.4,
      attunements: [],
      reputations: [],
      cooldowns: [],
      freshness: { prof: inDays(-1), char: inDays(-1), cd: null, market: null, stock: null },
    },
    {
      character: "Wanderalt-Whitemane",
      member_id: 7,
      member_name: "Wanderer",
      professions: [
        { name: "Mining", skill: 225, max_skill: 300 },
        { name: "Engineering", skill: 100, max_skill: 300 },
      ],
      level: 55,
      class: "HUNTER",
      race: "Orc",
      spec: "Marksmanship",
      item_level: 42.1,
      attunements: [],
      reputations: [],
      cooldowns: [],
      freshness: { prof: inDays(-2), char: inDays(-2), cd: null, market: null, stock: null },
    },
    {
      character: "Freshface-Whitemane",
      member_id: 9,
      member_name: "Freshface",
      professions: [
        { name: "Mining", skill: 180, max_skill: 300 },
        { name: "Skinning", skill: 300, max_skill: 300 },
        { name: "First Aid", skill: 225, max_skill: 300 },
      ],
      level: 58,
      class: "ROGUE",
      race: "Undead",
      spec: "Assassination",
      item_level: 44.0,
      attunements: [],
      reputations: [],
      cooldowns: [],
      freshness: { prof: inDays(-1), char: inDays(-1), cd: null, market: null, stock: null },
    },
    {
      character: "Strayalt-Whitemane",
      member_id: null,
      member_name: null,
      professions: [
        { name: "Tailoring", skill: 300, max_skill: 300 },
        { name: "Enchanting", skill: 120, max_skill: 300 },
        { name: "Cooking", skill: 300, max_skill: 300 },
      ],
      level: 60,
      class: "MAGE",
      race: "Gnome",
      spec: "Frost",
      item_level: 50.5,
      attunements: [],
      reputations: [],
      cooldowns: [],
      freshness: { prof: inDays(-3), char: inDays(-3), cd: null, market: null, stock: null },
    },
    {
      character: "Tank1-Whitemane",
      member_id: 4,
      member_name: "Quest Guide",
      professions: [
        { name: "Mining", skill: 300, max_skill: 300 },
        { name: "Blacksmithing", skill: 300, max_skill: 300 },
      ],
      level: 60,
      class: "WARRIOR",
      race: "Human",
      spec: "Protection",
      item_level: 61.0,
      attunements: ["onyxia", "molten_core"],
      reputations: [],
      cooldowns: [],
      freshness: { prof: inDays(-1), char: inDays(-1), cd: null, market: null, stock: null },
    },
    {
      character: "Ironhide-Whitemane",
      member_id: 15,
      member_name: "Ironhide",
      professions: [
        { name: "Mining", skill: 275, max_skill: 300 },
        { name: "Blacksmithing", skill: 275, max_skill: 300 },
      ],
      level: 60,
      class: "WARRIOR",
      race: "Dwarf",
      spec: "Fury",
      item_level: 56.8,
      attunements: [],
      reputations: [],
      cooldowns: [],
      freshness: { prof: inDays(-1), char: inDays(-1), cd: null, market: null, stock: null },
    },
    {
      character: "Rootmaster-Whitemane",
      member_id: 16,
      member_name: "Rootmaster",
      professions: [
        { name: "Mining", skill: 60, max_skill: 300 },
        { name: "Herbalism", skill: 275, max_skill: 300 },
        { name: "Fishing", skill: 300, max_skill: 300 },
      ],
      level: 59,
      class: "DRUID",
      race: "Tauren",
      spec: "Balance",
      item_level: 48.3,
      attunements: [],
      reputations: [],
      cooldowns: [],
      freshness: { prof: inDays(-2), char: inDays(-2), cd: null, market: null, stock: null },
    },
    {
      character: "Potionmaker-Whitemane",
      member_id: 17,
      member_name: "Potionmaker",
      professions: [
        { name: "Mining", skill: 30, max_skill: 300 },
        { name: "Alchemy", skill: 300, max_skill: 300 },
      ],
      level: 60,
      class: "SHAMAN",
      race: "Tauren",
      spec: "Restoration",
      item_level: 52.6,
      attunements: [],
      reputations: [],
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

export const GUILD_OFFICERS: GuildOfficer[] = [
  {
    character: "Guideline-Whitemane",
    name: "Guideline Whitemane",
    rank: "Guild Master",
    rank_index: 0,
    class: "paladin",
    level: 60,
    online: true,
    last_seen_at: inDays(0, 9),
  },
  {
    character: "Wanderer-Whitemane",
    name: "Wanderer Whitemane",
    rank: "Officer",
    rank_index: 1,
    class: "hunter",
    level: 60,
    online: false,
    last_seen_at: inDays(0, 10),
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
    slug: "hopeful-whitemane",
    battlenet: {
      slug: "hopeful-whitemane",
      name: "Hopeful",
      surname: "Whitemane",
      level: 60,
      class: "mage",
      race: "Gnome",
      faction: "Alliance",
      guild_name: "Fuzion",
      guild_slug: "fuzion",
      in_roster: false,
      guild_rank: null,
      rank_name: null,
      item_level: 240,
      spec: "Frost",
      achievement_points: 1500,
      honorable_kills: 20,
      pvp_rank: 1,
      last_login_at: inDays(-1),
      profile_found: true,
      fetched_at: inDays(-1),
    },
  },
  {
    id: "recruit-2",
    character: "Greenleaf",
    class: "DRUID",
    status: "applicant",
    note: null,
    member_id: null,
    checklist: { talked: false, gear_check: false, first_raid: false, vouched: false },
    votes: [],
    at: inDays(-1),
    slug: null,
    battlenet: null,
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

// ——— Auction house prices (GET /api/auctions/prices/{item_id}[?ids=], GET/POST/DELETE /api/me/auction-watches):
// faction-wide lowest prices for items already seen above (items, recipe reagents, guild market). Glory of the
// Defender (ITEMS[0]) is listed with a 14-day trend and two houses; Cloak of Autumn's Child (ITEMS[1]) is never
// listed, to exercise the "Not listed right now" state.
function auctionTrend(basePrice: number): ItemAuctionPrice["trend"] {
  return Array.from({ length: 14 }, (_, i) => ({
    day: inDays(-13 + i, 0).slice(0, 10),
    unit_price: basePrice + (i % 3) * 50,
  }));
}

function itemAuctionPrice(itemId: number, unitPrice: number | null): ItemAuctionPrice {
  if (unitPrice === null) {
    return { item_id: itemId, unit_price: null, quantity_total: 0, houses: [], trend: [], updated_at: null };
  }
  return {
    item_id: itemId,
    unit_price: unitPrice,
    quantity_total: 12,
    houses: [
      {
        house_id: 110,
        house_name: "Alliance Auction House",
        unit_price: unitPrice,
        quantity: 7,
        listings: 3,
        updated_at: inDays(0),
      },
      {
        house_id: 111,
        house_name: "Alliance Auction House",
        unit_price: unitPrice + 500,
        quantity: 5,
        listings: 2,
        updated_at: inDays(0),
      },
    ],
    trend: auctionTrend(unitPrice),
    updated_at: inDays(0),
  };
}

export const AUCTION_PRICES: Record<number, ItemAuctionPrice> = {
  [ITEMS[0]!.item_id]: itemAuctionPrice(ITEMS[0]!.item_id, 15000), // Glory of the Defender: 1g 50s
  [ITEMS[1]!.item_id]: itemAuctionPrice(ITEMS[1]!.item_id, null), // Cloak of Autumn's Child: not listed
  2840: itemAuctionPrice(2840, 100), // Copper Bar (recipe 101 reagent, priced)
  2841: itemAuctionPrice(2841, 150), // Tin Bar (recipe 101 reagent, priced \u2014 recipe 101 fully prices)
  2852: itemAuctionPrice(2852, 2000), // Heavy Grinding Stone (recipe 101's crafted item; also a guild market buy row)
  13510: itemAuctionPrice(13510, 50000), // Flask of the Titans (guild market sell row)
  // Recipe 102's reagent (2842, Heavy Stone) is intentionally left unpriced to exercise the missing-price state.
};

export function auctionPriceSummary(itemId: number): ItemPriceSummary {
  const price = AUCTION_PRICES[itemId];
  return price
    ? {
        item_id: itemId,
        unit_price: price.unit_price,
        quantity_total: price.quantity_total,
        updated_at: price.updated_at,
      }
    : { item_id: itemId, unit_price: null, quantity_total: 0, updated_at: null };
}

// The member's own watches (GET/POST/DELETE /api/me/auction-watches), mutated per test like the wishlist.
export const AUCTION_WATCHES: AuctionWatch[] = [
  {
    id: "watch-1",
    item_id: ITEMS[0]!.item_id,
    item_name: ITEMS[0]!.name,
    icon_url: null,
    max_unit_price: 20000,
    current_unit_price: 15000,
    created_at: inDays(-5),
    last_alerted_at: inDays(-1),
  },
];

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

// ——— Quests (GET /api/quests/areas[/{id}], GET /api/quests/{id}) ———
export const QUEST_AREAS: QuestArea[] = [
  {
    id: 15,
    name: "Dustwallow Marsh",
    quests: [
      { id: 1, title: "The Missing Diplomat" },
      { id: 2, title: "Brackenwall Village" },
    ],
  },
  { id: 1, name: "Dun Morogh", quests: [{ id: 3, title: "Rage Scar Hold" }] },
];

export const QUEST_AREA_SUMMARIES = QUEST_AREAS.map(({ id, name }) => ({ id, name }));

export const QUESTS: Quest[] = [
  {
    id: 1,
    title: "The Missing Diplomat",
    description: "Find the diplomat, {class}.",
    area: "Dustwallow Marsh",
    category: "Epic",
    type: "Elite",
    min_level: 20,
    max_level: 60,
    is_repeatable: false,
    is_daily: false,
    is_weekly: false,
    rewards: {
      experience: 550,
      money: 225,
      items: [{ item_id: 159, name: "Refreshing Spring Water" }],
      reputations: [{ faction: "Argent Dawn", value: 75 }],
    },
  },
];

// ——— Achievements (GET /api/achievements/categories[/{id}], GET /api/achievements/{id}) ———
export const ACHIEVEMENT_CATEGORIES: AchievementCategoryTree[] = [
  { id: 15568, name: "Classes", children: [{ id: 15587, name: "Alchemy" }] },
];

export const ACHIEVEMENT_CATEGORY_DETAIL: AchievementCategory = {
  id: 15587,
  name: "Alchemy",
  achievements: [{ id: 62012, name: "Journeyman Alchemist", points: 10, icon_url: null }],
};

export const ACHIEVEMENTS: Achievement[] = [
  {
    id: 62012,
    name: "Journeyman Alchemist",
    description: "Learn 150 alchemy recipes.",
    points: 10,
    icon_url: null,
    category: "Alchemy",
    reward_description: null,
    criteria: {
      description: null,
      amount: 0,
      children: [{ description: "Learn Alchemy recipes", amount: 150, children: [] }],
    },
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

// ——— Level milestones (GET /api/characters/milestones) ———
export const CHARACTER_MILESTONES: CharacterMilestone[] = [
  {
    id: "milestone-1",
    slug: "nox-zul",
    name: "Nox",
    surname: "Zul",
    class: "warrior",
    level: 60,
    reached_at: inDays(-1),
    posted_at: inDays(-1),
  },
  {
    id: "milestone-2",
    slug: "thal-windrunner",
    name: "Thal",
    surname: "Windrunner",
    class: "hunter",
    level: 40,
    reached_at: inDays(-6),
    posted_at: null,
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
    recent_achievements: [{ id: ACHIEVEMENTS[0]!.id, name: "Onyxia's Downfall", completed_at: inDays(-3) }],
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

// ——— PvP: battleground match history and boards, built from the addon's recorded scoreboards ———
export const PVP_MATCHES: PvpMatchDetail[] = [
  {
    id: "aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa",
    map: "Warsong Gulch",
    ended_at: inDays(-1),
    duration: 912,
    winner: "alliance",
    guild_faction: "alliance",
    won: true,
    guild_players: [CHARACTERS[0]!.name],
    recorded_by: `${CHARACTERS[0]!.name}-${CHARACTERS[0]!.surname}`,
    players: [
      {
        name: CHARACTERS[0]!.name,
        faction: "alliance",
        race: CHARACTERS[0]!.race,
        class: CHARACTERS[0]!.class,
        killing_blows: 5,
        honorable_kills: 18,
        deaths: 2,
        honor_gained: 210,
        damage_done: 62000,
        healing_done: 1400,
        guild_member: true,
        character_slug: CHARACTERS[0]!.slug,
      },
      {
        name: "Grimtusk",
        faction: "horde",
        race: "Orc",
        class: "warrior",
        killing_blows: 2,
        honorable_kills: 9,
        deaths: 4,
        honor_gained: 120,
        damage_done: 38000,
        healing_done: 0,
        guild_member: false,
        character_slug: null,
      },
    ],
  },
  {
    id: "bbbbbbbb-2222-4bbb-8bbb-bbbbbbbbbbbb",
    map: "Arathi Basin",
    ended_at: inDays(-2),
    duration: 1480,
    winner: "horde",
    guild_faction: "alliance",
    won: false,
    guild_players: [],
    recorded_by: "Someone-Whitemane",
    players: [],
  },
];

export function pvpMatchPage(matches: PvpMatchDetail[], page: number): PvpMatchPage {
  const perPage = 25;
  const start = (page - 1) * perPage;
  return {
    page,
    page_count: Math.max(1, Math.ceil(matches.length / perPage)),
    matches: matches.slice(start, start + perPage).map(({ players: _players, ...summary }) => summary),
  };
}

export const PVP_BOARDS: PvpBoards = {
  matches: PVP_MATCHES.length,
  wins: [{ name: CHARACTERS[0]!.name, class: CHARACTERS[0]!.class, character_slug: CHARACTERS[0]!.slug, value: 1 }],
  honorable_kills: [
    { name: CHARACTERS[0]!.name, class: CHARACTERS[0]!.class, character_slug: CHARACTERS[0]!.slug, value: 18 },
  ],
  killing_blows: [
    { name: CHARACTERS[0]!.name, class: CHARACTERS[0]!.class, character_slug: CHARACTERS[0]!.slug, value: 5 },
  ],
  honor_gained: [
    { name: CHARACTERS[0]!.name, class: CHARACTERS[0]!.class, character_slug: CHARACTERS[0]!.slug, value: 210 },
  ],
  damage_done: [
    { name: CHARACTERS[0]!.name, class: CHARACTERS[0]!.class, character_slug: CHARACTERS[0]!.slug, value: 62000 },
  ],
  healing_done: [],
};

// ——— Talents (GET /api/talents/{class}, GET /api/talent-builds?class=, GET/POST/DELETE /api/me/talent-builds[/{id}],
// PUT /api/talent-builds/{id}/pin). One class (druid) with two small trees, few enough nodes to spend and check by
// hand: Balance's row 2 (Moonglow) needs 5 points spent in row 1 first, and its Genesis needs Starlight Wrath maxed.
export const TALENTS_DRUID: ClassTalents = {
  class: "druid",
  max_points: 51,
  first_level: 10,
  trees: [
    {
      spec_id: 574,
      name: "Balance",
      icon_url: null,
      nodes: [
        {
          id: 1,
          row: 1,
          col: 1,
          max_rank: 5,
          talent_id: 100,
          name: "Starlight Wrath",
          requires: null,
          ranks: [1, 2, 3, 4, 5].map((rank) => ({
            spell_id: 9100 + rank,
            description: `Reduces the cast time of Wrath and Starfire by ${rank}%.`,
          })),
        },
        {
          id: 2,
          row: 1,
          col: 2,
          max_rank: 1,
          talent_id: 101,
          name: "Nature's Grace",
          requires: null,
          ranks: [
            { spell_id: 9110, description: "Your spell critical strikes reduce the cast time of your next spell." },
          ],
        },
        {
          id: 3,
          row: 1,
          col: 3,
          max_rank: 1,
          talent_id: 102,
          name: "Genesis",
          requires: 1,
          ranks: [{ spell_id: 9120, description: "Increases the damage of your damage over time spells." }],
        },
        {
          id: 4,
          row: 2,
          col: 1,
          max_rank: 1,
          talent_id: 103,
          name: "Moonglow",
          requires: null,
          ranks: [{ spell_id: 9130, description: "Reduces the mana cost of your Moonfire, Starfire and Wrath." }],
        },
      ],
    },
    {
      spec_id: 134,
      name: "Feral Combat",
      icon_url: null,
      nodes: [
        {
          id: 10,
          row: 1,
          col: 1,
          max_rank: 5,
          talent_id: 110,
          name: "Ferocity",
          requires: null,
          ranks: [1, 2, 3, 4, 5].map((rank) => ({
            spell_id: 9210 + rank,
            description: `Reduces the cost of most Cat and Bear Form abilities by ${rank * 2}%.`,
          })),
        },
        {
          id: 11,
          row: 1,
          col: 2,
          max_rank: 1,
          talent_id: 111,
          name: "Feral Aggression",
          requires: null,
          ranks: [{ spell_id: 9220, description: "Increases the attack power bonus of your Tiger's Fury." }],
        },
      ],
    },
  ],
};

export const TALENT_BUILDS: TalentBuild[] = [
  {
    id: "talent-build-1",
    class: "druid",
    name: "Starfire spam",
    code: "5-",
    note: "Maxes Starlight Wrath for raid night.",
    pinned: true,
    member_id: OFFICER.id,
    member_name: OFFICER.display_name,
    created_at: inDays(-6),
  },
];
