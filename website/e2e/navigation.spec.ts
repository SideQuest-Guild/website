// Moving around the site: links change the page in place (no new document), through the desktop nav or the phone
// menu, the back button works, sign-in links leave the site, and the Officers link is for officers only.
import type { Page } from "@playwright/test";

import { EVENTS, LONG_TITLE, MEMBER, OFFICER } from "./data";
import { expect, test } from "./fixtures";

/** Follows a header link the way a visitor would on this screen size: straight from the nav, or via the Menu. */
async function navTo(page: Page, name: string): Promise<void> {
  const toggle = page.locator("[data-nav-toggle]").first();
  if (await toggle.isVisible()) {
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
  }
  await page.locator("header nav").first().getByRole("link", { name, exact: true }).click();
}

const sameDocument = (page: Page) => page.evaluate(() => "e2eDocument" in window && window.e2eDocument === true);

test("links change the page in place", async ({ page, site }) => {
  site.signIn(OFFICER);
  await page.goto("/");
  await page.evaluate(() => Object.assign(window, { e2eDocument: true }));

  await navTo(page, "Events");
  await expect(page).toHaveURL("/events/");
  await expect(page.getByRole("heading", { level: 1, name: "Events" })).toBeVisible();
  await expect(page.locator("#events-upcoming a.quest")).toHaveCount(2);
  await expect(page).toHaveTitle(/^Events/);

  await page.locator("#events-upcoming a.quest", { hasText: LONG_TITLE }).click();
  await expect(page.getByRole("heading", { level: 1, name: LONG_TITLE })).toBeVisible();
  await expect(page.getByText("Brannoc").first()).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL("/events/");
  await expect(page.locator("#events-upcoming a.quest")).toHaveCount(2);

  await navTo(page, "Addons");
  await expect(page.locator("#addons-list .tooltip-card")).toHaveCount(2);

  await navTo(page, "Account");
  await expect(page.locator("#account-name")).toHaveText(OFFICER.display_name);

  await navTo(page, "Officers");
  await expect(page.locator("#officers-body")).toBeVisible();

  await page.locator(".page-brand").first().click();
  await expect(page.locator(".hearth")).toHaveCount(2);

  expect(await sameDocument(page), "a link loaded a new document").toBe(true);
  // The phone menu closes once its link is followed.
  const toggle = page.locator("[data-nav-toggle]").first();
  if (await toggle.isVisible()) {
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
  }
});

test("pages keep working after leaving and coming back", async ({ page, site }) => {
  site.signIn(MEMBER);
  await page.goto("/events/");
  for (let round = 0; round < 3; round += 1) {
    await navTo(page, "Addons");
    await expect(page.locator("#addons-list .tooltip-card")).toHaveCount(2);
    await navTo(page, "Events");
    await expect(page.locator("#events-upcoming a.quest")).toHaveCount(2);
  }
  await page.getByRole("link", { name: "Raids", exact: true }).click();
  await expect(page).toHaveURL("/events/?kind=raid");
  await expect(page.locator("#events-upcoming a.quest")).toHaveCount(1);
});

test("sign-in leaves the site", async ({ page, site }) => {
  site.signIn(null);
  await page.goto("/account/");
  await page.getByRole("link", { name: "Sign in with Discord" }).first().click();
  await expect(page).toHaveURL("/auth/discord/login?next=/account/");
  await expect(page.getByText("auth stub")).toBeVisible();
});

for (const [who, me, shown] of [
  ["signed out", null, false],
  ["a member", MEMBER, false],
  ["an officer", OFFICER, true],
] as const) {
  test(`the Officers link is ${shown ? "shown" : "hidden"} for ${who}`, async ({ page, site }) => {
    site.signIn(me);
    await page.goto(`/events/detail/?id=${EVENTS[1]?.id}`);
    await page.waitForLoadState("networkidle");
    const link = page.locator("[data-officer-nav]").first();
    if (shown) {
      await expect(link).toBeAttached();
      await expect(page.locator("html")).toHaveClass(/officer/);
    } else {
      await expect(page.locator("html")).not.toHaveClass(/officer/);
    }
  });
}
