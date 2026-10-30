// Every page, at every device size, signed out and signed in: nothing scrolls sideways or sits past the screen
// edge, the painting spans the screen, every picture on screen loads, and the header fits. A full-page screenshot
// of each is attached to the report for a human look.
import type { Page } from "@playwright/test";

import { EVENTS, GM, HEROES } from "./data";
import { expect, test } from "./fixtures";

const PAGES = [
  { name: "home", path: "/" },
  { name: "events", path: "/events/" },
  { name: "raid", path: `/events/detail/?id=${EVENTS[0]?.id}` },
  { name: "heroes", path: "/heroes/" },
  { name: "hero", path: `/heroes/member/?id=${HEROES[0]?.member_id}` },
  { name: "addons", path: "/addons/" },
  { name: "raids", path: "/raids/" },
  { name: "account", path: "/account/" },
  { name: "officers", path: "/officers/#members" },
  { name: "officers attendance", path: "/officers/#attendance" },
  { name: "rules", path: "/rules/" },
  { name: "privacy", path: "/privacy/" },
  { name: "terms", path: "/terms/" },
  { name: "not found", path: "/no-such-page/", nav: false },
];

// Text and controls a visitor reads or taps; decorative layers may bleed past the edge on purpose.
const CONTENT = "h1, h2, h3, p, li, a, button, input, select, textarea, label, img, .chamber";

type Offender = { what: string; left: number; right: number };

async function offScreen(page: Page): Promise<{ width: number; scrollWidth: number; offenders: Offender[] }> {
  return page.evaluate((selector) => {
    const width = document.documentElement.clientWidth;
    const offenders: Offender[] = [];
    for (const el of document.querySelectorAll<HTMLElement>(selector)) {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (rect.width === 0 || rect.height === 0 || style.visibility === "hidden" || el.closest("[hidden], .sr-only")) {
        continue;
      }
      if (rect.left < -1 || rect.right > width + 1) {
        const label = `${el.tagName.toLowerCase()}${el.className ? `.${String(el.className).trim().replace(/\s+/g, ".")}` : ""}`;
        offenders.push({ what: label, left: Math.round(rect.left), right: Math.round(rect.right) });
      }
    }
    return { width, scrollWidth: document.documentElement.scrollWidth, offenders };
  }, CONTENT);
}

for (const state of ["signed out", "signed in"] as const) {
  test.describe(state, () => {
    test.use({ reducedMotion: "reduce" });

    for (const { name, path } of PAGES) {
      test(`${name} fits the screen`, async ({ page, site }, testInfo) => {
        site.signIn(state === "signed in" ? GM : null);
        await page.goto(path);
        await page.waitForLoadState("networkidle");

        const layout = await offScreen(page);
        expect(layout.scrollWidth, "page scrolls sideways").toBeLessThanOrEqual(layout.width);
        expect(layout.offenders, "content past the screen edge").toEqual([]);

        // The hero or room painting is the page's backdrop: it must reach both edges.
        const painting = page.locator("img.hero-art, img.room-art").first();
        if ((await painting.count()) > 0) {
          const box = await painting.boundingBox();
          expect(box?.x ?? 99, "painting starts at the left edge").toBeLessThanOrEqual(0.5);
          expect((box?.x ?? 0) + (box?.width ?? 0), "painting reaches the right edge").toBeGreaterThanOrEqual(
            layout.width - 0.5,
          );
        }

        const broken = await page.evaluate(() =>
          [...document.images]
            .filter((img) => {
              const rect = img.getBoundingClientRect();
              const onScreen = rect.width > 0 && rect.bottom > 0 && rect.top < innerHeight;
              return onScreen && (!img.complete || img.naturalWidth === 0);
            })
            .map((img) => img.currentSrc || img.src),
        );
        expect(broken, "pictures on screen that didn't load").toEqual([]);

        // The 404 has no header, only its way back.
        if (PAGES.find((p) => p.path === path)?.nav === false) {
          await expect(page.getByRole("link", { name: "Back to SideQuest" })).toBeVisible();
        } else {
          const header = page.locator("header").first();
          const narrow = layout.width <= 900;
          await expect(header.locator(narrow ? "[data-nav-toggle]" : 'nav a[href="/events/"]').first()).toBeVisible();
        }

        // First screen as a visitor sees it, and the whole page (lazy pictures below the fold stay unloaded).
        for (const [file, fullPage] of [
          ["screen.png", false],
          ["page.png", true],
        ] as const) {
          const shot = testInfo.outputPath(file);
          await page.screenshot({ path: shot, fullPage });
          await testInfo.attach(`${name} (${state}) ${fullPage ? "page" : "screen"}`, {
            path: shot,
            contentType: "image/png",
          });
        }
      });
    }
  });
}

// The officers console at the comp's own width, where the Addon Crate once ran off the right edge with nothing in it.
test.describe("wide desktop officers console", () => {
  test.use({ viewport: { width: 1568, height: 980 }, reducedMotion: "reduce" });

  const tabs = [
    { tab: "events", empty: false },
    { tab: "addons", empty: false },
    { tab: "addons", empty: true },
    { tab: "recruiting", empty: false },
    { tab: "attendance", empty: false },
    { tab: "members", empty: false },
    { tab: "log", empty: false },
    { tab: "moderation", empty: false },
  ];
  for (const { tab, empty } of tabs) {
    test(`${tab}${empty ? " (empty crate)" : ""} fits`, async ({ page, site }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop", "a desktop width");
      site.signIn(GM);
      if (empty) {
        site.addons([]);
      }
      await page.goto(`/officers/#${tab}`);
      await expect(page.locator(`#tab-${tab}`)).toHaveAttribute("aria-selected", "true");
      await page.waitForLoadState("networkidle");

      const layout = await offScreen(page);
      expect(layout.scrollWidth, "page scrolls sideways").toBeLessThanOrEqual(layout.width);
      expect(layout.offenders, "content past the screen edge").toEqual([]);

      // Chambers side by side start level; a chamber alone in its tab spans the tab instead of half of it.
      const panel = page.locator(`#panel-${tab}`);
      const geometry = await panel.evaluate((root) => ({
        width: root.getBoundingClientRect().width,
        pairs: [...root.querySelectorAll(".chamber-pair")].map((pair) =>
          [...pair.children].map((child) => Math.round(child.getBoundingClientRect().top)),
        ),
        singles: [...root.querySelectorAll(":scope > .chamber")].map((c) => c.getBoundingClientRect().width),
      }));
      for (const tops of geometry.pairs) {
        expect(new Set(tops).size, `paired chambers start at different heights: ${tops.join(", ")}`).toBe(1);
      }
      for (const width of geometry.singles) {
        expect(width, "a lone chamber spans its tab").toBeGreaterThan(geometry.width * 0.95);
      }

      const shot = testInfo.outputPath("page.png");
      await page.screenshot({ path: shot, fullPage: true });
      await testInfo.attach(`officers #${tab}${empty ? " empty" : ""}`, { path: shot, contentType: "image/png" });
    });
  }
});
