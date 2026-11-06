// What each page shows to whom: signed-out visitors get event headlines only, members see rosters and can sign
// up, officers get the Round Table, and only GMs get the member console.
import {
  ACHIEVEMENT_CATEGORIES,
  ACHIEVEMENT_CATEGORY_DETAIL,
  ACHIEVEMENTS,
  ADDONS,
  ATTENDANCE_EVENTS,
  CHARACTER_MILESTONES,
  CHARACTER_PAGES,
  CHARACTERS,
  DEVICE_AUTH_USER_CODE,
  EPGP_RECRUITS,
  EVENTS,
  GM,
  GUILD_ANNOUNCEMENTS,
  GUILD_ROSTER,
  HEROES,
  ITEMS,
  LONG_TITLE,
  MCP_TOKENS,
  MEMBER,
  OFFICER,
  ONLINE,
  PROFESSIONS,
  PVP_BOARDS,
  PVP_MATCHES,
  QUEST_AREAS,
  QUESTS,
  RECIPES,
} from "./data";
import { expect, test } from "./fixtures";
import { DISCORD_INVITE } from "../src/config";

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

  test("the addons band links to CurseForge and the addon's source", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/");
    const band = page.locator("#addons");
    await expect(band.locator('a[href="https://www.curseforge.com/wow/addons/sidequest"]')).toBeVisible();
    await expect(band.locator('a[href="https://github.com/SideQuest-Guild/addon"]')).toBeVisible();
  });

  test("recruiting lays roles and classes out in even rows", async ({ page, site }) => {
    site.signIn(null);
    site.recruiting({
      roles: [
        { role: "tank", priority: "normal", note: null },
        { role: "healer", priority: "high", note: "Raid healers" },
        { role: "dps", priority: "normal", note: null },
      ],
      classes: (["warrior", "paladin", "hunter", "rogue", "priest", "shaman", "mage", "warlock", "druid"] as const).map(
        (cls) => ({ class: cls, priority: "normal" as const, note: null }),
      ),
      updated_at: new Date().toISOString(),
    });
    await page.goto("/");
    const band = page.locator("#recruiting");
    await expect(band).toBeVisible();
    const roles = band.locator(".recruit-grid").first().locator(".recruit-card");
    await expect(roles).toHaveCount(3);
    await expect(band.locator(".recruit-card.is-high")).toContainText("High priority");
    const roleTops = await roles.evaluateAll((cards) => cards.map((card) => card.getBoundingClientRect().top));
    expect(new Set(roleTops).size).toBe(1);

    const classes = band.locator(".recruit-grid-classes .recruit-card");
    await expect(classes).toHaveCount(9);
    const perRow = await classes.evaluateAll((cards) => {
      const firstTop = cards[0]!.getBoundingClientRect().top;
      return cards.filter((card) => card.getBoundingClientRect().top === firstTop).length;
    });
    expect(perRow).toBe(page.viewportSize()!.width > 400 ? 3 : 2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    // Every card is a link to the Discord invite, the one way to sign up.
    const hrefs = await band
      .locator("a.recruit-card")
      .evaluateAll((cards) => cards.map((card) => card.getAttribute("href")));
    expect(hrefs).toEqual(Array(12).fill(DISCORD_INVITE));
  });

  test("signed out, the online-now roster never shows names", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await expect(page.locator("[data-online-now]")).toBeHidden();
    await expect(page.locator(".online-now-member")).toHaveCount(0);
  });

  test("members see the online-now roster and an Open Discord link", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/");
    await expect(page.locator("[data-online-now]")).toBeVisible();
    await expect(page.locator(".online-now-member")).toHaveCount(ONLINE.members.length);
    await expect(page.locator(".online-now-member").first()).toContainText(ONLINE.members[0]?.name ?? "");
    await expect(page.locator("[data-online-now-link]")).toHaveAttribute(
      "href",
      "https://discord.com/channels/1564671275316543508",
    );
  });

  test("online-now names stay inside their own item", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/");
    await expect(page.locator(".online-now-member")).toHaveCount(ONLINE.members.length);
    const spills = await page.locator(".online-now-member").evaluateAll((items) =>
      items.flatMap((item) => {
        const name = item.querySelector(".online-now-name");
        const box = item.getBoundingClientRect();
        const text = name?.getBoundingClientRect();
        const fits =
          name && text && name.scrollWidth <= name.clientWidth && text.left >= box.left && text.right <= box.right;
        return fits ? [] : [item.getAttribute("title")];
      }),
    );
    expect(spills).toEqual([]);
  });
});

