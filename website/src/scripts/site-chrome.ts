// Shared page chrome on every page: the SideQuest nav (scripts/nav.ts), the back-to-top control, and (once per
// visit) the service worker, link warm-up and full loads for sign-in links.
import { setupNav } from "./nav";
import { onPage } from "./page";

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
  setupNav(signal);
  const toTop = document.querySelector<HTMLElement>("[data-to-top]");
  if (toTop) {
    setupToTop(toTop, signal);
  }
});
setupFullLoadLinks();
setupBuildGuard();
setupServiceWorker();
