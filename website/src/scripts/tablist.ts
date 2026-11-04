// A roving-tabindex tablist (WAI-ARIA tabs): click or arrow-key between the visible tabs, Home/End jump to the ends.
// Shared by the page-level consoles (Account, Guild, Officers) and the officers' filter rows.

/** Wires every `[role="tab"]` in `container`; `onActivate` runs for each selection, including `select()` calls. */
export function setupTablist(
  container: HTMLElement,
  onActivate: (tab: HTMLButtonElement) => void,
): { select: (tab: HTMLButtonElement, opts?: { focus?: boolean }) => void } {
  const allTabs = (): HTMLButtonElement[] => Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'));

  function select(tab: HTMLButtonElement, { focus = false }: { focus?: boolean } = {}): void {
    for (const t of allTabs()) {
      const selected = t === tab;
      t.setAttribute("aria-selected", String(selected));
      t.tabIndex = selected ? 0 : -1;
    }
    if (focus) {
      tab.focus();
    }
    // A row that scrolls sideways (`.tabs-scroll` on phones) centres the chosen tab, so it's never left offscreen.
    // Only the row scrolls: scrollIntoView would also move the page.
    if (container.scrollWidth > container.clientWidth) {
      container.scrollTo({ left: tab.offsetLeft - (container.clientWidth - tab.offsetWidth) / 2 });
    }
    onActivate(tab);
  }

  for (const tab of allTabs()) {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", (ev) => {
      const visible = allTabs().filter((t) => !t.hidden);
      const i = visible.indexOf(tab);
      let next: number;
      if (ev.key === "ArrowRight") {
        next = (i + 1) % visible.length;
      } else if (ev.key === "ArrowLeft") {
        next = (i - 1 + visible.length) % visible.length;
      } else if (ev.key === "Home") {
        next = 0;
      } else if (ev.key === "End") {
        next = visible.length - 1;
      } else {
        return;
      }
      ev.preventDefault();
      select(visible[next]!, { focus: true });
    });
  }

  return { select };
}