test.describe("events", () => {
  test("signed out, rows carry no sign-up counts", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/events/");
    await expect(page.locator("#events-upcoming a.quest")).toHaveCount(2);
    await expect(page.locator("#events-past a.quest")).toHaveCount(1);
    await expect(page.locator("#events-upcoming")).not.toContainText("2T");
    await expect(page.locator("#signup-hint")).toBeVisible();
  });

  test("members see counts, and the kind filter narrows the list", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/events/");
    await expect(page.locator("#events-upcoming .quest-meta").filter({ hasText: "Molten Core" })).toContainText(
      "2T · 3H · 9D · 1 tentative · 4 interested on Discord",
    );
    await expect(page.locator("#signup-hint")).toBeHidden();
    await page.locator("#kind-filter-list").getByRole("link", { name: "Raids", exact: true }).click();
    await expect(page.locator("#events-upcoming a.quest")).toHaveCount(1);
    await expect(page.locator("#kind-filter-list").getByRole("link", { name: "Raids", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
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
    await expect(page.locator("#away-section")).toBeHidden();
  });

  test("members see the roster and raid chart, and can sign up", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/events/detail/?id=${raid?.id}`);
    await expect(page.locator("#roster-chamber")).toContainText("Brannoc");
    await expect(page.locator("#chart-section")).toBeVisible();
    await expect(page.locator("#away-section")).toBeVisible();
    await expect(page.locator("#away-chips")).toContainText("Kaelthasmaybe");
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

test.describe("raid chart", () => {
  test("officer applies a suggestion and the PATCH calls go out", async ({ page, site }) => {
    site.signIn(OFFICER);
    const patched: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "PATCH" && /\/signups\//.test(req.url())) {
        patched.push(req.url());
      }
    });
    await page.goto(`/events/detail/?id=${raid?.id}`);
    await page.getByRole("button", { name: "Suggest groups" }).click();
    await expect(page.locator("#suggest-preview-actions")).toBeVisible();
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(page.locator("#chart-status")).toHaveText("Chart updated.");
    expect(patched.length).toBeGreaterThan(0);
  });

  test("drag moves a player between groups", async ({ page, site }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "drag uses mouse pointer events");
    site.signIn(OFFICER);
    await page.goto(`/events/detail/?id=${raid?.id}`);
    const bar = page.locator('.raid-bar[data-signup-id="s3"]');
    const targetFrame = page.locator('.raid-frame[data-chart-target="5"]');
    await targetFrame.scrollIntoViewIfNeeded();
    const barBox = await bar.boundingBox();
    const targetBox = await targetFrame.boundingBox();
    if (!barBox || !targetBox) {
      throw new Error("expected both the dragged bar and the target frame on screen");
    }
    await page.mouse.move(barBox.x + barBox.width / 2, barBox.y + barBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 10 });
    await page.mouse.up();
    await expect(page.locator('.raid-frame[data-chart-target="5"]')).toContainText("Thistlewhit");
  });
});

test.describe("raid readiness", () => {
  test("shows level, item level and spec, marking under-geared sign-ups", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/events/detail/?id=${raid?.id}`);
    const brannoc = page.locator('.raid-bar[data-signup-id="s1"]');
    await expect(brannoc.locator(".readiness-low")).toHaveText("ilvl 54");
    await expect(brannoc.locator(".readiness-low")).toHaveAttribute("title", "Below the raid minimum of 58");
    await expect(brannoc.locator("a.raid-bar-name")).toHaveAttribute(
      "href",
      "/characters/detail/?slug=brannoc-anvilheart",
    );
    const elowen = page.locator('.raid-bar[data-signup-id="s2"]');
    await expect(elowen.locator(".readiness")).toContainText("ilvl 60");
    await expect(elowen.locator(".readiness-low")).toHaveCount(0);
    const thistlewhit = page.locator('.raid-bar[data-signup-id="s3"]');
    await expect(thistlewhit.locator(".readiness")).toContainText("Lvl 58");
    await expect(thistlewhit.locator(".readiness")).not.toContainText("ilvl");
  });

  test("officer sets a minimum item level and the marks follow it", async ({ page, site }) => {
    site.signIn(OFFICER);
    let putBody: unknown = null;
    page.on("request", (req) => {
      if (req.method() === "PUT" && req.url().endsWith("/api/raid-readiness")) {
        putBody = req.postDataJSON();
      }
    });
    await page.goto(`/events/detail/?id=${raid?.id}`);
    await expect(page.locator("#chart-min-ilvl")).toHaveValue("58");
    await page.locator("#chart-min-ilvl").fill("70");
    await page.locator("#chart-min-ilvl-save").click();
    await expect(page.locator("#chart-minlevel-status")).toHaveText("Saved.");
    expect(putBody).toEqual({ min_item_level: 70 });
    // Elowen's ilvl 60 sign-up is fine under 58 but under-geared once the minimum rises to 70.
    await expect(page.locator('.raid-bar[data-signup-id="s2"] .readiness-low')).toHaveText("ilvl 60");
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

test.describe("raids", () => {
  test("the upcoming list shows the mocked raid, and the contents rail links work", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/raids/");
    await expect(page.getByRole("heading", { level: 1, name: "Raiding" })).toBeVisible();
    await expect(page.locator("#raids-upcoming a.quest")).toHaveCount(1);
    await expect(page.locator("#raids-upcoming")).toContainText(LONG_TITLE);
    await expect(page.locator("#raids-upcoming a.quest")).toHaveAttribute("href", `/events/detail/?id=${raid?.id}`);
    await expect(page.locator("#raids-signup-hint")).toBeVisible();

    await page.locator('[data-toc="loot"]').click();
    await expect(page).toHaveURL("/raids/#loot");
    await expect(page.locator("#loot")).toBeInViewport();

    await page.locator('[data-toc="faq"]').click();
    await expect(page).toHaveURL("/raids/#faq");
    await expect(page.locator("#faq")).toBeInViewport();
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

  test("shows the calendar link and Google/Apple subscribe links, and rotation replaces it", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/account/#schedule");
    const urlInput = page.locator("#calendar-url");
    await expect(urlInput).toHaveValue(/\/api\/calendar\/mock-calendar-token\.ics$/);
    await expect(page.locator("#calendar-google")).toHaveAttribute(
      "href",
      /^https:\/\/calendar\.google\.com\/calendar\/r\?cid=webcal%3A%2F%2F.*mock-calendar-token\.ics$/,
    );
    await expect(page.locator("#calendar-apple")).toHaveAttribute("href", /^webcal:\/\/.*mock-calendar-token\.ics$/);

    page.once("dialog", (dialog) => dialog.accept());
    await page.locator("#calendar-rotate-btn").click();
    await expect(urlInput).not.toHaveValue(/\/api\/calendar\/mock-calendar-token\.ics$/);
    await expect(urlInput).toHaveValue(/\/api\/calendar\/mock-calendar-token-\d+\.ics$/);
  });

  test("deleting the account asks first, and keeping it sends nothing", async ({ page, site }) => {
    site.signIn(MEMBER);
    const deletes: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "DELETE" && new URL(request.url()).pathname === "/api/me") {
        deletes.push(request.url());
      }
    });
    await page.goto("/account/#danger");
    const confirm = page.locator("#delete-confirm");
    await expect(page.locator(".danger-zone")).toContainText("removes you from the guild on Discord");

    await page.locator("#delete-account-btn").click();
    await expect(confirm).toBeVisible();
    await expect(page.locator("#delete-account-cancel")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(confirm).toBeHidden();
    await expect(page.locator("#delete-account-btn")).toBeFocused();
    expect(deletes).toHaveLength(0);

    await page.locator("#delete-account-btn").click();
    await page.locator("#delete-account-confirm").click();
    await expect(page.locator("#account-signed-out")).toBeVisible();
    expect(deletes).toHaveLength(1);
  });

  test("adding and removing an away range calls the API and updates the list", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/account/#schedule");
    await expect(page.locator("#away-list")).toContainText("No away dates marked.");

    await page.locator("#away-start").fill("2026-11-10");
    await page.locator("#away-end").fill("2026-11-14");
    await page.locator("#away-note").fill("Family trip");
    await page.locator("#away-form button[type=submit]").click();

    const item = page.locator(".away-item");
    await expect(item).toHaveCount(1);
    await expect(item).toContainText("Nov 10");
    await expect(item).toContainText("Nov 14");
    await expect(item).toContainText("Family trip");

    await item.locator(".away-delete-btn").click();
    await expect(page.locator(".away-item")).toHaveCount(0);
    await expect(page.locator("#away-list")).toContainText("No away dates marked.");
  });

  test("adding and removing a character calls the API and updates the list", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/account/#characters");
    await expect(page.locator("#char-list")).toContainText("No characters linked yet.");

    await page.locator("#char-name").fill("Testerton");
    await page.locator("#char-realm").fill("Whitemane");
    await page.locator("#char-class").selectOption("warrior");
    await page.locator("#char-form button[type=submit]").click();

    const item = page.locator(".char-item");
    await expect(item).toHaveCount(1);
    await expect(item).toContainText("Testerton-Whitemane");

    await item.locator(".char-delete-btn").click();
    await expect(page.locator(".char-item")).toHaveCount(0);
    await expect(page.locator("#char-list")).toContainText("No characters linked yet.");
  });

  test("adding an item to the wishlist with a note shows it on the account Wishlist tab, and removing it there works", async ({
    page,
    site,
  }) => {
    site.signIn(MEMBER);
    await page.goto(`/items/detail/?id=${ITEMS[0]!.item_id}`);
    await expect(page.locator("#wishlist-member")).toBeVisible();
    await page.locator("#wishlist-note").fill("For my hunter off-spec");
    await page.locator("#wishlist-save-btn").click();
    await expect(page.locator("#wishlist-status")).toContainText("Added to your wishlist.");
    await expect(page.locator("#wishlist-remove-btn")).toBeVisible();

    await page.goto("/account/#wishlist");
    const item = page.locator(".wish-item");
    await expect(item).toHaveCount(1);
    await expect(item).toContainText("Glory of the Defender");
    await expect(item).toContainText("For my hunter off-spec");

    await item.locator(".wish-delete-btn").click();
    await expect(page.locator(".wish-item")).toHaveCount(0);
    await expect(page.locator("#wish-list")).toContainText("No wishes yet.");
  });

  test("lists Companion sign-ins and revoking one calls the API and updates the list", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/account/#companion");
    const item = page.locator("#companion-token-list .companion-row");
    await expect(item).toHaveCount(1);
    await expect(item).toContainText("Guide's laptop");

    page.once("dialog", (dialog) => dialog.accept());
    await item.locator("[data-revoke-companion-token]").click();
    await expect(page.locator("#companion-token-list")).toContainText("No Companion sign-ins yet.");
  });

  test("the Stats tab shows the member's own level and voice hours, and #companion lands on Companion", async ({
    page,
    site,
  }) => {
    site.signIn(MEMBER);
    const memberHero = HEROES.find((h) => h.member_id === MEMBER.id)!;

    await page.goto("/account/#stats");
    await expect(page.locator("#tab-stats")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("[data-log-level]")).toHaveText(`Lv. ${memberHero.chat_level}`);
    await expect(page.locator("[data-log-tiles]")).toContainText("35.0h");

    await page.goto("/account/#companion");
    await expect(page.locator("#tab-companion")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#panel-companion")).toBeVisible();
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

  test("creating an MCP token shows the plaintext once and the connect command", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/#mcp");
    await expect(page.locator("#tab-mcp")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#mcp-token-list")).toContainText(MCP_TOKENS[0]!.name);

    await page.locator("#mcp-token-name").fill("My new laptop");
    await page.locator("#mcp-token-create").click();

    const reveal = page.locator("#mcp-token-reveal");
    await expect(reveal).toBeVisible();
    await expect(reveal.locator('input[aria-label="New MCP token"]')).toHaveValue(/^sqm_/);
    await expect(reveal).toContainText("claude mcp add --transport http sidequest https://sidequest-guild.com/api/mcp");
    await expect(reveal).toContainText("Authorization: Bearer sqm_");
    await expect(page.locator("#mcp-token-list")).toContainText("My new laptop");
  });

  test("revoking an MCP token removes it from the list", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/#mcp");
    const row = page.locator(`[data-mcp-token-id="${MCP_TOKENS[0]!.id}"]`);
    await expect(row).toBeVisible();

    page.once("dialog", (dialog) => dialog.accept());
    await row.locator("[data-revoke-mcp-token]").click();
    await expect(row).toHaveCount(0);
    await expect(page.locator("#mcp-token-list")).not.toContainText(MCP_TOKENS[0]!.name);
  });

  test("members don't see the Statistics tab", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/officers/#statistics");
    await expect(page.locator("#officers-gate")).toBeVisible();
    await expect(page.locator("#tab-statistics")).toBeHidden();
  });

  test("officers see the Statistics tab with leaderboards", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/#statistics");
    await expect(page.locator("#tab-statistics")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#stats-kpi-grid")).toContainText("Messages");
    await expect(page.locator("#stats-top-chatters")).toContainText(GM.display_name);
  });
});

