// Shared page chrome on every page: the narrow-screen Menu disclosure, the back-to-top control, and the
// officer-only Officers nav link.
import { ApiError, fetchMe } from "./api";

const MOBILE_QUERY = window.matchMedia("(max-width: 900px)");

function setupMenu(toggle: HTMLButtonElement): void {
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
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false);
      toggle.focus();
    }
  });
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Node && !toggle.contains(target) && !list.contains(target)) {
      setOpen(false);
    }
  });
  MOBILE_QUERY.addEventListener("change", () => setOpen(false));
}

function setupToTop(link: HTMLElement): void {
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
    { passive: true },
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
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  if (!connection?.saveData) {
    setupWarmUp();
  }
}

for (const toggle of document.querySelectorAll<HTMLButtonElement>("[data-nav-toggle]")) {
  setupMenu(toggle);
}
const toTop = document.querySelector<HTMLElement>("[data-to-top]");
if (toTop) {
  setupToTop(toTop);
}
if (document.querySelector("[data-officer-nav]")) {
  void syncOfficerNav();
}
setupServiceWorker();
