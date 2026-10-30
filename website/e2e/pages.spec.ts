// What each page shows to whom: signed-out visitors get event headlines only, members see rosters and can sign
// up, officers get the Round Table, and only GMs get the member console.
import { ADDONS, ATTENDANCE_EVENTS, EVENTS, GM, HEROES, LONG_TITLE, MEMBER, OFFICER, ONLINE } from "./data";
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

  test("shows the calendar link and Google/Apple subscribe links, and rotation replaces it", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/account/");
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

  test("adding and removing an away range calls the API and updates the list", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/account/");
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

test.describe("hall of heroes", () => {
  test("signed out, the leaderboard stays behind a gate", async ({ page, site }) => {
    site.signIn(null);
    await page.goto("/heroes/");
    await expect(page.locator("#heroes-gate")).toBeVisible();
    await expect(page.locator("#heroes-gate-message a")).toHaveAttribute("href", /\/auth\/discord\/login\?next=/);
    await expect(page.locator("#heroes-body")).toBeHidden();
  });

  test("members see the leaderboard ranked by EP, and can switch season and sort", async ({ page, site }) => {
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

  test("a hero's profile shows badges and recent events", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto(`/heroes/member/?id=${GM.id}`);
    await expect(page.getByRole("heading", { level: 1, name: GM.display_name })).toBeVisible();
    await expect(page.locator("#hero-badge-case")).toContainText("First Steps");
    await expect(page.locator("#hero-recent-events")).toContainText(LONG_TITLE);
  });

  test("an unknown member says so", async ({ page, site }) => {
    site.signIn(MEMBER);
    await page.goto("/heroes/member/?id=999999");
    await expect(page.locator("#hero-status")).not.toBeEmpty();
    await expect(page.locator("#hero-content")).toBeHidden();
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