test.describe("ledger", () => {
  test("signed out, standings, rules, loot and progression all show", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/ledger/");
    await expect(page.locator("#standings-rows tr")).toHaveCount(4);
    await expect(page.locator("#rules-body")).toContainText("Boss kill");
    await expect(page.locator("#loot-list")).toContainText("Glory of the Defender");
    await expect(page.locator("#progression-body")).toContainText("Hyjal Summit");
    await expect(page.locator(".ledger-table tr.is-you")).toHaveCount(0);
  });

  test("signed in, the member's own standings row is highlighted", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/ledger/");
    await expect(page.locator(".ledger-table tr.is-you")).toContainText("Wanderer");
  });
});

test.describe("items", () => {
  test("searching lists matching items that link to their detail page", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/items/");
    await page.locator("#item-query").fill("Glory of the Defender");
    await page.locator("#item-search-form button[type=submit]").click();
    const result = page.locator("#item-results .item-row a.item-link");
    await expect(result).toHaveText("Glory of the Defender");
    await expect(result).toHaveAttribute("href", `/items/detail/?id=${ITEMS[0]!.item_id}`);
    await result.click();
    await expect(page).toHaveURL(`/items/detail/?id=${ITEMS[0]!.item_id}`);
    await expect(page.locator(".item-detail-name")).toHaveText("Glory of the Defender");
  });

  test("too short a query asks for more letters instead of searching", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/items/");
    await page.locator("#item-query").fill("gl");
    await page.locator("#item-search-form button[type=submit]").click();
    await expect(page.locator("#item-status")).toContainText("at least 3 letters");
    await expect(page.locator("#item-results")).toBeEmpty();
  });

  test("an item page shows who in the guild has looted it", async ({ page, site }) => {
    site.signIn(null);
    await page.goto(`/items/detail/?id=${ITEMS[0]!.item_id}`);
    await expect(page.locator(".item-detail-name")).toHaveText("Glory of the Defender");
    await expect(page.locator("#item-loot-list")).toContainText("Quest Guide");
    await expect(page.locator(".item-loot-price")).toContainText("125 GP main spec");
  });

  test("an unknown item says so plainly", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/items/detail/?id=999999999");
    await expect(page.locator("#item-detail-status")).toContainText("no such item");
    await expect(page.locator("#item-detail-content")).toBeHidden();
  });

  test("an officer sees who wants the item, highest priority first", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto(`/items/detail/?id=${ITEMS[0]!.item_id}`);
    const rows = page.locator("#item-wishers-list .item-wisher-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("Wanderer");
    await expect(rows.first()).toContainText("120.0 EP");
    await expect(rows.first()).toContainText("0.800 PR");
    await expect(rows.nth(1)).toContainText("Freshface");
    await expect(rows.nth(1)).toContainText("Trial");
  });

  test("a signed-out visitor sees the sign-in line and no wishers request is made", async ({ page, site }) => {
    site.signIn(null);
    const requests: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/wishers")) {
        requests.push(request.url());
      }
    });
    await page.goto(`/items/detail/?id=${ITEMS[0]!.item_id}`);
    await expect(page.locator(".item-detail-name")).toHaveText("Glory of the Defender");
    await expect(page.locator("#wishlist-signed-out")).toContainText("Sign in with Discord");
    await expect(page.locator("#wishlist-member")).toBeHidden();
    await expect(page.locator("#wishers-section")).toBeHidden();
    expect(requests).toHaveLength(0);
  });
});

