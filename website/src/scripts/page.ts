// The site moves between pages with Astro's ClientRouter: following a link swaps the page body instead of loading a
// new document, and a page's script module runs only once per visit to the site. Each page script therefore puts
// its work in `onPage`, which runs it now (a full page load) and again after every swap that lands on a page
// containing `root`, never twice for the same page. `signal` aborts just before the page is swapped away: pass it to
// window/document listeners and use it to stop timers and observers, so nothing outlives its page.
const started = new WeakSet<Element>();

export function onPage(root: string, setup: (signal: AbortSignal) => void): void {
  const start = (): void => {
    const element = document.querySelector(root);
    if (!element || started.has(element)) {
      return;
    }
    started.add(element);
    const controller = new AbortController();
    document.addEventListener("astro:before-swap", () => controller.abort(), { once: true });
    setup(controller.signal);
  };
  start();
  // Astro fires this after every swap (and once more after the first full load, which `started` ignores).
  document.addEventListener("astro:page-load", start);
}
