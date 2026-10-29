// After one visit the service worker holds every page: with the network gone, the site still opens and moves
// between pages. (The rest of the suite blocks the worker so the API mock sees every request.)
import { expect, test } from "./fixtures";

test.use({ serviceWorkers: "allow" });

test("pages open offline after the first visit", async ({ page, context, site }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one engine is enough for the worker's cache");
  site.signIn(null);
  await page.goto("/events/");
  await page.waitForFunction(async () => {
    const registration = await navigator.serviceWorker.ready;
    return (
      registration.active?.state === "activated" && (await caches.keys()).some((name) => name.startsWith("sq-pages-"))
    );
  });

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Events" })).toBeVisible();
  await page.locator("header nav").getByRole("link", { name: "Addons", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Addons" })).toBeVisible();
  // The page's own scripts ran from the worker's cache (the API mock still answers the worker's requests).
  await expect(page.locator("#addons-list .tooltip-card")).toHaveCount(2);
  site.errors.length = 0; // the paintings first loaded before the worker took over, so offline they fail to load
});
