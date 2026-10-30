// Every test runs against the built site (website/dist, served by `astro preview`) with the API answered here, so
// the suite needs no database and behaves the same locally and in CI. The mock follows the server's rules that the
// pages depend on: signed-out visitors get event headlines only, and sign-in, sign-out and Battle.net links are
// full page loads. Any API call the mock doesn't know fails the test, so a page can't quietly drift from it.
import { test as base, expect, type Page, type Route } from "@playwright/test";

import type {
  Addon,
  AttendanceMark,
  AwayRange,
  EventDetail,
  EventSummary,
  HeroRow,
  Me,
  Recruiting,
} from "../src/scripts/api";
import {
  ADDONS,
  ATTENDANCE_EVENTS,
  ATTENDANCE_REPORT,
  ATTENDANCE_TRENDS,
  EVENTS,
  GM_MEMBERS,
  HEROES,
  LIVE,
  ONLINE,
  RECRUITING,
  SIGNUPS,
  attendanceDetail,
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
    });
    // Sign-in leaves the site (the real server redirects to Discord): a stub shows the browser really loaded it.
    await context.route("**/auth/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>auth</title><p>auth stub</p>",
      }),
    );

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
