// Fixture data for the mocked API, typed against the site's own response shapes (src/scripts/api.ts) so a schema
// change that the pages depend on breaks the build here too. Times are relative to now so "upcoming" stays upcoming.
import type {
  Addon,
  DiscordLive,
  EventDetail,
  EventSummary,
  GmMember,
  GmMemberDetail,
  Me,
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
  return { ...event, signups: SIGNUPS, my_signup: null, discord_interest: { count: 4, members: [] } };
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