test.describe("quests", () => {
  test("filtering zones then picking one shows its quests, which link to their detail page", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/quests/");
    await page.locator("#quest-area-filter").fill(QUEST_AREAS[0]!.name);
    const row = page.locator("#quest-area-list .quest-area-row", { hasText: QUEST_AREAS[0]!.name });
    await expect(row).toHaveCount(1);
    await row.click();
    const questRow = page.locator("#quest-list a.ref-link", { hasText: QUESTS[0]!.title });
    await expect(questRow).toBeVisible();
    await questRow.click();
    await expect(page).toHaveURL(`/quests/detail/?id=${QUESTS[0]!.id}`);
    await expect(page.locator(".quest-detail-name")).toHaveText(QUESTS[0]!.title);
  });

  test("a quest page shows its rewards", async ({ page, site }) => {
    site.signIn(null);
    await page.goto(`/quests/detail/?id=${QUESTS[0]!.id}`);
    await expect(page.locator(".quest-detail-name")).toHaveText(QUESTS[0]!.title);
    await expect(page.locator(".quest-rewards-list")).toContainText("Refreshing Spring Water");
    await expect(page.locator(".quest-rewards-list")).toContainText("Argent Dawn");
  });

  test("an unknown quest says so plainly", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/quests/detail/?id=999999999");
    await expect(page.locator("#quest-detail-status")).toContainText("no such quest");
    await expect(page.locator("#quest-detail-content")).toBeHidden();
  });
});

test.describe("achievements", () => {
  test("picking a category lists its achievements with points, linking to their detail page", async ({
    page,
    site,
  }) => {
    site.signIn(null);
    await page.goto("/achievements/");
    const childRow = page.locator("#achievement-category-list .achievement-category-row", {
      hasText: ACHIEVEMENT_CATEGORIES[0]!.children[0]!.name,
    });
    await childRow.click();
    const achievementRow = page.locator("#achievement-list .achievement-row", {
      hasText: ACHIEVEMENT_CATEGORY_DETAIL.achievements[0]!.name,
    });
    await expect(achievementRow).toContainText(`${ACHIEVEMENT_CATEGORY_DETAIL.achievements[0]!.points} pts`);
    await achievementRow.locator("a.ref-link").click();
    await expect(page).toHaveURL(`/achievements/detail/?id=${ACHIEVEMENTS[0]!.id}`);
  });

  test("an achievement page shows its criteria", async ({ page, site }) => {
    site.signIn(null);
    await page.goto(`/achievements/detail/?id=${ACHIEVEMENTS[0]!.id}`);
    await expect(page.locator(".achievement-detail-name")).toHaveText(ACHIEVEMENTS[0]!.name);
    await expect(page.locator(".achievement-criteria-list").last()).toContainText(
      ACHIEVEMENTS[0]!.criteria.children[0]!.description!,
    );
  });

  test("an unknown achievement says so plainly", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/achievements/detail/?id=999999999");
    await expect(page.locator("#achievement-detail-status")).toContainText("no such achievement");
    await expect(page.locator("#achievement-detail-content")).toBeHidden();
  });
});

test.describe("recipes", () => {
  test("picking a profession lists its categories/recipes, and the name filter narrows them", async ({
    page,
    site,
  }) => {
    site.signIn(null);
    await page.goto("/recipes/");
    await page.locator(`[data-profession-id="${PROFESSIONS[0]!.id}"]`).click();
    await expect(page.locator("#recipes-profession-name")).toHaveText(PROFESSIONS[0]!.name);
    await expect(page.locator(".recipe-row")).toHaveCount(3);
    await expect(page.locator(".recipe-row", { hasText: "Copper Chain Pants" })).toBeVisible();

    await page.locator("#recipe-filter").fill("copper");
    await expect(page.locator(".recipe-row:visible")).toHaveCount(1);
    await expect(page.locator(".recipe-row:visible")).toContainText("Copper Chain Pants");
  });
});

