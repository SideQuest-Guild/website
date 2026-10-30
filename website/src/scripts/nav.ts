// The shared nav (SiteNav.astro): the Raids/Guild group panel, the account chip and its menu, and the phone/
// tablet sheet. Called once per page from site-chrome.ts's body setup; `signal` aborts just before the next
// ClientRouter swap (the nav itself is swapped content, so everything here is torn down and rebuilt per page).
import { ApiError, fetchMe, type Me } from "./api";

const EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)";
const OPEN_DELAY = 110;
const CLOSE_DELAY = 220;
const PANEL_MS = 200;
const ME_CACHE_KEY = "sq-me";
const OFFICER_FLAG = "sq-officer";

function reduceMotion(): boolean {
  return matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Caches just enough of `/api/me` to pre-paint the account chip next visit (SiteNav.astro's inline script).
 * Cleared on sign-out and whenever `/api/me` says signed out, so one person's name/avatar never shows for the
 * next (service-worker/sw.js applies the same rule to the pages' own data). */
function cacheMe(me: Me | null): void {
  try {
    if (me) {
      localStorage.setItem(ME_CACHE_KEY, JSON.stringify({ display_name: me.display_name, avatar_url: me.avatar_url }));
      if (me.is_officer) {
        localStorage.setItem(OFFICER_FLAG, "1");
      } else {
        localStorage.removeItem(OFFICER_FLAG);
      }
    } else {
      localStorage.removeItem(ME_CACHE_KEY);
      localStorage.removeItem(OFFICER_FLAG);
    }
  } catch {
    // Storage blocked: the chip and the Officers link just follow /api/me without the pre-paint.
  }
}

function renderAvatar(container: HTMLElement, me: Me): void {
  container.replaceChildren();
  if (me.avatar_url) {
    const img = document.createElement("img");
    img.src = me.avatar_url;
    img.alt = "";
    img.width = 28;
    img.height = 28;
    container.append(img);
  } else {
    container.textContent = (me.display_name.trim().charAt(0) || "?").toUpperCase();
  }
}

/** Shows the signed-in or signed-out account chip (bar and phone sheet share the same data attributes), the
 * Officers menu entry for officers only, and refreshes the cached answer for next visit's pre-paint. */
async function syncAccount(root: ParentNode): Promise<void> {
  let me: Me | null;
  try {
    me = await fetchMe();
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      return; // Offline: keep whatever the cache already painted.
    }
    me = null;
  }
  document.documentElement.classList.toggle("member", Boolean(me));
  document.documentElement.classList.toggle("officer", Boolean(me?.is_officer));
  cacheMe(me);

  for (const el of root.querySelectorAll<HTMLElement>("[data-account-signed-out]")) {
    el.hidden = Boolean(me);
  }
  for (const el of root.querySelectorAll<HTMLElement>("[data-account-signed-in]")) {
    el.hidden = !me;
  }
  for (const el of root.querySelectorAll<HTMLElement>("[data-officer-nav]")) {
    el.hidden = !me?.is_officer;
  }
  if (me) {
    for (const nameEl of root.querySelectorAll<HTMLElement>("[data-account-name]")) {
      nameEl.textContent = me.display_name;
    }
    for (const avatarEl of root.querySelectorAll<HTMLElement>("[data-account-avatar]")) {
      renderAvatar(avatarEl, me);
    }
  }
}

/** The Raids/Guild disclosure buttons and the one panel that slides and resizes under whichever is open. */
function setupGroupPanel(nav: HTMLElement, signal: AbortSignal): void {
  const navBarEl = nav.querySelector<HTMLElement>("[data-nav-bar]");
  const panelEl = nav.querySelector<HTMLElement>("[data-nav-panel]");
  const triggers = Array.from(nav.querySelectorAll<HTMLButtonElement>("[data-nav-trigger]"));
  if (!navBarEl || !panelEl || triggers.length === 0) {
    return;
  }
  const navBar: HTMLElement = navBarEl;
  const panel: HTMLElement = panelEl;
  const panes = new Map<string, HTMLElement>();
  for (const pane of panel.querySelectorAll<HTMLElement>("[data-pane]")) {
    panes.set(pane.dataset.pane ?? "", pane);
  }
  const order = triggers.map((t) => t.dataset.navTrigger ?? "");

  let openGroup: string | null = null;
  let openTrigger: HTMLButtonElement | null = null;
  let openTimer = 0;
  let closeTimer = 0;
  /** Whether the open panel came from hover intent (a click then pins it open) or a click/keyboard. */
  let openedByHover = false;
  // Timers outlive the page they were set on; never let one fire into the next page after a swap.
  signal.addEventListener("abort", () => {
    window.clearTimeout(openTimer);
    window.clearTimeout(closeTimer);
  });
  const animations = new Map<HTMLElement, Animation>();

  const scheduleHide = (): void => {
    window.setTimeout(
      () => {
        if (openGroup === null) {
          panel.hidden = true;
          panel.classList.remove("is-sized");
        }
      },
      reduceMotion() ? 0 : PANEL_MS,
    );
  };

  function position(trigger: HTMLElement, width: number, height: number): void {
    const barRect = navBar.getBoundingClientRect();
    const trigRect = trigger.getBoundingClientRect();
    const maxLeft = Math.max(0, barRect.width - width);
    const left = Math.min(Math.max(trigRect.left - barRect.left, 0), maxLeft);
    panel.style.width = `${width}px`;
    panel.style.height = `${height}px`;
    panel.style.left = `${left}px`;
    const notch = panel.querySelector<HTMLElement>(".nav-panel-notch");
    if (notch) {
      notch.style.left = `${trigRect.left - barRect.left - left + trigRect.width / 2}px`;
    }
  }

  function crossfade(pane: HTMLElement, leaving: HTMLElement | null, dir: 1 | -1): void {
    animations.get(pane)?.cancel();
    if (leaving) {
      animations.get(leaving)?.cancel();
      leaving.removeAttribute("data-active");
    }
    if (reduceMotion()) {
      pane.setAttribute("data-active", "");
      return;
    }
    const dist = 18;
    if (leaving) {
      // CSS hides a pane the instant `data-active` is gone; keep it visible until its fade-out finishes.
      leaving.style.visibility = "visible";
      const leaveAnim = leaving.animate(
        [
          { opacity: 1, transform: "translateX(0)" },
          { opacity: 0, transform: `translateX(${-dir * dist}px)` },
        ],
        { duration: PANEL_MS, easing: EASE, fill: "forwards" },
      );
      leaveAnim.addEventListener("finish", () => {
        leaving.style.visibility = "";
      });
      animations.set(leaving, leaveAnim);
    }
    pane.setAttribute("data-active", "");
    const enterAnim = pane.animate(
      [
        { opacity: 0, transform: `translateX(${dir * dist}px)` },
        { opacity: 1, transform: "translateX(0)" },
      ],
      { duration: PANEL_MS, easing: EASE, fill: "forwards" },
    );
    animations.set(pane, enterAnim);
  }

  function open(trigger: HTMLButtonElement, group: string): void {
    const pane = panes.get(group);
    if (!pane) {
      return;
    }
    window.clearTimeout(closeTimer);
    window.clearTimeout(openTimer);
    const firstOpen = panel.hidden;
    const dir: 1 | -1 = order.indexOf(group) >= order.indexOf(openGroup ?? group) ? 1 : -1;
    const leaving = openGroup && openGroup !== group ? (panes.get(openGroup) ?? null) : null;

    if (firstOpen) {
      panel.hidden = false;
    }
    const width = Number(pane.dataset.w) || 320;
    // Measure the pane at its own fixed width: the panel's width may be mid-tween (or unset on first open), and
    // a pane laid out at that width wraps differently and reports the wrong height.
    pane.style.width = `${width}px`;
    position(trigger, width, pane.offsetHeight);
    if (firstOpen) {
      // The first open sets size instantly (no tween from zero); switching groups afterward tweens it.
      requestAnimationFrame(() => requestAnimationFrame(() => panel.classList.add("is-sized")));
    }
    crossfade(pane, leaving, dir);
    panel.classList.add("is-open");

    for (const t of triggers) {
      t.setAttribute("aria-expanded", String(t === trigger));
    }
    openGroup = group;
    openTrigger = trigger;
  }

  function close({ refocus = false }: { refocus?: boolean } = {}): void {
    if (openGroup === null) {
      return;
    }
    const trigger = openTrigger;
    panel.classList.remove("is-open");
    for (const t of triggers) {
      t.setAttribute("aria-expanded", "false");
    }
    openGroup = null;
    openTrigger = null;
    scheduleHide();
    if (refocus) {
      trigger?.focus();
    }
  }

  for (const trigger of triggers) {
    const group = trigger.dataset.navTrigger ?? "";
    // Hover intent starts on movement, not `pointerenter`: after an in-place page swap the browser re-checks what
    // sits under a still pointer and fires `pointerenter` on whatever is there, which would pop a panel open on
    // its own a moment after the visitor clicked a link.
    trigger.addEventListener(
      "pointermove",
      (event) => {
        if (event.pointerType === "touch" || openGroup === group || openTimer !== 0) {
          return;
        }
        window.clearTimeout(closeTimer);
        openTimer = window.setTimeout(() => {
          openTimer = 0;
          open(trigger, group);
          openedByHover = true;
        }, OPEN_DELAY);
      },
      { signal },
    );
    trigger.addEventListener(
      "pointerleave",
      (event) => {
        if (event.pointerType === "touch") {
          return;
        }
        window.clearTimeout(openTimer);
        openTimer = 0;
        closeTimer = window.setTimeout(() => {
          if (!panel.matches(":hover")) {
            close();
          }
        }, CLOSE_DELAY);
      },
      { signal },
    );
    // A mouse click also focuses the button; opening here too would race the click handler below (focus fires
    // first, so a click toggling "already open" would immediately close what the click meant to open). Keyboard
    // (:focus-visible) is the only case this handler needs to cover.
    trigger.addEventListener(
      "focus",
      () => {
        if (!trigger.matches(":focus-visible")) {
          return;
        }
        window.clearTimeout(closeTimer);
        open(trigger, group);
        openedByHover = false;
      },
      { signal },
    );
    trigger.addEventListener(
      "click",
      () => {
        window.clearTimeout(closeTimer);
        window.clearTimeout(openTimer);
        openTimer = 0;
        // Hover usually opens the panel just before the click lands; that click means "keep it open", not
        // "close it". Only a click on a panel that was already pinned open by a click or the keyboard closes it.
        if (openGroup === group && !openedByHover) {
          close();
        } else {
          open(trigger, group);
          openedByHover = false;
        }
      },
      { signal },
    );
    // Tab from a trigger whose panel is open jumps straight into the panel (the panel isn't the trigger's next
    // DOM sibling, since both triggers share it), instead of landing on the other trigger first.
    trigger.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Tab" && !event.shiftKey && openGroup === group) {
          const first = panes.get(group)?.querySelector<HTMLElement>("a, button");
          if (first) {
            event.preventDefault();
            first.focus();
          }
        }
      },
      { signal },
    );
  }

  panel.addEventListener("pointerenter", () => window.clearTimeout(closeTimer), { signal });
  panel.addEventListener(
    "pointerleave",
    () => {
      closeTimer = window.setTimeout(() => close(), CLOSE_DELAY);
    },
    { signal },
  );
  // Leaving the last link forward returns to the bar; leaving the first link backward returns to the trigger.
  panel.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "Tab" || openGroup === null) {
        return;
      }
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>("a, button"));
      const index = focusable.indexOf(document.activeElement as HTMLElement);
      if (index === -1) {
        return;
      }
      if (!event.shiftKey && index === focusable.length - 1) {
        const group = openGroup;
        const next = triggers[order.indexOf(group) + 1];
        close();
        if (next) {
          event.preventDefault();
          next.focus();
        }
      } else if (event.shiftKey && index === 0) {
        event.preventDefault();
        openTrigger?.focus();
      }
    },
    { signal },
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape" && openGroup !== null) {
        close({ refocus: true });
      }
    },
    { signal },
  );
  document.addEventListener(
    "click",
    (event) => {
      if (openGroup === null || !(event.target instanceof Node)) {
        return;
      }
      if (!panel.contains(event.target) && !triggers.some((t) => t.contains(event.target as Node))) {
        close();
      }
    },
    { signal },
  );
}

