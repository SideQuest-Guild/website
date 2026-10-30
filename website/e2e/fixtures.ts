// Every test runs against the built site (website/dist, served by `astro preview`) with the API answered here, so
// the suite needs no database and behaves the same locally and in CI. The mock follows the server's rules that the
// pages depend on: signed-out visitors get event headlines only, and sign-in, sign-out and Battle.net links are
// full page loads. Any API call the mock doesn't know fails the test, so a page can't quietly drift from it.
import { test as base, expect, type Page, type Route } from "@playwright/test";

import type {
  Addon,
  AttendanceMark,
  AwayRange,
  EpgpAdjustmentCreate,
  EpgpCharacter,
  EpgpRecruit,
  EventDetail,
  EventSummary,
  GuildAnnouncement,
  HeroRow,
  Me,
  Recruiting,
} from "../src/scripts/api";
import {
  ADDONS,
  ATTENDANCE_EVENTS,
  ATTENDANCE_REPORT,
  ATTENDANCE_TRENDS,
  EPGP_CHARACTERS,
  EPGP_DEVICE_AUTHORIZATION,
  EPGP_LOOT,
  EPGP_MEMBER_NOTES,
  EPGP_PROGRESSION,
  EPGP_RECRUITS,
  EPGP_ROSTER,
  EPGP_RULES,
  EPGP_STANDINGS,
  EPGP_SYNC_TOKENS,
  EVENTS,
  GM_MEMBERS,
  GUILD_ANNOUNCEMENTS,
  GUILD_BANK,
  GUILD_CRAFTERS,
  GUILD_NEWS,
  GUILD_ROSTER,
  HEROES,
  LIVE,
  MCP_TOKENS,
  ONLINE,
  RECRUITING,
  SIGNUPS,
  attendanceDetail,
  epgpImportResult,
  eventDetail,
  gmMemberDetail,
  heroLeaderboard,
  heroProfile,
} from "./data";

type Site = {
  /** Who `/api/me` says is signed in; `null` (the default) is a signed-out visitor. */
  signIn(me: Me | null): void;
  /** What `/api/addons` lists; `ADDONS` by default. */
  addons(list: Addon[]): void;
  /** What `/api/recruiting` reports; `RECRUITING` (nothing wanted) by default. */
  recruiting(data: Recruiting): void;
  /** API calls that reached the mock without a handler. */
  unmocked: string[];
  /** Uncaught page errors and `console.error` lines. */
  errors: string[];
};

function anonymousSummary(event: EventSummary): EventSummary {
  return { ...event, notes: null, counts: null };
}

function anonymousDetail(detail: EventDetail): EventDetail {
  return { ...detail, notes: null, counts: null, signups: [], my_signup: null, discord_interest: null, away: null };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// A trimmed copy of the real API's OpenAPI document (api/src/sidequest_api/app.py), just enough paths and shapes
// to exercise the API reference page's chrome, sidebar and an operation's parameters/responses without the
// hundreds of real routes.
const OPENAPI_SPEC = {
  openapi: "3.1.0",
  info: {
    title: "SideQuest Guild API",
    version: "0.1.0",
    description: "The API behind the SideQuest site, the Discord bot and the in-game addon.",
  },
  servers: [{ url: "/" }],
  tags: [
    { name: "Events", description: "Upcoming and past guild events." },
    { name: "Me", description: "The signed-in visitor." },
    { name: "Bot", description: "Called by the Discord bot with its shared key." },
  ],
  paths: {
    "/api/events": {
      get: {
        tags: ["Events"],
        summary: "List events",
        operationId: "list_events",
        parameters: [
          { name: "when", in: "query", schema: { type: "string", enum: ["upcoming", "past"] } },
          { name: "kind", in: "query", schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Events matching the filters",
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/EventSummary" } },
              },
            },
          },
        },
      },
    },
    "/api/me": {
      get: {
        tags: ["Me"],
        summary: "The signed-in visitor",
        operationId: "get_me",
        security: [{ SessionAuth: [] }],
        responses: {
          "200": { description: "Signed in", content: { "application/json": { schema: { type: "object" } } } },
          "401": { description: "Not signed in" },
        },
      },
    },
    "/api/guilds/{guild_id}/members": {
      get: {
        tags: ["Bot"],
        summary: "List guild members",
        operationId: "bot_list_members",
        security: [{ ApiKeyAuth: [] }],
        parameters: [{ name: "guild_id", in: "path", required: true, schema: { type: "string" } }],
        responses: { "200": { description: "The guild's members" } },
      },
    },
  },
  components: {
    securitySchemes: {
      ApiKeyAuth: { type: "apiKey", in: "header", name: "X-API-Key" },
      SessionAuth: { type: "apiKey", in: "cookie", name: "session" },
    },
    schemas: {
      EventSummary: {
        type: "object",
        required: ["id", "title", "starts_at"],
        properties: {
          id: { type: "string" },
          title: { type: "string" },
          starts_at: { type: "string", format: "date-time" },
        },
      },
    },
  },
};

