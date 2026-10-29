// Every test runs against the built site (website/dist, served by `astro preview`) with the API answered here, so
// the suite needs no database and behaves the same locally and in CI. The mock follows the server's rules that the
// pages depend on: signed-out visitors get event headlines only, and sign-in, sign-out and Battle.net links are
// full page loads. Any API call the mock doesn't know fails the test, so a page can't quietly drift from it.
import { test as base, expect, type Page, type Route } from "@playwright/test";

import type { Addon, EventDetail, EventSummary, Me } from "../src/scripts/api";
import { ADDONS, EVENTS, GM_MEMBERS, LIVE, eventDetail, gmMemberDetail } from "./data";

type Site = {
  /** Who `/api/me` says is signed in; `null` (the default) is a signed-out visitor. */
  signIn(me: Me | null): void;
  /** What `/api/addons` lists; `ADDONS` by default. */
  addons(list: Addon[]): void;
  /** API calls that reached the mock without a handler. */
  unmocked: string[];
  /** Uncaught page errors and `console.error` lines. */
  errors: string[];
};

function anonymousSummary(event: EventSummary): EventSummary {
  return { ...event, notes: null, counts: null };
}

function anonymousDetail(detail: EventDetail): EventDetail {
  return { ...detail, notes: null, counts: null, signups: [], my_signup: null, discord_interest: null };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export const test = base.extend<{ site: Site }>({
  site: async ({ context, baseURL }, use) => {
    let me: Me | null = null;
    let addons = ADDONS;
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
      if (path === "/api/addons" && method === "GET") {
        return json(route, addons);
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
        return json(route, me ? eventDetail(event) : anonymousDetail(eventDetail(event)));
      }
      if (/^\/api\/events\/[^/]+\/signup$/.test(path) && method === "PUT") {
        return json(route, { ...eventDetail(EVENTS[0]).signups[0], ...JSON.parse(request.postData() ?? "{}") });
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
      unmocked.push(`${method} ${path}${url.search}`);
      return json(route, { detail: "Not mocked" }, 404);
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
    await use({ signIn: (who) => (me = who), addons: (list) => (addons = list), unmocked, errors });
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
