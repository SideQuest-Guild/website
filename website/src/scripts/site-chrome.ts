// Shared page chrome on every page: the narrow-screen Menu disclosure, the back-to-top control, the officer-only
// Officers nav link, and (once per visit) the service worker, link warm-up and full loads for sign-in links.
import { ApiError, fetchMe } from "./api";
import { onPage } from "./page";

const MOBILE_QUERY = window.matchMedia("(max-width: 900px)");

function setupMenu(toggle: HTMLButtonElement, signal: AbortSignal): void {
  const listId = toggle.getAttribute("aria-controls");
  const list = listId ? document.getElementById(listId) : null;
  const label = toggle.querySelector<HTMLElement>("[data-nav-label]");
  if (!list) {
    return;
  }

  const setOpen = (open: boolean): void => {
    toggle.setAttribute("aria-expanded", String(open));
    list.classList.toggle("open", open);
    if (label) {
      label.textContent = open ? "Close" : "Menu";
    }
  };

  toggle.addEventListener("click", () => setOpen(toggle.getAttribute("aria-expanded") !== "true"));
  // Following a link (including same-page anchors) closes the menu.
  list.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("a")) {
      setOpen(false);
    }
  });
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        toggle.focus();
      }
    },
    { signal },
  );
  document.addEventListener(
    "click",
    (event) => {
      const target = event.target;
      if (target instanceof Node && !toggle.contains(target) && !list.contains(target)) {
        setOpen(false);
      }
    },
    { signal },
  );
  MOBILE_QUERY.addEventListener("change", () => setOpen(false), { signal });
}

function setupToTop(link: HTMLElement, signal: AbortSignal): void {
  let ticking = false;
  const update = (): void => {
    link.classList.toggle("show", window.scrollY > window.innerHeight * 1.2);
    ticking = false;
  };
  window.addEventListener(
    "scroll",
    () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    },
    { passive: true, signal },
  );
  update();
}

const OFFICER_FLAG = "sq-officer";

/** Shows the Officers link to signed-in officers only. The head script already applied last visit's answer to
 * avoid a reflow; this confirms it. A network failure keeps that answer; any HTTP answer replaces it. */
async function syncOfficerNav(): Promise<void> {
  let officer: boolean;
  try {
    officer = (await fetchMe()).is_officer;
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      return;
    }
    officer = false;
  }
  document.documentElement.classList.toggle("officer", officer);
  try {
    if (officer) {
      localStorage.setItem(OFFICER_FLAG, "1");
    } else {
      localStorage.removeItem(OFFICER_FLAG);
    }
  } catch {
    // Storage blocked: the link still follows /api/me, it just appears after the check.
  }
}

/** Starts loading the painting of a page the visitor is about to open (hover, focus or touch), so it's on the
 * device before the click. The page itself comes from the service worker, so reading it costs nothing. */
function setupWarmUp(): void {
  const warmed = new Set<string>([location.pathname]);
  const warm = async (target: EventTarget | null): Promise<void> => {
    const link = target instanceof Element ? target.closest<HTMLAnchorElement>("a[href]") : null;
    if (!link || !navigator.serviceWorker.controller) {
      return;
    }
    const url = new URL(link.href);
    if (url.origin !== location.origin || warmed.has(url.pathname) || /^\/(api|auth)\//.test(url.pathname)) {
      return;
    }
    warmed.add(url.pathname);
    const response = await fetch(url.pathname);
    if (!response.ok) {
      return;
    }
    const doc = new DOMParser().parseFromString(await response.text(), "text/html");
    const images: { srcset: string; sizes: string }[] = [];
    for (const preload of doc.querySelectorAll<HTMLLinkElement>('link[rel="preload"][as="image"]')) {
      const media = preload.getAttribute("media");
      if (!media || matchMedia(media).matches) {
        images.push({
          srcset: preload.getAttribute("imagesrcset") ?? "",
          sizes: preload.getAttribute("imagesizes") ?? "",
        });
      }
    }
    const room = doc.querySelector<HTMLSourceElement>('picture.room-art-pic source[type="image/avif"]');
    if (room) {
      images.push({ srcset: room.getAttribute("srcset") ?? "", sizes: room.getAttribute("sizes") ?? "" });
    }
    for (const { srcset, sizes } of images) {
      // A detached image still picks the candidate this screen would and loads it into the cache.
      const image = new Image();
      image.sizes = sizes;
      image.srcset = srcset;
    }
  };
  const onIntent = (event: Event): void => {
    void warm(event.target).catch(() => undefined);
  };
  document.addEventListener("pointerover", onIntent, { passive: true });
  document.addEventListener("focusin", onIntent);
  document.addEventListener("touchstart", onIntent, { passive: true });
}

const UPDATE_CHECK_MS = 60_000;

function registerServiceWorker(): void {
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}

/** Pages, scripts, fonts and paintings answer from the device after the first visit (service-worker/sw.js). */
function setupServiceWorker(): void {
  if (!import.meta.env.PROD || !SQ_SERVICE_WORKER || !("serviceWorker" in navigator)) {
    return;
  }
  if (document.readyState === "complete") {
    registerServiceWorker();
  } else {
    window.addEventListener("load", registerServiceWorker, { once: true });
  }
  // Moving between pages never loads a document, so the browser never re-checks sw.js on its own; ask it to (at
  // most once a minute) so a deploy reaches someone who keeps the site open.
  let lastCheck = Date.now();
  document.addEventListener("astro:page-load", () => {
    if (Date.now() - lastCheck > UPDATE_CHECK_MS) {
      lastCheck = Date.now();
      void navigator.serviceWorker.getRegistration().then((registration) => registration?.update());
    }
  });
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  if (!connection?.saveData) {
    setupWarmUp();
  }
}

/** A page from a newer deploy needs that deploy's scripts, so it gets a full load instead of being swapped into a
 * document still running this one's. */
function setupBuildGuard(): void {
  document.addEventListener("astro:before-swap", (event) => {
    const next = event.newDocument.querySelector('meta[name="sq-build"]')?.getAttribute("content");
    if (next && next !== SQ_BUILD) {
      event.swap = () => location.assign(event.to.href);
    }
  });
}

/** Sign-in, sign-out and API links leave the site (Discord, Battle.net) or return data, so they get a full page
 * load instead of the in-page swap. Runs before the router's own click handler. */
function setupFullLoadLinks(): void {
  document.addEventListener(
    "click",
    (event) => {
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (link && /^\/(api|auth|schema|health)(\/|$)/.test(new URL(link.href).pathname)) {
        link.dataset.astroReload = "";
      }
    },
    { capture: true },
  );
}

onPage("body", (signal) => {
  for (const toggle of document.querySelectorAll<HTMLButtonElement>("[data-nav-toggle]")) {
    setupMenu(toggle, signal);
  }
  const toTop = document.querySelector<HTMLElement>("[data-to-top]");
  if (toTop) {
    setupToTop(toTop, signal);
  }
  if (document.querySelector("[data-officer-nav]")) {
    void syncOfficerNav();
  }
});
setupFullLoadLinks();
setupBuildGuard();
setupServiceWorker();