/** The account chip's own small menu (Your account / Officers / Sign out): click to open, Escape and outside
 * click to close, focus returns to the chip. */
function setupAccountMenu(nav: HTMLElement, signal: AbortSignal): void {
  const trigger = nav.querySelector<HTMLButtonElement>("[data-account-signed-in]");
  const menu = nav.querySelector<HTMLElement>("[data-account-menu]");
  if (!trigger || !menu) {
    return;
  }
  const setOpen = (open: boolean): void => {
    trigger.setAttribute("aria-expanded", String(open));
    menu.hidden = !open;
  };
  trigger.addEventListener("click", () => setOpen(trigger.getAttribute("aria-expanded") !== "true"));
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape" && trigger.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        trigger.focus();
      }
    },
    { signal },
  );
  document.addEventListener(
    "click",
    (event) => {
      if (
        trigger.getAttribute("aria-expanded") === "true" &&
        event.target instanceof Node &&
        !trigger.contains(event.target) &&
        !menu.contains(event.target)
      ) {
        setOpen(false);
      }
    },
    { signal },
  );
}

/** Sign out: the API's own `/auth/logout`, then a full load (clearing every in-memory and cached answer at once)
 * instead of trying to hand-patch the chip back to signed out. */
function setupSignOut(nav: HTMLElement): void {
  for (const button of nav.querySelectorAll<HTMLButtonElement>("[data-sign-out]")) {
    button.addEventListener("click", () => {
      button.disabled = true;
      cacheMe(null);
      fetch("/auth/logout", { method: "POST", credentials: "same-origin" })
        .catch(() => undefined)
        .finally(() => location.reload());
    });
  }
}

