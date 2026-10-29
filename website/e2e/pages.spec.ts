// What each page shows to whom: signed-out visitors get event headlines only, members see rosters and can sign
// up, officers get the Round Table, and only GMs get the member console.
import { ADDONS, EVENTS, GM, LONG_TITLE, MEMBER, OFFICER } from "./data";
import { expect, test } from "./fixtures";

const raid = EVENTS[0];

test.describe("homepage", () => {
  test("shows who's in the Discord and the next raid", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/");
    await expect(page.locator("[data-discord-online]")).toHaveText("6 online");
    await expect(page.locator(".hearth")).toHaveCount(2);
    await expect(page.locator("#raids")).toBeVisible();
    await expect(page.locator("#raid-next-date a")).toHaveAttribute("href", `/events/detail/?id=${raid?.id}`);
  });
});

test.describe("events", () => {
  test("signed out, rows carry no sign-up counts", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/events/");
    await expect(page.locator("#events-upcoming a.quest")).toHaveCount(2);
    await expect(page.locator("#events-past a.quest")).toHaveCount(1);
    await expect(page.locator("#events-upcoming")).not.toContainText("2T");
  });

  test("members see counts, and the kind filter narrows the list", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/events/");
    await expect(page.locator("#events-upcoming .quest-meta").filter({ hasText: "Molten Core" })).toContainText(
      "2T · 3H · 9D · 1 tentative · 4 interested on Discord",
    );
    await page.getByRole("link", { name: "Raids", exact: true }).click();
    await expect(page.locator("#events-upcoming a.quest")).toHaveCount(1);
    await expect(page.getByRole("link", { name: "Raids", exact: true })).toHaveAttribute("aria-current", "page");
  });
});

test.describe("event page", () => {
  test("signed out, the plan and roster stay hidden behind sign-in", async ({ page, site }) => {
    site.signIn(null);
    await page.goto(`/events/detail/?id=${raid?.id}`);
    await expect(page.getByRole("heading", { level: 1, name: LONG_TITLE })).toBeVisible();
    await expect(page.locator("#signed-out-section")).toBeVisible();
    await expect(page.locator("#signed-out-message a")).toHaveAttribute("href", /\/auth\/discord\/login\?next=/);
    await expect(page.locator("#roster-chamber")).toBeHidden();
    await expect(page.locator("#signup-section")).toBeHidden();
  });

  test("members see the roster and raid chart, and can sign up", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/events/detail/?id=${raid?.id}`);
    await expect(page.locator("#roster-chamber")).toContainText("Brannoc");
    await expect(page.locator("#chart-section")).toBeVisible();
    await page.locator("#su-character").fill("Wanderer");
    await page.locator("#su-class").selectOption("paladin");
    await page.locator("#su-role").selectOption("healer");
    await page.getByRole("button", { name: "Save signup" }).click();
    await expect(page.locator("#signup-status")).toHaveText("Saved.");
  });

  test("an unknown event says so", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/events/detail/?id=00000000-0000-4000-8000-000000000000");
    await expect(page.locator("#event-status")).not.toBeEmpty();
    await expect(page.locator("#event-content")).toBeHidden();
  });
});

test.describe("addons", () => {
  test("guild-made addons come first, labelled", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/addons/");
    const cards = page.locator("#addons-list .tooltip-card");
    await expect(cards).toHaveCount(ADDONS.length);
    await expect(cards.first()).toContainText("SideQuest Raid Helper");
    await expect(cards.first()).toContainText("Made by SideQuest");
    await expect(cards.nth(1)).toContainText("Community pick");
  });
});

test.describe("account", () => {
  test("signed out, it offers Discord sign-in", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/account/");
    await expect(page.locator("#account-signed-out")).toBeVisible();
    await expect(page.locator("#account-signed-in")).toBeHidden();
  });

  test("signed in, it shows the character sheet", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/account/");
    await expect(page.locator("#account-name")).toHaveText(MEMBER.display_name);
    await expect(page.locator("#bnet-tag")).toHaveText(MEMBER.battletag ?? "");
    await expect(page.locator("#account-signed-out")).toBeHidden();
  });
});

test.describe("officers", () => {
  test("members are turned away at the gate", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/officers/");
    await expect(page.locator("#officers-gate")).toBeVisible();
    await expect(page.locator("#officers-body")).toBeHidden();
  });

  test("officers get events and addons, not the GM console", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/#members");
    await expect(page.locator("#officers-body")).toBeVisible();
    await expect(page.locator("#tab-events")).toHaveAttribute("aria-selected", "true");
    for (const tab of ["#tab-members", "#tab-log", "#tab-moderation"]) {
      await expect(page.locator(tab)).toBeHidden();
    }
  });

  test("GMs can open a member's sheet from a deep link", async ({ page, site }) => {
    site.signIn(GM);
    await page.goto(`/officers/#members?member=${MEMBER.id}`);
    await expect(page.locator("#tab-members")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#officer-member-list [data-select-member]")).toHaveCount(3);
    await expect(page.locator("#member-detail-body")).toContainText(MEMBER.display_name);
  });
});
