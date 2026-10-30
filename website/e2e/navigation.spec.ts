// Moving around the site: the nav bar and its one group panel (desktop) or the full-height sheet (phone/tablet),
// the account chip and its menu, sign-in/officer visibility, and that links change the page in place (no new
// document).
import type { Page } from "@playwright/test";

import { EVENTS, MEMBER, OFFICER } from "./data";
import { expect, test } from "./fixtures";

const sameDocument = (page: Page) => page.evaluate(() => "e2eDocument" in window && window.e2eDocument === true);

/** True on phone/tablet viewports, where the bar collapses behind the Menu button. */
async function isNarrow(page: Page): Promise<boolean> {
  return page.locator("[data-nav-toggle]").first().isVisible();
}

async function openSheet(page: Page): Promise<void> {
  const sheet = page.locator("[data-nav-sheet]");
  if (!(await sheet.isVisible())) {
    await page.locator("[data-nav-toggle]").first().click();
    await expect(sheet).toBeVisible();
  }
}

/** Follows a plain bar link (Events, Addons) the way a visitor would on this screen size. */
async function navToPlain(page: Page, name: string): Promise<void> {
  if (await isNarrow(page)) {
    await openSheet(page);
    await page.locator("[data-nav-sheet]").getByRole("link", { name, exact: true }).click();
    return;
  }
  await page.locator("[data-nav-bar]").getByRole("link", { name, exact: true }).click();
}

/** Follows a Raids or Guild group entry: opens the desktop panel or the sheet's matching section first. */
async function navToGroup(page: Page, group: "raids" | "guild", name: string): Promise<void> {
  // Panel/sheet entries carry their description in the same link's accessible name (icon + name + desc), so an
  // exact match on just the visible name never matches; a substring match does.
  if (await isNarrow(page)) {
    await openSheet(page);
    await page.locator("[data-nav-sheet]").getByRole("link", { name }).click();
    return;
  }
  const trigger = page.locator(`[data-nav-trigger="${group}"]`);
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await page.locator("[data-nav-panel]").getByRole("link", { name }).click();
}

/** Opens the account chip's menu (bar, every viewport) and follows a link or button inside it. */
async function navToAccount(page: Page, name: string): Promise<void> {
  // The bar carries both chips (signed in, signed out) and only one shows; the sheet repeats the signed-in ones.
  const chip = page
    .locator(".nav-aside")
    .locator("[data-account-signed-in], [data-account-signed-out]")
    .filter({ visible: true });
  await chip.click();
  const menu = page.locator("[data-account-menu]");
  await expect(menu).toBeVisible();
  await menu.getByRole("link", { name, exact: true }).click();
}