/** The phone/tablet sheet behind the Menu button: slides in full-height, traps focus, locks scroll, and closes
 * on Escape, the close button, or a link (which also navigates). */
function setupSheet(signal: AbortSignal): void {
  const toggle = document.querySelector<HTMLButtonElement>("[data-nav-toggle]");
  const sheet = document.querySelector<HTMLElement>("[data-nav-sheet]");
  const closeBtn = sheet?.querySelector<HTMLButtonElement>("[data-nav-sheet-close]");
  if (!toggle || !sheet || !closeBtn) {
    return;
  }
  const label = toggle.querySelector<HTMLElement>("[data-nav-label]");
  let lastFocus: HTMLElement | null = null;

  const setOpen = (open: boolean): void => {
    toggle.setAttribute("aria-expanded", String(open));
    if (label) {
      label.textContent = open ? "Close" : "Menu";
    }
    if (open) {
      lastFocus = document.activeElement as HTMLElement | null;
      sheet.hidden = false;
      document.documentElement.classList.add("nav-sheet-open");
      requestAnimationFrame(() => sheet.classList.add("is-open"));
      closeBtn.focus();
    } else {
      sheet.classList.remove("is-open");
      document.documentElement.classList.remove("nav-sheet-open");
      window.setTimeout(
        () => {
          sheet.hidden = true;
        },
        reduceMotion() ? 0 : PANEL_MS,
      );
      (lastFocus ?? toggle).focus();
    }
  };

  toggle.addEventListener("click", () => setOpen(toggle.getAttribute("aria-expanded") !== "true"));
  closeBtn.addEventListener("click", () => setOpen(false));
  sheet.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("a")) {
      setOpen(false);
    }
  });
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        return;
      }
      if (event.key !== "Tab" || toggle.getAttribute("aria-expanded") !== "true") {
        return;
      }
      const focusable = Array.from(sheet.querySelectorAll<HTMLElement>("a, button:not([disabled])")).filter(
        (el) => el.offsetParent !== null,
      );
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
    { signal },
  );
  signal.addEventListener("abort", () => document.documentElement.classList.remove("nav-sheet-open"));
}