test.describe("recipe page", () => {
  test("shows the recipe's reagents and the guild crafters who know it", async ({ page, site }) => {
    site.signIn(null);
    await page.goto(`/recipes/detail/?id=${RECIPES[0]!.recipe_id}`);
    await expect(page.locator("#recipe-name")).toHaveText(RECIPES[0]!.name);
    await expect(page.locator("#recipe-reagent-list")).toContainText("Copper Bar");
    await expect(page.locator("#recipe-reagent-list")).toContainText("Tin Bar");
    await expect(page.locator("#recipe-crafter-list")).toContainText("Quest Guide");
  });

  test("an unknown recipe says so plainly", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/recipes/detail/?id=999999999");
    await expect(page.locator("#recipe-detail-status")).toContainText("no such recipe");
    await expect(page.locator("#recipe-detail-content")).toBeHidden();
  });
});

test.describe("officers sync", () => {
  test("members are turned away at the gate", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/officers/sync/");
    await expect(page.locator("#sync-gate")).toBeVisible();
    await expect(page.locator("#sync-body")).toBeHidden();
  });

  test("officers can import a raid night and link a character", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/sync/");
    await expect(page.locator("#sync-body")).toBeVisible();

    await page.locator("#import-payload").fill("SQX1:bW9jaw==");
    await page.locator("#import-submit").click();
    await expect(page.locator("#import-result")).toContainText("Sessions: 1 new");

    const strayRow = page.locator("[data-character-id='char-2']");
    await strayRow.locator("select[data-char-member]").selectOption("7");
    await expect(page.locator("#sync-status")).toContainText("Character updated.");
  });

  test("an officer votes on a recruit and the vote shows up", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/sync/");
    const recruit = EPGP_RECRUITS[0]!;
    const row = page.locator(`[data-recruit-id="${recruit.id}"]`);
    await expect(row).toContainText(recruit.character);
    await row.locator('[data-recruit-vote="no"]').click();
    await expect(row).toContainText("Quest Guide: no");
    await expect(page.locator("#sync-status")).toHaveText("Vote recorded.");
  });

  test("an officer sets a recruit's Battle.net character and sees their guild", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/sync/");

    const linked = EPGP_RECRUITS[0]!;
    const linkedRow = page.locator(`[data-recruit-id="${linked.id}"]`);
    await expect(linkedRow).toContainText(`In guild ${linked.battlenet!.guild_name}`);

    const unlinked = EPGP_RECRUITS[1]!;
    const row = page.locator(`[data-recruit-id="${unlinked.id}"]`);
    await expect(row).toContainText("No Battle.net character linked yet.");
    const target = CHARACTERS[0]!;
    await row.locator("[data-battlenet-input]").fill(`${target.name} ${target.surname}`);
    await row.locator('button[type="submit"]').click();
    await expect(row).toContainText(`${target.name} ${target.surname}`);
    await expect(row).toContainText(target.guild_name ?? "");
  });

  test("checking an unknown Battle.net character shows the API's detail", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/sync/");
    const recruit = EPGP_RECRUITS[1]!;
    const row = page.locator(`[data-recruit-id="${recruit.id}"]`);
    await row.locator("[data-battlenet-input]").fill("Nobody Nowhere");
    await row.locator('button[type="submit"]').click();
    await expect(row.locator("[data-battlenet-status]")).toContainText("Battle.net has no character nobody-nowhere.");
  });

  test("an officer composes an announcement and it appears in the recent list", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/sync/");
    await expect(page.locator("#announcements-list")).toContainText(GUILD_ANNOUNCEMENTS[0]!.text);

    await page.locator("#announcement-text").fill("Raid moved to 8pm tonight");
    await page.locator("#announcement-discord").check();
    await page.locator("#announcement-submit").click();
    await expect(page.locator("#announcement-status")).toHaveText("Posted.");
    await expect(page.locator("#announcements-list")).toContainText("Raid moved to 8pm tonight");
  });
});

test.describe("companion authorize", () => {
  test("signed out, it offers Discord sign-in", async ({ page, site }) => {
    site.signIn(null);
    await page.goto(`/companion/authorize/?code=${DEVICE_AUTH_USER_CODE}`);
    await expect(page.locator("#authorize-gate")).toBeVisible();
    await expect(page.locator("#authorize-body")).toBeHidden();
    await expect(page.locator("#authorize-gate-message a")).toHaveAttribute("href", /\/auth\/discord\/login\?next=/);
  });

  test("a member (not just an officer) can authorize the companion", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/companion/authorize/?code=${DEVICE_AUTH_USER_CODE}`);
    await expect(page.locator("#authorize-gate")).toBeHidden();
    await expect(page.locator("#authorize-confirm")).toBeVisible();
    await expect(page.locator("#authorize-code-display")).toHaveText(DEVICE_AUTH_USER_CODE);
    await expect(page.locator("#authorize-capabilities")).not.toContainText("upload raid nights");

    await page.locator("#authorize-approve-btn").click();
    await expect(page.locator("#authorize-result-title")).toHaveText("All set");
  });

  test("an officer sees sync mentioned in what Companion can do", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto(`/companion/authorize/?code=${DEVICE_AUTH_USER_CODE}`);
    await expect(page.locator("#authorize-capabilities")).toContainText("upload raid nights");
  });

  test("the old officers/sync/authorize/ URL still works", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/officers/sync/authorize/?code=${DEVICE_AUTH_USER_CODE}`);
    await expect(page).toHaveURL(new RegExp(`/companion/authorize/\\?code=${DEVICE_AUTH_USER_CODE}`));
    await expect(page.locator("#authorize-confirm")).toBeVisible();
  });
});

