// Shared page chrome on every page: the narrow-screen Menu disclosure and the back-to-top control.

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

for (const toggle of document.querySelectorAll<HTMLButtonElement>("[data-nav-toggle]")) {
  setupMenu(toggle);
}
const toTop = document.querySelector<HTMLElement>("[data-to-top]");
if (toTop) {
  setupToTop(toTop);
}