test("every destination is reachable from the bar", async ({ page, site }) => {
  site.signIn(OFFICER);
  await page.goto("/");
  await page.evaluate(() => Object.assign(window, { e2eDocument: true }));

  await navToPlain(page, "Events");
  await expect(page).toHaveURL("/events/");

  await navToGroup(page, "raids", "How raid nights work");
  await expect(page).toHaveURL("/raids/");

  await navToGroup(page, "raids", "Loot ledger");
  await expect(page).toHaveURL("/ledger/");

  await navToGroup(page, "raids", "Upcoming raids");
  await expect(page).toHaveURL("/events/?kind=raid");

  await navToGroup(page, "guild", "Hall of Heroes");
  await expect(page).toHaveURL("/heroes/");

  await navToGroup(page, "guild", "Roster and crafters");
  // The guild page names its open tab in the hash (#roster by default).
  await expect(page).toHaveURL(/\/guild\/(#[\w-]+)?$/);

  await navToGroup(page, "guild", "How we play");
  await expect(page).toHaveURL("/#how-we-play");

  await navToGroup(page, "guild", "Guild rules");
  await expect(page).toHaveURL("/rules/");

  await navToPlain(page, "Addons");
  await expect(page).toHaveURL("/addons/");

  await navToAccount(page, "Your account");
  await expect(page).toHaveURL("/account/");

  await navToAccount(page, "Officers");
  // Like the guild page, the officers console names its open tab in the hash (#events by default).
  await expect(page).toHaveURL(/\/officers\/(#[\w-]+)?$/);

  expect(await sameDocument(page), "a link loaded a new document").toBe(true);
  // The phone sheet closes once its link is followed.
  const sheet = page.locator("[data-nav-sheet]");
  if (await isNarrow(page)) {
    await expect(sheet).toBeHidden();
  }
});

test.describe("desktop group panel", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("hovering Raids opens the panel; moving to Guild moves the same panel", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/events/");

    const raids = page.getByRole("button", { name: "Raids", exact: true });
    const guild = page.getByRole("button", { name: "Guild", exact: true });
    const panel = page.locator("[data-nav-panel]");

    await raids.hover();
    await expect(panel).toBeVisible();
    await expect(raids).toHaveAttribute("aria-expanded", "true");
    await expect(panel.getByRole("link", { name: "How raid nights work" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Loot ledger" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Upcoming raids" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Hall of Heroes" })).toBeHidden();
    const panelId = await panel.evaluate((el) => el.id);
    const raidsBox = await panel.boundingBox();

    await guild.hover();
    await expect(guild).toHaveAttribute("aria-expanded", "true");
    await expect(raids).toHaveAttribute("aria-expanded", "false");
    // Still the one shared panel element, not a second one.
    await expect(page.locator(`#${panelId}`)).toHaveCount(1);
    await expect(panel.getByRole("link", { name: "Hall of Heroes" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Roster and crafters" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "How we play" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Guild rules" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "How raid nights work" })).toBeHidden();
    await expect.poll(async () => (await panel.boundingBox())?.x).not.toBe(raidsBox?.x);
    await expect.poll(async () => (await panel.boundingBox())?.height).not.toBe(raidsBox?.height);
  });

  test("Escape closes the panel and returns focus to the trigger", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/");

    const raids = page.getByRole("button", { name: "Raids", exact: true });
    await raids.focus();
    const panel = page.locator("[data-nav-panel]");
    await expect(panel).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(raids).toBeFocused();
  });

  test("a panel link navigates in place", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/");
    await page.evaluate(() => Object.assign(window, { e2eDocument: true }));

    await page.getByRole("button", { name: "Raids", exact: true }).focus();
    await page.locator("[data-nav-panel]").getByRole("link", { name: "Loot ledger" }).click();
    await expect(page).toHaveURL("/ledger/");
    expect(await sameDocument(page), "a link loaded a new document").toBe(true);
  });

  test("the Raids trigger is current on the ledger page", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/ledger/");
    await expect(page.getByRole("button", { name: "Raids", exact: true })).toHaveAttribute("aria-current", "page");
  });

  test("the Guild trigger is current on the rules page", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/rules/");
    await expect(page.getByRole("button", { name: "Guild", exact: true })).toHaveAttribute("aria-current", "page");
  });
});

test("the phone menu opens the sheet; a link navigates in place and the sheet closes", async ({ page, site }) => {
  site.signIn(MEMBER);
  await page.goto("/");
  await page.evaluate(() => Object.assign(window, { e2eDocument: true }));
  const toggle = page.locator("[data-nav-toggle]").first();
  test.skip(!(await toggle.isVisible()), "desktop: the bar doesn't collapse behind a Menu button");

  await toggle.click();
  const sheet = page.locator("[data-nav-sheet]");
  await expect(sheet).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");

  await sheet.getByRole("link", { name: "Addons", exact: true }).click();
  await expect(page).toHaveURL("/addons/");
  await expect(sheet).toBeHidden();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(await sameDocument(page), "a link loaded a new document").toBe(true);
});

test("pages keep working after leaving and coming back", async ({ page, site }) => {
  site.signIn(MEMBER);
  await page.goto("/events/");
  for (let round = 0; round < 3; round += 1) {
    await navToPlain(page, "Addons");
    await expect(page.locator("#addons-list .tooltip-card")).toHaveCount(2);
    await navToPlain(page, "Events");
    await expect(page.locator("#events-upcoming a.quest")).toHaveCount(2);
  }
  await page.locator("#kind-filter-list").getByRole("link", { name: "Raids", exact: true }).click();
  await expect(page).toHaveURL("/events/?kind=raid");
  await expect(page.locator("#events-upcoming a.quest")).toHaveCount(1);
});

test("the full nav flow keeps working after leaving and coming back", async ({ page, site }) => {
  site.signIn(MEMBER);
  await page.goto("/events/");
  await page.evaluate(() => Object.assign(window, { e2eDocument: true }));

  await navToGroup(page, "raids", "Loot ledger");
  await expect(page).toHaveURL("/ledger/");
  await navToGroup(page, "guild", "Hall of Heroes");
  await expect(page).toHaveURL("/heroes/");
  await navToGroup(page, "raids", "How raid nights work");
  await expect(page).toHaveURL("/raids/");

  expect(await sameDocument(page), "a link loaded a new document").toBe(true);
});

test("the API reference keeps working after leaving and coming back", async ({ page, site }) => {
  site.signIn(null);
  await page.goto("/");
  await page.evaluate(() => Object.assign(window, { e2eDocument: true }));

  await page.locator("footer").getByRole("link", { name: "API", exact: true }).click();
  await expect(page).toHaveURL("/api-reference/");
  // Narrow viewports collapse each tag's operations behind "Show More"; "SideQuest Guild API" is Scalar's own
  // document title, rendered either way, so it proves the spec loaded without depending on that collapse state.
  await expect(page.getByRole("heading", { name: "SideQuest Guild API" })).toBeVisible();

  await navToPlain(page, "Events");
  await expect(page).toHaveURL("/events/");

  await page.goBack();
  // Scalar adds its own hash as sections scroll into view; the path, not the hash, is what proves the router
  // actually came back here instead of reloading a stale history entry.
  await expect(page).toHaveURL(/\/api-reference\/(#.*)?$/);
  // The lazy-loaded Scalar chunk (service-worker/integration.mjs excludes it from the precache) re-parses from
  // scratch here; under parallel test load that can take longer than the default assertion timeout.
  await expect(page.getByRole("heading", { name: "SideQuest Guild API" })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".t-doc__sidebar")).toBeAttached();

  expect(await sameDocument(page), "a link loaded a new document").toBe(true);
});

test("sign-in leaves the site", async ({ page, site }) => {
  site.signIn(null);
  await page.goto("/account/");
  await page.getByRole("link", { name: "Sign in with Discord" }).first().click();
  await expect(page).toHaveURL("/auth/discord/login?next=/account/");
  await expect(page.getByText("auth stub")).toBeVisible();
});

test("signed out, the nav shows Sign in", async ({ page, site }) => {
  site.signIn(null);
  await page.goto("/");
  await expect(page.locator("[data-account-signed-out]").first()).toBeVisible();
  await expect(page.locator("[data-account-signed-out]").first()).toHaveText("Sign in");
  await expect(page.locator("[data-account-signed-in]").first()).toBeHidden();
});

for (const [who, me, officerShown] of [
  ["a member", MEMBER, false],
  ["an officer", OFFICER, true],
] as const) {
  test(`the account menu shows Officers only for ${who}`, async ({ page, site }) => {
    site.signIn(me);
    await page.goto(`/events/detail/?id=${EVENTS[1]?.id}`);
    await page.waitForLoadState("networkidle");

    const chip = page.locator("[data-account-signed-in]").first();
    await expect(chip).toBeVisible();
    await expect(chip).toContainText(me.display_name);
    await expect(page.locator("html")).toHaveClass(officerShown ? /officer/ : /member/);

    await chip.click();
    const officersLink = page.locator("[data-account-menu]").getByRole("link", { name: "Officers" });
    if (officerShown) {
      await expect(officersLink).toBeVisible();
    } else {
      await expect(officersLink).toBeHidden();
    }
  });
}
