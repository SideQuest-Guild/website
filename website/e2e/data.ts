// Fixture data for the mocked API, typed against the site's own response shapes (src/scripts/api.ts) so a schema
// change that the pages depend on breaks the build here too. Times are relative to now so "upcoming" stays upcoming.
import type {
  Addon,
  AttendanceDetail,
  AttendanceEventSummary,
  AttendanceReport,
  AttendanceSignup,
  AttendanceTrends,
  DiscordLive,
  DiscordOnline,
  EarnedBadge,
  EpgpCharacter,
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
  GuildAnnouncement,
  GuildBankRow,
  GuildCrafterProfession,
  GuildCrafterResult,
  GuildNewsItem,
  GuildRoster,
  HeroLeaderboard,
  HeroProfile,
  HeroRow,
  Me,
  Recruiting,
  Signup,
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
  signup("s1", "Brannoc", { class: "warrior", role: "tank", group: 1 }),
  signup("s2", "Elowen", { class: "priest", role: "healer", group: 1 }),
  signup("s3", "Thistlewhit", { class: "mage", role: "dps", group: 2 }),
  signup("s4", "Kaelthasmaybe", { class: "shaman", role: "healer", status: "tentative" }),
  signup("s5", "Grimbold", { class: "hunter", role: "dps", bench: true }),
];

export function eventDetail(event: EventSummary): EventDetail {
  return {
    ...event,
    signups: SIGNUPS,
    my_signup: null,
    discord_interest: { count: 4, members: [] },
    away: [{ display_name: "Kaelthasmaybe", avatar_url: null }],
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