test.describe("guild hall", () => {
  test("signed out, the guild hall stays behind a gate", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/guild/");
    await expect(page.locator("#guild-gate")).toBeVisible();
    await expect(page.locator("#guild-gate-message a")).toHaveAttribute("href", /\/auth\/discord\/login\?next=/);
    await expect(page.locator("#guild-body")).toBeHidden();
  });

  test("members see the roster, and can switch to the other tabs", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/guild/");
    await expect(page.locator("#guild-body")).toBeVisible();
    await expect(page.locator("#tab-roster")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#roster-list")).toContainText(GUILD_ROSTER.members[0]!.name);
    await expect(page.locator("#roster-list")).toContainText(GUILD_ROSTER.unlinked[0]!.name);

    await page.locator("#tab-crafters").click();
    await expect(page).toHaveURL("/guild/#crafters");
    await expect(page.locator("#panel-crafters")).toBeVisible();

    await page.locator("#tab-bank").click();
    await expect(page).toHaveURL("/guild/#bank");
    await expect(page.locator("#bank-totals")).toContainText("4");

    await page.locator("#tab-news").click();
    await expect(page).toHaveURL("/guild/#news");
    await expect(page.locator("#news-list")).toContainText("Rage Winterchill");
  });

  test("a direct link to a tab opens it", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/guild/#crafters");
    await expect(page.locator("#tab-crafters")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#panel-crafters")).toBeVisible();
  });

  test("searching for a recipe lists its crafters and copies a whisper line", async ({ page, site }) => {
    // Browser clipboard permissions differ across engines; stub the API in-page instead of granting permission.
    await page.addInitScript(() => {
      const win = window as typeof window & { copiedWhispers: string[] };
      win.copiedWhispers = [];
      Object.defineProperty(navigator, "clipboard", {
        value: {
          writeText: (text: string) => {
            win.copiedWhispers.push(text);
            return Promise.resolve();
          },
        },
      });
    });
    site.signIn(MEMBER);
    await page.goto("/guild/#crafters");
    await page.locator("#crafter-query").fill("Flask of the Titans");
    await expect(page.locator("#crafter-results")).toContainText("Flask of the Titans");
    await expect(page.locator("#crafter-results")).toContainText("Wanderer");
    await page.locator("[data-copy-whisper]").first().click();
    await expect(page.locator("[data-copy-whisper]").first()).toHaveText("Copied");
    const copied = await page.evaluate(() => {
      const win = window as typeof window & { copiedWhispers: string[] };
      return win.copiedWhispers;
    });
    expect(copied[0]?.startsWith("/w ")).toBe(true);
  });

  test("a crafter row with a matched recipe links to its recipe page", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/guild/#crafters");
    await page.locator("#crafter-query").fill("Copper Chain Pants");
    const row = page.locator(".guild-crafter-recipe", { hasText: "Copper Chain Pants" });
    await expect(row.getByRole("link", { name: "Recipe" })).toHaveAttribute(
      "href",
      `/recipes/detail/?id=${RECIPES[0]!.recipe_id}`,
    );
  });
});

test.describe("hall of heroes", () => {
  test("signed out, the leaderboard stays behind a gate", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/heroes/");
    await expect(page.locator("#heroes-gate")).toBeVisible();
    await expect(page.locator("#heroes-gate-message a")).toHaveAttribute("href", /\/auth\/discord\/login\?next=/);
    await expect(page.locator("#heroes-body")).toBeHidden();
  });

  test("the hero boards show the roster's top characters, and an empty board where no one qualifies", async ({
    page,
    site,
  }) => {
    site.signIn(null);
    await page.goto("/heroes/");
    const boards = page.locator("#hero-boards-grid .hero-board");
    await expect(boards).toHaveCount(4);
    const itemLevelBoard = page.locator("#hero-boards-grid .hero-board", { hasText: "Item level" });
    const topRow = itemLevelBoard.locator(".groups-board-row").first();
    await expect(topRow).toContainText(`${CHARACTERS[0]!.name} ${CHARACTERS[0]!.surname}`);
    await expect(topRow.locator("a")).toHaveAttribute("href", `/characters/detail/?slug=${CHARACTERS[0]!.slug}`);
    const killsBoard = page.locator("#hero-boards-grid .hero-board", { hasText: "Honorable kills" });
    await expect(killsBoard.locator(".hero-board-empty")).toContainText("No one yet");
  });
  test("members see the leaderboard ranked by Renown, and can switch season and sort", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/heroes/");
    await expect(page.locator("#heroes-body")).toBeVisible();
    const rows = page.locator(".hero-row");
    await expect(rows).toHaveCount(HEROES.length);
    await expect(rows.first()).toContainText(GM.display_name);

    await page.locator('#season-tabs button[data-season="all"]').click();
    await expect(page.locator('#season-tabs button[data-season="all"]')).toHaveAttribute("aria-selected", "true");

    await page.locator('#sort-tabs button[data-sort="raids_attended"]').click();
    await expect(page.locator('#sort-tabs button[data-sort="raids_attended"]')).toHaveAttribute("aria-pressed", "true");
    await expect(rows.first()).toContainText(GM.display_name);
  });

  test("before anyone earns Renown, the roster is listed unranked", async ({ page, site }) => {
    site.signIn(MEMBER);
    const fresh = HEROES.map((row) => ({ ...row, rank: null, ep: 0, raids_attended: 0, events_attended: 0 }));
    await page.route("**/api/heroes?*", (route) =>
      route.fulfill({ json: { season_id: "all", season_name: "All Time", rows: fresh } }),
    );
    await page.goto("/heroes/");
    const rows = page.locator(".hero-row");
    await expect(rows).toHaveCount(HEROES.length);
    await expect(page.locator(".hero-empty")).toContainText("No one has earned Renown");
    await expect(rows.locator(".hero-rank-none")).toHaveCount(HEROES.length);

    await page.locator('#sort-tabs button[data-sort="chat_level"]').click();
    await expect(page.locator(".hero-empty")).toHaveCount(0);
    await expect(rows.first().locator(".hero-rank")).toHaveText("1");
  });

  test("a hero's profile shows badges and recent events", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/heroes/member/?id=${GM.id}`);
    await expect(page.getByRole("heading", { level: 1, name: GM.display_name })).toBeVisible();
    await expect(page.locator("#hero-badge-case")).toContainText("First Steps");
    await expect(page.locator("#hero-recent-events")).toContainText(LONG_TITLE);
  });

  test("a hero's profile shows level, messages and voice hours from the Adventurer's Log", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/heroes/member/?id=${GM.id}`);
    await expect(page.locator("[data-log-level]")).toContainText("Lv.");
    await expect(page.locator("[data-log-tiles]")).toContainText("Messages");
    await expect(page.locator("[data-log-tiles]")).toContainText("Voice hours");
  });

  test("an unknown member says so", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/heroes/member/?id=999999");
    await expect(page.locator("#hero-status")).not.toBeEmpty();
    await expect(page.locator("#hero-content")).toBeHidden();
  });
});