export const test = base.extend<{ site: Site }>({
  site: async ({ context, baseURL }, use) => {
    let me: Me | null = null;
    let addons = ADDONS;
    let recruiting = RECRUITING;
    let calendarToken = "mock-calendar-token";
    let awayRanges: AwayRange[] = [];
    // A per-test copy: the raid chart's PATCH handler mutates this, and a shared SIGNUPS array would leak those
    // group/bench changes into the next test.
    const signups = SIGNUPS.map((s) => Object.assign({}, s));
    // Per-test copies, mutated by the officer sync console and the account page's character CRUD.
    const epgpCharacters = EPGP_CHARACTERS.map((c) => Object.assign({}, c));
    const epgpRoster = EPGP_ROSTER.map((m) => Object.assign({}, m));
    const epgpSyncTokens = EPGP_SYNC_TOKENS.map((t) => Object.assign({}, t));
    const mcpTokens = MCP_TOKENS.map((t) => Object.assign({}, t));
    let deviceAuth = { ...EPGP_DEVICE_AUTHORIZATION };
    let deviceAuthPolled = false;
    const DEVICE_CODE = "mock-device-code";
    const epgpRecruits = EPGP_RECRUITS.map((r) =>
      Object.assign({}, r, { checklist: { ...r.checklist }, votes: [...r.votes] }),
    );
    let guildAnnouncements = GUILD_ANNOUNCEMENTS.map((a) => Object.assign({}, a));
    let myCharacters: EpgpCharacter[] = [];
    let nextCharacterId = 100;
    const unmocked: string[] = [];
    const errors: string[] = [];

    // Nothing reaches any other host (Discord, CDNs, Cloudflare's analytics beacon): the site under test is the only
    // origin. An empty answer rather than an abort, so the browser doesn't log a load failure for it.
    const origin = new URL(baseURL ?? "http://localhost").origin;
    await context.route(
      (url) => url.origin !== origin,
      (route) => route.fulfill({ status: 204 }),
    );
    await context.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const method = request.method();

      if (path === "/api/me") {
        return me ? json(route, me) : json(route, { detail: "Not signed in" }, 401);
      }
      if (path === "/api/discord/live") {
        return json(route, LIVE);
      }
      if (path === "/api/discord/online") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!me.is_guild_member) {
          return json(route, { detail: "Not a guild member" }, 403);
        }
        return json(route, ONLINE);
      }
      if (path === "/api/addons" && method === "GET") {
        return json(route, addons);
      }
      if (path === "/api/recruiting" && method === "GET") {
        return json(route, recruiting);
      }
      if (path === "/api/recruiting" && method === "PUT") {
        recruiting = { ...JSON.parse(request.postData() ?? "{}"), updated_at: new Date().toISOString() };
        return json(route, recruiting);
      }
      if (path === "/api/me/calendar" && method === "GET") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        return json(route, { token: calendarToken, url: `${origin}/api/calendar/${calendarToken}.ics` });
      }
      if (path === "/api/me/calendar/rotate" && method === "POST") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        calendarToken = `mock-calendar-token-${Date.now()}`;
        return json(route, { token: calendarToken, url: `${origin}/api/calendar/${calendarToken}.ics` });
      }
      if (path === "/api/me/away" && method === "GET") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        return json(route, awayRanges);
      }
      if (path === "/api/me/away" && method === "POST") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        const body = JSON.parse(request.postData() ?? "{}");
        const created: AwayRange = { id: `away-${awayRanges.length + 1}`, note: null, ...body };
        awayRanges = [...awayRanges, created].toSorted((a, b) => a.start_date.localeCompare(b.start_date));
        return json(route, created, 201);
      }
      const awayDeleteMatch = /^\/api\/me\/away\/([^/]+)$/.exec(path);
      if (awayDeleteMatch && method === "DELETE") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!awayRanges.some((range) => range.id === awayDeleteMatch[1])) {
          return json(route, { detail: "No such away range" }, 404);
        }
        awayRanges = awayRanges.filter((range) => range.id !== awayDeleteMatch[1]);
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/event-series" && method === "GET") {
        return json(route, []);
      }
      if (path === "/api/events" && method === "GET") {
        const now = Date.now();
        const when = url.searchParams.get("when");
        const kind = url.searchParams.get("kind");
        const events = EVENTS.filter((e) =>
          when === "past" ? Date.parse(e.starts_at) < now : Date.parse(e.starts_at) >= now,
        )
          .filter((e) => !kind || e.kind === kind)
          .map((e) => (me ? e : anonymousSummary(e)));
        return json(route, events);
      }
      const eventMatch = /^\/api\/events\/([^/]+)$/.exec(path);
      if (eventMatch && method === "GET") {
        const event = EVENTS.find((e) => e.id === eventMatch[1]);
        if (!event) {
          return json(route, { detail: "No such event" }, 404);
        }
        const detail = { ...eventDetail(event), signups };
        return json(route, me ? detail : anonymousDetail(detail));
      }
      if (/^\/api\/events\/[^/]+\/signup$/.test(path) && method === "PUT") {
        return json(route, { ...eventDetail(EVENTS[0]).signups[0], ...JSON.parse(request.postData() ?? "{}") });
      }
      const chartMatch = /^\/api\/events\/[^/]+\/signups\/([^/]+)$/.exec(path);
      if (chartMatch && method === "PATCH") {
        const target = signups.find((s) => s.id === chartMatch[1]);
        if (!target) {
          return json(route, { detail: "No such signup" }, 404);
        }
        Object.assign(target, JSON.parse(request.postData() ?? "{}"));
        return json(route, target);
      }
      if (path === "/api/gm/members") {
        return json(route, GM_MEMBERS);
      }
      const memberMatch = /^\/api\/gm\/members\/(\d+)$/.exec(path);
      if (memberMatch) {
        const member = GM_MEMBERS.find((m) => m.id === Number(memberMatch[1]));
        return member ? json(route, gmMemberDetail(member)) : json(route, { detail: "No such member" }, 404);
      }
      if (path === "/api/gm/log") {
        return json(route, { entries: [], next_before: null });
      }
      if (path === "/api/gm/cases") {
        return json(route, []);
      }
      if (path === "/api/attendance/events") {
        return json(route, ATTENDANCE_EVENTS);
      }
      const attendanceMatch = /^\/api\/events\/([^/]+)\/attendance$/.exec(path);
      if (attendanceMatch && (method === "GET" || method === "PUT")) {
        const summary = ATTENDANCE_EVENTS.find((e) => e.id === attendanceMatch[1]) ?? ATTENDANCE_EVENTS[0];
        if (method === "PUT") {
          const body = JSON.parse(request.postData() ?? "{}") as AttendanceMark;
          const detail = attendanceDetail({
            ...summary,
            attendance_taken_at: new Date().toISOString(),
            needs_attendance: false,
          });
          detail.signups = detail.signups.map((s) => {
            const entry = body.entries.find((e) => e.signup_id === s.signup_id);
            return entry ? { ...s, attended: entry.attended } : s;
          });
          return json(route, detail);
        }
        return json(route, attendanceDetail(summary));
      }
      if (path === "/api/attendance/report") {
        return json(route, ATTENDANCE_REPORT);
      }
      if (path === "/api/attendance/trends") {
        return json(route, ATTENDANCE_TRENDS);
      }
      if (path === "/api/heroes" && method === "GET") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        return json(route, heroLeaderboard(url.searchParams.get("season") ?? "season-one"));
      }
      const heroMatch = /^\/api\/heroes\/(\d+)$/.exec(path);
      if (heroMatch && method === "GET") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        const row = HEROES.find((h: HeroRow) => h.member_id === Number(heroMatch[1]));
        return row ? json(route, heroProfile(row)) : json(route, { detail: "No such member" }, 404);
      }
      if (path === "/api/epgp/standings" && method === "GET") {
        return json(route, { generated_at: new Date().toISOString(), rules: EPGP_RULES, rows: EPGP_STANDINGS });
      }
      if (path === "/api/epgp/loot" && method === "GET") {
        return json(route, { items: EPGP_LOOT });
      }
      if (path === "/api/epgp/progression" && method === "GET") {
        return json(route, { instances: EPGP_PROGRESSION });
      }
      if (path === "/api/epgp/imports" && method === "POST") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        return json(route, epgpImportResult());
      }
      if (path === "/api/epgp/game-import" && method === "GET") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        return json(route, { payload: "SQI1:bW9jay1pbXBvcnQtc3RyaW5n", generated_at: new Date().toISOString() });
      }
      if (path === "/api/epgp/adjustments" && method === "POST") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const body = JSON.parse(request.postData() ?? "{}") as EpgpAdjustmentCreate;
        return json(route, {
          id: `adjust-${Date.now()}`,
          at: new Date().toISOString(),
          kind: body.kind,
          amount: body.amount,
          decayed: body.amount,
          reason: "adjust",
          note: body.reason,
          character: null,
          member_id: body.member_id,
          member_name: epgpRoster.find((m) => m.member_id === body.member_id)?.name ?? null,
          officer: me.display_name,
          item_name: null,
          voided: false,
        });
      }
      if (path === "/api/epgp/characters" && method === "GET") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        return json(route, { characters: epgpCharacters });
      }
      const epgpCharacterMatch = /^\/api\/epgp\/characters\/([^/]+)$/.exec(path);
      if (epgpCharacterMatch && method === "PUT") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const target = epgpCharacters.find((c) => c.id === epgpCharacterMatch[1]);
        if (!target) {
          return json(route, { detail: "No such character" }, 404);
        }
        const body = JSON.parse(request.postData() ?? "{}") as { member_id: number | null; is_main: boolean };
        target.member_id = body.member_id;
        target.member_name = epgpRoster.find((m) => m.member_id === body.member_id)?.name ?? null;
        target.is_main = body.is_main;
        return json(route, target);
      }
      if (path === "/api/epgp/roster" && method === "GET") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        return json(route, { members: epgpRoster });
      }
      const epgpRosterMatch = /^\/api\/epgp\/roster\/(\d+)$/.exec(path);
      if (epgpRosterMatch && method === "PUT") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const target = epgpRoster.find((m) => m.member_id === Number(epgpRosterMatch[1]));
        if (!target) {
          return json(route, { detail: "No such member" }, 404);
        }
        const body = JSON.parse(request.postData() ?? "{}") as { raid_status: "trial" | "raider" | null };
        target.raid_status = body.raid_status;
        target.trial_started_at = body.raid_status === "trial" ? new Date().toISOString() : null;
        return json(route, target);
      }
      if (path === "/api/epgp/sync-tokens" && method === "GET") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!me.is_guild_member) {
          return json(route, { detail: "Not a guild member" }, 403);
        }
        return json(route, { tokens: epgpSyncTokens });
      }
      if (path === "/api/epgp/sync-tokens" && method === "POST") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 403);
        }
        const body = JSON.parse(request.postData() ?? "{}") as { name: string };
        const id = `token-${epgpSyncTokens.length + 1}`;
        epgpSyncTokens.push({ id, name: body.name, created_at: new Date().toISOString(), last_used_at: null });
        return json(route, { id, name: body.name, token: `sqs_${"x".repeat(40)}` }, 201);
      }
      const epgpTokenDeleteMatch = /^\/api\/epgp\/sync-tokens\/([^/]+)$/.exec(path);
      if (epgpTokenDeleteMatch && method === "DELETE") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!me.is_guild_member) {
          return json(route, { detail: "Not a guild member" }, 403);
        }
        const index = epgpSyncTokens.findIndex((t) => t.id === epgpTokenDeleteMatch[1]);
        if (index === -1) {
          return json(route, { detail: "No such token" }, 404);
        }
        epgpSyncTokens.splice(index, 1);
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/me/mcp-tokens" && method === "GET") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        return json(route, { tokens: mcpTokens });
      }
      if (path === "/api/me/mcp-tokens" && method === "POST") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const body = JSON.parse(request.postData() ?? "{}") as { name: string };
        const id = `mcp-token-${mcpTokens.length + 1}`;
        mcpTokens.push({ id, name: body.name, created_at: new Date().toISOString(), last_used_at: null });
        return json(route, { id, name: body.name, token: `sqm_${"x".repeat(40)}` }, 201);
      }
      const mcpTokenDeleteMatch = /^\/api\/me\/mcp-tokens\/([^/]+)$/.exec(path);
      if (mcpTokenDeleteMatch && method === "DELETE") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const index = mcpTokens.findIndex((t) => t.id === mcpTokenDeleteMatch[1]);
        if (index === -1) {
          return json(route, { detail: "No such token" }, 404);
        }
        mcpTokens.splice(index, 1);
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/epgp/device-authorizations" && method === "POST") {
        const body = JSON.parse(request.postData() ?? "{}") as { device_name: string };
        deviceAuth = { ...EPGP_DEVICE_AUTHORIZATION, device_name: body.device_name, status: "pending" };
        deviceAuthPolled = false;
        return json(
          route,
          {
            device_code: DEVICE_CODE,
            user_code: deviceAuth.user_code,
            verification_uri: `${origin}/companion/authorize/`,
            verification_uri_complete: `${origin}/companion/authorize/?code=${deviceAuth.user_code}`,
            expires_in: 600,
            interval: 5,
          },
          201,
        );
      }
      if (path === "/api/epgp/device-authorizations/token" && method === "POST") {
        const body = JSON.parse(request.postData() ?? "{}") as { device_code: string };
        if (body.device_code !== DEVICE_CODE) {
          return json(route, { status: "expired", token: null, name: null });
        }
        if (deviceAuth.status === "approved" && !deviceAuthPolled) {
          deviceAuthPolled = true;
          return json(route, {
            status: "approved",
            token: `sqs_${"x".repeat(40)}`,
            name: `SideQuest Companion on ${deviceAuth.device_name}`,
          });
        }
        if (deviceAuth.status === "approved") {
          return json(route, { status: "expired", token: null, name: null });
        }
        return json(route, { status: deviceAuth.status, token: null, name: null });
      }
      const deviceAuthStatusMatch = /^\/api\/epgp\/device-authorizations\/([^/]+)$/.exec(path);
      if (deviceAuthStatusMatch && method === "GET") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!me.is_guild_member) {
          return json(route, { detail: "Not a guild member" }, 403);
        }
        if (deviceAuthStatusMatch[1].replaceAll("-", "").toUpperCase() !== deviceAuth.user_code.replaceAll("-", "")) {
          return json(route, { detail: "No such device authorization" }, 404);
        }
        return json(route, deviceAuth);
      }
      const deviceAuthApproveMatch = /^\/api\/epgp\/device-authorizations\/([^/]+)\/approve$/.exec(path);
      if (deviceAuthApproveMatch && method === "POST") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!me.is_guild_member) {
          return json(route, { detail: "Not a guild member" }, 403);
        }
        deviceAuth = { ...deviceAuth, status: "approved" };
        return route.fulfill({ status: 204 });
      }
      const deviceAuthDenyMatch = /^\/api\/epgp\/device-authorizations\/([^/]+)\/deny$/.exec(path);
      if (deviceAuthDenyMatch && method === "POST") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!me.is_guild_member) {
          return json(route, { detail: "Not a guild member" }, 403);
        }
        deviceAuth = { ...deviceAuth, status: "denied" };
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/guild/roster" && method === "GET") {
        if (!me?.is_guild_member) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        return json(route, GUILD_ROSTER);
      }
      if (path === "/api/guild/crafters" && method === "GET") {
        if (!me?.is_guild_member) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        return json(route, GUILD_CRAFTERS);
      }
      if (path === "/api/guild/news" && method === "GET") {
        return json(route, { items: GUILD_NEWS });
      }
      if (path === "/api/guild/bank" && method === "GET") {
        if (!me?.is_guild_member) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        return json(route, { rows: GUILD_BANK, totals: { deposits_30d: 4, withdrawals_30d: 1 } });
      }
      if (path === "/api/guild/announcements" && method === "GET") {
        return json(route, { items: guildAnnouncements });
      }
      if (path === "/api/guild/announcements" && method === "POST") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const body = JSON.parse(request.postData() ?? "{}") as { text: string; discord: boolean };
        const created: GuildAnnouncement = {
          id: `ann-${guildAnnouncements.length + 1}`,
          text: body.text,
          author: me.display_name,
          at: new Date().toISOString(),
          source: "site",
          posted_at: body.discord ? null : null,
        };
        guildAnnouncements = [created, ...guildAnnouncements];
        return json(route, created, 201);
      }
      if (path === "/api/epgp/recruits" && method === "GET") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        return json(route, { recruits: epgpRecruits });
      }
      const recruitMatch = /^\/api\/epgp\/recruits\/([^/]+)$/.exec(path);
      if (recruitMatch && method === "PUT") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const target = epgpRecruits.find((r) => r.id === recruitMatch[1]);
        if (!target) {
          return json(route, { detail: "No such recruit" }, 404);
        }
        const body = JSON.parse(request.postData() ?? "{}") as Partial<EpgpRecruit>;
        Object.assign(target, body);
        return json(route, target);
      }
      const recruitVoteMatch = /^\/api\/epgp\/recruits\/([^/]+)\/votes$/.exec(path);
      if (recruitVoteMatch && method === "POST") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const target = epgpRecruits.find((r) => r.id === recruitVoteMatch[1]);
        if (!target) {
          return json(route, { detail: "No such recruit" }, 404);
        }
        const body = JSON.parse(request.postData() ?? "{}") as { vote: "yes" | "no" | "wait" };
        target.votes = [
          ...target.votes.filter((v) => v.officer !== me?.display_name),
          { officer: me.display_name, vote: body.vote, at: new Date().toISOString() },
        ];
        return json(route, target);
      }
      if (path === "/api/epgp/member-notes" && method === "GET") {
        if (!me?.is_officer) {
          return json(route, { detail: "Officers only" }, 401);
        }
        const memberId = Number(url.searchParams.get("member_id"));
        return json(route, { notes: EPGP_MEMBER_NOTES[memberId] ?? [] });
      }
      if (path === "/api/me/characters" && method === "GET") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        return json(route, { characters: myCharacters });
      }
      if (path === "/api/me/characters" && method === "POST") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        const body = JSON.parse(request.postData() ?? "{}") as { name: string; realm?: string; class?: string };
        if (epgpCharacters.some((c) => c.name.toLowerCase() === body.name.toLowerCase() && c.member_id !== me?.id)) {
          return json(route, { detail: "Another member already has that character." }, 409);
        }
        const created: EpgpCharacter = {
          id: `char-me-${nextCharacterId++}`,
          name: body.name,
          realm: body.realm ?? "Whitemane",
          class: body.class ?? null,
          member_id: me.id,
          member_name: me.display_name,
          is_main: myCharacters.length === 0,
          source: "claim",
          last_seen_at: null,
        };
        myCharacters = [...myCharacters, created];
        return json(route, created, 201);
      }
      const myCharacterDeleteMatch = /^\/api\/me\/characters\/([^/]+)$/.exec(path);
      if (myCharacterDeleteMatch && method === "DELETE") {
        if (!me) {
          return json(route, { detail: "Not signed in" }, 401);
        }
        if (!myCharacters.some((c) => c.id === myCharacterDeleteMatch[1])) {
          return json(route, { detail: "No such character" }, 404);
        }
        myCharacters = myCharacters.filter((c) => c.id !== myCharacterDeleteMatch[1]);
        return route.fulfill({ status: 204 });
      }
    });
    // Sign-in leaves the site (the real server redirects to Discord): a stub shows the browser really loaded it.
    await context.route("**/auth/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>auth</title><p>auth stub</p>",
      }),
    );
    // The API reference page (src/pages/api-reference/) reads this directly, not through /api/.
    await context.route("**/schema/openapi.json", (route) => json(route, OPENAPI_SPEC));

    for (const page of context.pages()) {
      watchErrors(page, origin, errors);
    }
    context.on("page", (page) => watchErrors(page, origin, errors));
    await use({
      signIn: (who) => (me = who),
      addons: (list) => (addons = list),
      recruiting: (data) => (recruiting = data),
      unmocked,
      errors,
    });
    expect(unmocked, "API calls the mock doesn't handle").toEqual([]);
    expect(errors, "page errors").toEqual([]);
  },
});

/** Errors from the site's own pages and code. Skipped: the browser loading the sign-in stub (e.g. a skipped page
 * transition), and third-party resources (Cloudflare's injected analytics beacon on a live run). */
function watchErrors(page: Page, origin: string, errors: string[]): void {
  const onSite = () => !new URL(page.url()).pathname.startsWith("/auth/");
  const offSiteUrl = (text: string) =>
    [...text.matchAll(/https?:\/\/[^\s'"]+/g)].some(([url]) => !url.startsWith(origin));
  page.on("pageerror", (error) => {
    if (onSite() && !offSiteUrl(error.message)) {
      errors.push(`${page.url()}: ${error.message}`);
    }
  });
  page.on("console", (message) => {
    const text = message.text();
    // A 401 from /api/me is how a signed-out visitor looks; the browser logs every non-2xx fetch as an error.
    if (onSite() && message.type() === "error" && !/status of 40[14]/.test(text) && !offSiteUrl(text)) {
      errors.push(`${page.url()}: ${text}`);
    }
  });
}

export { expect };
