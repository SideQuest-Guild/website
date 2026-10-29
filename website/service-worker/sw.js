// SideQuest service worker: pages, scripts, fonts and paintings answer from the device, and the public data a page
// shows answers from the device first and then re-renders in place when the fresh copy lands.
//
// integration.mjs builds dist/sw.js by prepending this build's constants:
//   BUILD     the build id every page carries in <meta name="sq-build">
//   PAGES     page paths ("/", "/events/", ...)
//   PRECACHE  the build's scripts and fonts
//   ASSETS    every file in /_astro/ (anything else in the asset cache is from an older build)
/* global BUILD, PAGES, PRECACHE, ASSETS */

const PAGE_CACHE = `sq-pages-${BUILD}`;
const ASSET_CACHE = "sq-assets";
const DATA_CACHE = "sq-data";
const META_CACHE = "sq-meta";
const IDENTITY_KEY = "/__sq/identity";
const DATA_LIMIT = 60;
const PAGE_SET = new Set(PAGES);
const BUILD_META = /<meta name="sq-build" content="([^"]+)"/;

// Data a page may get from the device first: only pages that re-render when the fresh copy lands (onFreshData in
// src/scripts/api.ts). Everything else, including /api/me, the account page and the officers console, always goes
// to the network.
const STALE_FIRST = [
  { page: /^\/$/, data: /^\/api\/(discord\/live|events)$/ },
  { page: /^\/events\/$/, data: /^\/api\/events$/ },
  { page: /^\/events\/detail\/$/, data: /^\/api\/events\/[^/]+$/ },
  { page: /^\/addons\/$/, data: /^\/api\/addons$/ },
];

// Bumped by every change (sign-up, sign-out, edit): a refresh that started before it must not store the old answer.
let dataGeneration = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Cloudflare may hand out the previous deploy's page for a few seconds after a deploy (it refreshes in the
// background), so a page is only cached once it carries this build's id. Failing the install keeps the current
// worker, and the browser tries again on a later visit.
async function fetchPage(path, retryDelays = [1500, 4000, 8000]) {
  const response = await fetch(path, { cache: "reload", credentials: "omit" });
  if (response.ok && !response.redirected && BUILD_META.exec(await response.clone().text())?.[1] === BUILD) {
    return response;
  }
  const [delay, ...rest] = retryDelays;
  if (delay === undefined) {
    throw new Error(`${path} is not build ${BUILD} yet`);
  }
  await sleep(delay);
  return fetchPage(path, rest);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const pages = await caches.open(PAGE_CACHE);
      await Promise.all(PAGES.map(async (path) => pages.put(path, await fetchPage(path))));
      const assets = await caches.open(ASSET_CACHE);
      const cached = await Promise.all(PRECACHE.map((path) => assets.match(path)));
      await assets.addAll(PRECACHE.filter((_, index) => !cached[index]));
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const stale = (await caches.keys()).filter((name) => name.startsWith("sq-pages-") && name !== PAGE_CACHE);
      await Promise.all(stale.map((name) => caches.delete(name)));
      const current = new Set(ASSETS);
      const assets = await caches.open(ASSET_CACHE);
      const old = (await assets.keys()).filter((request) => !current.has(new URL(request.url).pathname));
      await Promise.all(old.map((request) => assets.delete(request)));
      await self.clients.claim();
    })(),
  );
});

async function notify(clientId, url) {
  const targets = clientId ? [await self.clients.get(clientId)] : await self.clients.matchAll({ type: "window" });
  for (const client of targets) {
    // oxlint-disable-next-line unicorn/require-post-message-target-origin -- Client.postMessage takes no origin.
    client?.postMessage({ type: "sq-fresh", url });
  }
}

// Every page re-asks for its data after this, so whatever showed under the old answer gets replaced.
async function forgetData() {
  dataGeneration += 1;
  await caches.delete(DATA_CACHE);
  await notify(null, "*");
}

async function page(path, request) {
  const cached = await (await caches.open(PAGE_CACHE)).match(path);
  return cached ?? fetch(request);
}

async function asset(request) {
  const cache = await caches.open(ASSET_CACHE);
  // A hashed file is the same bytes whatever the request headers, so a `Vary` (e.g. `Vary: Origin` from a proxy)
  // must not turn a stored copy into a miss; module scripts and fonts are requested with an Origin header.
  const cached = await cache.match(request, { ignoreVary: true });
  if (cached) {
    return cached;
  }
  const response = await fetch(request);
  if (response.ok && response.type === "basic") {
    await cache.put(request, response.clone());
  }
  return response;
}

// Sign-ups, edits, sign-out and account deletion all change what the cached data would say.
async function change(request) {
  const response = await fetch(request);
  await forgetData();
  return response;
}

// /api/me is never cached; it only tells the worker when the person behind this browser changes (signed out,
// session expired, someone else signed in), so one person's members-only data never shows for the next.
async function watchIdentity(event) {
  const response = await fetch(event.request);
  if (response.ok || response.status === 401) {
    event.waitUntil(
      (async () => {
        const identity = response.ok ? `member:${(await response.clone().json()).id}` : "signed-out";
        const meta = await caches.open(META_CACHE);
        const before = await (await meta.match(IDENTITY_KEY))?.text();
        if (before !== identity) {
          await meta.put(IDENTITY_KEY, new Response(identity));
          if (before !== undefined) {
            await forgetData();
          }
        }
      })(),
    );
  }
  return response;
}

async function staleFirst(event, key) {
  const cache = await caches.open(DATA_CACHE);
  const cached = await cache.match(key);
  const cachedText = cached ? cached.clone().text() : null;
  const generation = dataGeneration;
  const store = async (copy) => {
    if (generation !== dataGeneration) {
      return;
    }
    const fresh = await copy.clone().text();
    await cache.put(key, copy);
    const keys = await cache.keys();
    await Promise.all(keys.slice(0, Math.max(0, keys.length - DATA_LIMIT)).map((old) => cache.delete(old)));
    if (cachedText !== null && (await cachedText) !== fresh) {
      await notify(event.clientId, key);
    }
  };
  const network = fetch(event.request).then((response) => {
    if (response.ok) {
      event.waitUntil(store(response.clone()));
    }
    return response;
  });
  if (cached) {
    event.waitUntil(network.catch(() => undefined));
    return cached;
  }
  return network;
}

function staleFirstAllowed(request, url) {
  if (!request.referrer) {
    return false;
  }
  const from = new URL(request.referrer);
  return (
    from.origin === url.origin &&
    STALE_FIRST.some((rule) => rule.page.test(from.pathname) && rule.data.test(url.pathname))
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }
  const isApi = url.pathname.startsWith("/api/");
  const isAuth = url.pathname.startsWith("/auth/");
  if (request.method !== "GET") {
    if (isApi || isAuth) {
      event.respondWith(change(request));
    }
    return;
  }
  if (isAuth) {
    // Signing in (or linking Battle.net) is about to change who this is.
    event.waitUntil(forgetData());
    return;
  }
  if (PAGE_SET.has(url.pathname)) {
    // Navigations, prerenders and the hover warm-up (site-chrome.ts) all read the same copy.
    event.respondWith(page(url.pathname, request));
    return;
  }
  if (url.pathname.startsWith("/_astro/")) {
    event.respondWith(asset(request));
    return;
  }
  if (url.pathname === "/api/me") {
    event.respondWith(watchIdentity(event));
    return;
  }
  if (isApi && staleFirstAllowed(request, url)) {
    event.respondWith(staleFirst(event, url.pathname + url.search));
  }
});