test.describe("pvp", () => {
  test("signed out, pvp stays behind a gate", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/pvp/");
    await expect(page.locator("#pvp-gate")).toBeVisible();
    await expect(page.locator("#pvp-gate-message a")).toHaveAttribute("href", /\/auth\/discord\/login\?next=/);
    await expect(page.locator("#pvp-body")).toBeHidden();
  });

  test("members see the PvP boards and match history, and can open a match's full scoreboard", async ({
    page,
    site,
  }) => {
    site.signIn(MEMBER);
    await page.goto("/pvp/");
    await expect(page.locator("#pvp-body")).toBeVisible();

    const killsBoard = page.locator("#pvp-boards-grid .pvp-board", { hasText: "Honorable kills" });
    await expect(killsBoard.locator(".pvp-board-row").first()).toContainText(
      String(PVP_BOARDS.honorable_kills[0]!.value),
    );
    const healingBoard = page.locator("#pvp-boards-grid .pvp-board", { hasText: "Healing done" });
    await expect(healingBoard.locator(".pvp-board-empty")).toBeVisible();

    const rows = page.locator("#pvp-matches > li");
    await expect(rows).toHaveCount(PVP_MATCHES.length);
    await expect(rows.first()).toContainText(PVP_MATCHES[0]!.map);
    await expect(rows.first()).toContainText("Won");
    await expect(rows.last()).toContainText("Lost");

    await rows.first().locator("a").click();
    await expect(page).toHaveURL(`/pvp/match/?id=${PVP_MATCHES[0]!.id}`);
    await expect(page.locator("#pvp-match-map")).toHaveText(PVP_MATCHES[0]!.map);
    const scoreRows = page.locator("#pvp-scoreboard-body tr");
    await expect(scoreRows).toHaveCount(PVP_MATCHES[0]!.players.length);
    await expect(scoreRows.filter({ hasText: CHARACTERS[0]!.name })).toHaveClass(/is-guild/);
  });

  test("an unknown battleground says so", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/pvp/match/?id=00000000-0000-4000-8000-000000000000");
    await expect(page.locator("#pvp-match-status")).toContainText("no such battleground");
    await expect(page.locator("#pvp-match-content")).toBeHidden();
  });
});

test.describe("characters", () => {
  test("the roster lists every current member, linking to their detail page", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/characters/");
    const rows = page.locator("#char-roster-list li");
    const roster = CHARACTERS.filter((c) => c.in_roster);
    await expect(rows).toHaveCount(roster.length);
    await expect(rows.first()).toContainText(`${roster[0]!.name} ${roster[0]!.surname}`);
    await expect(rows.first().locator("a")).toHaveAttribute("href", `/characters/detail/?slug=${roster[0]!.slug}`);
  });

  test("the Milestones section lists recent level 40/60 characters", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/characters/");
    const rows = page.locator("#char-milestones-list li");
    await expect(rows).toHaveCount(CHARACTER_MILESTONES.length);
    const first = CHARACTER_MILESTONES[0]!;
    await expect(rows.first()).toContainText(`${first.name} ${first.surname} reached level ${first.level}`);
    await expect(rows.first().locator("a")).toHaveAttribute("href", `/characters/detail/?slug=${first.slug}`);
  });

  test("an exact two-word search offers a direct Battle.net lookup, which navigates to the character's page", async ({
    page,
    site,
  }) => {
    site.signIn(null);
    const target = CHARACTER_PAGES[2]!;
    await page.goto("/characters/");
    await page.locator("#char-query").fill(`${target.name} ${target.surname}`);
    await page.locator("#characters-search-form button[type=submit]").click();
    const exactLink = page.locator("#char-exact-link");
    await expect(exactLink).toBeVisible();
    await expect(exactLink).toHaveAttribute("href", `/characters/detail/?slug=${target.slug}`);
    await exactLink.click();
    await expect(page).toHaveURL(`/characters/detail/?slug=${target.slug}`);
    await expect(page.locator(".char-detail-name")).toContainText(`${target.name} ${target.surname}`);
  });

  test("a roster character without a Battle.net profile shows the not-published line", async ({ page, site }) => {
    site.signIn(null);
    const noProfile = CHARACTER_PAGES.find((c) => c.sheet === null)!;
    await page.goto(`/characters/detail/?slug=${noProfile.slug}`);
    await expect(page.locator("#char-no-profile")).toContainText("hasn't published");
    await expect(page.locator("#char-gear-section")).toBeHidden();
  });

  test("an unknown character shows a clear not-found message", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/characters/detail/?slug=nobody-nowhere");
    await expect(page.locator("#character-status")).toContainText("No character named Nobody Nowhere");
    await expect(page.locator("#character-content")).toBeHidden();
  });
});

test.describe("attendance", () => {
  test("an officer marks attendance and a walk-in, and the PUT carries the right body", async ({ page, site }) => {
    site.signIn(OFFICER);
    const puts: { url: string; body: unknown }[] = [];
    page.on("request", (req) => {
      if (req.method() === "PUT" && /\/api\/events\/.+\/attendance$/.test(req.url())) {
        puts.push({ url: req.url(), body: JSON.parse(req.postData() ?? "{}") });
      }
    });
    await page.goto("/officers/#attendance");
    await expect(page.locator("#tab-attendance")).toHaveAttribute("aria-selected", "true");
    const event = ATTENDANCE_EVENTS[0];
    const eventRow = page.locator(`[data-select-attendance-event="${event.id}"]`);
    await expect(eventRow).toContainText("Needs attendance");
    await eventRow.click();
    await expect(page.locator("#attendance-form")).toBeVisible();
    await expect(page.locator("#attendance-signup-list")).toContainText("In voice 42m");
    await page.selectOption('#attendance-signup-list select[aria-label="Attendance for Wanderer"]', "no_show");
    await page.selectOption("#attendance-walkin-member", { label: "Quest Guide" });
    await page.locator("#attendance-walkin-add").click();
    await expect(page.locator("#attendance-walkin-list")).toContainText("Quest Guide");
    await page.locator("#attendance-save").click();
    await expect(page.locator("#attendance-form-status")).toHaveText("Attendance saved.");
    expect(puts).toHaveLength(1);
    expect(puts[0].url).toContain(`/api/events/${event.id}/attendance`);
    expect(puts[0].body).toEqual({
      entries: [{ signup_id: "att-Wanderer", attended: false }],
      walk_ins: [{ member_id: OFFICER.id, character: null, class: "warrior", role: "tank" }],
    });
  });

  test("a Quest Guide does not see the GM report", async ({ page, site }) => {
    site.signIn(OFFICER);
    await page.goto("/officers/#attendance");
    await expect(page.locator("#panel-attendance")).toBeVisible();
    await expect(page.locator("#attendance-report")).toBeHidden();
  });

  test("a GM sees the report, switches range and raids-only, and the trend chart renders", async ({ page, site }) => {
    site.signIn(GM);
    await page.goto("/officers/#attendance");
    await expect(page.locator("#attendance-report")).toBeVisible();
    await expect(page.locator("#attendance-report-table")).toContainText("Wanderer");
    await expect(page.locator("#attendance-trend-chart svg")).toBeVisible();
    await page.locator('#attendance-range-tabs [data-range="season"]').click();
    await expect(page.locator('#attendance-range-tabs [data-range="season"]')).toHaveAttribute("aria-selected", "true");
    await page.locator("#attendance-raids-only").check();
    await expect(page.locator("#attendance-raids-only")).toBeChecked();
    await expect(page.locator("#attendance-trend-chart svg")).toBeVisible();
  });
});