/** ArrowLeft/ArrowRight move focus between the bar's own items (Events, Raids, Guild, Addons, Discord, the
 * account chip); Tab keeps the browser's normal order. */
function setupRoving(nav: HTMLElement, signal: AbortSignal): void {
  nav.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      const items = Array.from(nav.querySelectorAll<HTMLElement>("[data-nav-roving], .nav-discord")).filter(
        (el) => el.offsetParent !== null,
      );
      const accountChip = nav.querySelector<HTMLElement>(
        "[data-account-signed-in]:not([hidden]), [data-account-signed-out]:not([hidden])",
      );
      if (accountChip && !items.includes(accountChip)) {
        items.push(accountChip);
      }
      const index = items.indexOf(document.activeElement as HTMLElement);
      if (index === -1) {
        return;
      }
      event.preventDefault();
      const next =
        event.key === "ArrowRight"
          ? items[(index + 1) % items.length]
          : items[(index - 1 + items.length) % items.length];
      next.focus();
    },
    { signal },
  );
}

export function setupNav(signal: AbortSignal): void {
  const nav = document.querySelector<HTMLElement>("[data-nav]");
  if (!nav) {
    return;
  }
  setupGroupPanel(nav, signal);
  setupAccountMenu(nav, signal);
  setupSignOut(nav);
  setupSheet(signal);
  setupRoving(nav, signal);
  void syncAccount(document);
}