test.describe("API reference", () => {
  // Scalar hides its sidebar behind a toggle below its own "lg" breakpoint; the sidebar-under-header layout is a
  // desktop concern, so this runs at the width used for the final 1568px review screenshot.
  test.use({ viewport: { width: 1568, height: 980 } });

  test("shows operations from the OpenAPI document, themed, full width under the header", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/api-reference/");
    // The on-screen title lives in Scalar's own document intro now (OpenAPI info.description); the page's own
    // h1 is visually hidden, kept only for the title landmark and the page title.
    await expect(page.getByRole("heading", { level: 1, name: "API reference", exact: true })).toBeAttached();
    await expect(page.locator(".t-doc__sidebar")).toBeVisible();
    await expect(page.getByRole("heading", { name: "List events" })).toBeVisible();
    const sidebarNav = page.locator(".t-doc__sidebar");
    await expect(sidebarNav.getByRole("link", { name: "Events", exact: true })).toBeVisible();
    await expect(sidebarNav.getByRole("link", { name: "Me", exact: true })).toBeVisible();
    await expect(sidebarNav.getByRole("link", { name: "Bot", exact: true })).toBeVisible();

    const header = await page.locator(".api-reference-room .site-nav").boundingBox();
    const sidebar = await page.locator(".t-doc__sidebar").boundingBox();
    expect(sidebar?.y ?? -1, "sidebar sits below the header").toBeGreaterThanOrEqual(
      (header?.y ?? 0) + (header?.height ?? 0) - 1,
    );
    // No boxed, bordered mount with page margins: the sidebar sits flush against the left edge, and Scalar's
    // whole container spans the viewport instead of the site's centered `.wrap` measure.
    expect(sidebar?.x ?? -1, "sidebar sits flush left").toBeLessThan(1);
    const scalarApp = await page.locator(".scalar-app").first().boundingBox();
    expect(scalarApp?.width ?? 0, "Scalar's container spans the viewport").toBeGreaterThanOrEqual(1568 - 1);

    // theme: "none" with forced dark mode and withDefaultFonts: false; nothing but this page's own font and colors.
    const body = page.locator(".scalar-app").first();
    await expect(body).toHaveCSS("background-color", /rgb\(10, 15, 26\)|rgba\(10, 15, 26/);
    // Scalar's "Ask AI" chat sends the spec and questions to Scalar's servers, so it stays off.
    await expect(page.getByText("Ask AI")).toHaveCount(0);

    // The header stays in view while reading further down, so the sidebar's offset never points at empty space.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    const scrolledHeader = await page.locator(".api-reference-room .site-nav").boundingBox();
    expect(scrolledHeader?.y, "header stays at the top after scrolling").toBe(0);
  });

  test("on a phone, the sidebar collapses under the header with no sideways scroll", async ({ page, site }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    site.signIn(null);
    await page.goto("/api-reference/");
    await expect(page.getByRole("heading", { name: "List events" })).toBeVisible();
    // Scalar's own sidebar hides itself below its "lg" breakpoint; it reappears behind Scalar's mobile nav
    // toggle, not as a second, site-drawn sidebar.
    await expect(page.locator(".t-doc__sidebar")).toBeHidden();
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth, "no horizontal scroll on a phone").toBeLessThanOrEqual(clientWidth);
  });
});

test.describe("talents", () => {
  test("spending points updates the counter and the URL", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/talents/?class=druid");
    const starlight = page.getByRole("button", { name: /^Starlight Wrath,/ });
    await expect(starlight).toBeVisible();
    await starlight.click();
    await starlight.click();
    await expect(page.locator(".talent-points-summary")).toContainText("2 / 51 points spent");
    await expect(page).toHaveURL(/\?class=druid&build=2-$/);
  });

  test("a row 2 node refuses points until 5 are spent in its tree", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/talents/?class=druid");
    const moonglow = page.getByRole("button", { name: /^Moonglow,/ });
    const starlight = page.getByRole("button", { name: /^Starlight Wrath,/ });
    await expect(moonglow).toBeDisabled();
    await expect(moonglow).toHaveAttribute("title", /Spend 5 points in Balance first/);
    for (let i = 0; i < 5; i++) {
      await starlight.click();
    }
    await expect(moonglow).toBeEnabled();
    await moonglow.click();
    await expect(moonglow).toHaveAttribute("aria-label", "Moonglow, rank 1 of 1");
  });

  test("loading a pinned build restores ranks", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/talents/");
    await page.getByRole("button", { name: "Druid", exact: true }).click();
    const pinnedList = page.locator("#pinned-builds-list");
    await expect(pinnedList).toContainText("Starfire spam");
    await pinnedList.locator("[data-load-build]").first().click();
    await expect(page.getByRole("button", { name: /^Starlight Wrath,/ })).toHaveAttribute(
      "aria-label",
      "Starlight Wrath, rank 5 of 5",
    );
    await expect(page).toHaveURL(/\?class=druid&build=5-$/);
  });

  test("a member saves a build", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/talents/?class=druid");
    await page.getByRole("button", { name: /^Starlight Wrath,/ }).click();
    await page.locator("#build-name").fill("My Balance build");
    await page.locator("#save-build-btn").click();
    await expect(page.locator("#save-build-status")).toContainText("Build saved.");
    await expect(page.locator("#my-builds-list")).toContainText("My Balance build");
  });
});
