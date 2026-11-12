// End-to-end tests for the Board and the New episode dialog (design doc sections 11.2 and
// 11.5, and the Board mockups). The episode list is answered from a fixed list, except in
// the last group, which goes through the real API and worker in demo mode.
import AxeBuilder from "@axe-core/playwright";
import { type Page, type Route, expect, test } from "@playwright/test";

import {
  type EpisodeRow,
  SAMPLE_EPISODES,
  SIZES,
  WCAG_TAGS,
  episode,
  mockEpisodes,
  open,
  sidewaysOverflow,
} from "./support";

const groups = (page: Page) => page.getByTestId("board-groups");
const group = (page: Page, name: string) => page.getByTestId(`group-${name}`);
const card = (page: Page, title: string) =>
  page.getByRole("article").filter({ has: page.getByRole("heading", { name: title, exact: true }) });

async function openBoard(page: Page, episodes: EpisodeRow[] = SAMPLE_EPISODES) {
  await mockEpisodes(page, () => episodes);
  await open(page);
}

test.describe("Board groups follow the mockups", () => {
  test("desktop shows Needs you, Planning, Producing and Finished with their episodes", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page);

    await expect(page.getByText("7 episodes")).toBeVisible();
    await expect(groups(page).getByRole("heading", { level: 2 })).toHaveText([
      "Needs you 2",
      "Planning 2",
      "Producing 1",
      "Finished 2",
    ]);

    const needsYou = group(page, "needs-you");
    await expect(needsYou.getByRole("article")).toHaveCount(2);
    await expect(needsYou.getByRole("article").nth(0)).toContainText("The Lighthouse Keeper");
    await expect(needsYou.getByRole("article").nth(0)).toContainText("Approve the plan");
    await expect(needsYou.getByRole("article").nth(1)).toContainText("Two Chairs");
    await expect(needsYou.getByRole("article").nth(1)).toContainText("Review the video");

    await expect(group(page, "planning").getByRole("article")).toHaveCount(2);
    await expect(card(page, "The Second Bowl")).toContainText("Checking sources");
    await expect(group(page, "producing").getByRole("article")).toHaveText(
      /Small Steps.*Making pictures and clips/,
    );
    await expect(group(page, "finished").getByRole("article")).toHaveText([
      /The Long Road Home.*Exported/,
      /What the River Kept.*Exported/,
    ]);
  });

  test("the four columns sit side by side on desktop", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page);

    const boxes = [];
    for (const name of ["needs-you", "planning", "producing", "finished"]) {
      boxes.push(await group(page, name).boundingBox());
    }
    const lefts = boxes.map((box) => Math.round(box?.x ?? -1));
    expect([...lefts].sort((a, b) => a - b)).toEqual(lefts);
    expect(new Set(lefts).size).toBe(4);
    expect(new Set(boxes.map((box) => Math.round(box?.y ?? -1))).size).toBe(1);
  });

  test("an episode without a title shows its idea", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page);

    await expect(
      group(page, "planning").getByRole("heading", {
        name: "A baker who gives away the first loaf every morning",
      }),
    ).toBeVisible();
  });

  test("an episode waiting at a gate says which approval it needs", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page, [
      episode(1, { title: "Plan", state: "direction", awaiting_approval: true, gate: "plan" }),
      episode(2, { title: "Pictures", state: "asset_gen", awaiting_approval: true, gate: "assets" }),
      episode(3, { title: "Video", state: "critique", awaiting_approval: true, gate: "review" }),
    ]);

    await expect(card(page, "Plan")).toContainText("Approve the plan");
    await expect(card(page, "Pictures")).toContainText("Approve the pictures");
    await expect(card(page, "Video")).toContainText("Review the video");
    await expect(group(page, "needs-you").getByRole("article")).toHaveCount(3);
  });

  test("the progress strip names the step, and never says it by colour alone", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page, [
      ...SAMPLE_EPISODES,
      episode(8, { title: "Not started", state: "idea" }),
      episode(9, { title: "Almost there", state: "export" }),
    ]);

    const strip = (title: string) => card(page, title).getByRole("img");
    await expect(strip("The Lighthouse Keeper")).toHaveAccessibleName(
      "Step 4 of 7, Direction: waiting for you",
    );
    await expect(strip("The Second Bowl")).toHaveAccessibleName("Step 2 of 7, Research: in progress");
    await expect(strip("Small Steps")).toHaveAccessibleName("Step 5 of 7, Pictures: in progress");
    await expect(strip("Two Chairs")).toHaveAccessibleName("Step 6 of 7, Video: waiting for you");
    await expect(strip("Almost there")).toHaveAccessibleName("Step 7 of 7, Export: in progress");
    await expect(strip("The Long Road Home")).toHaveAccessibleName("All 7 steps finished");
    await expect(strip("Not started")).toHaveAccessibleName("Not started");
    await expect(card(page, "Not started")).toContainText("Waiting to start");
  });

  test("an episode with out-of-date outputs carries the Out of date badge", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page, [
      episode(1, {
        title: "Edited later",
        state: "render",
        stale_from_state: "voice",
        stale_scenes: { voice: ["s02"] },
      }),
      episode(2, { title: "Untouched", state: "render" }),
    ]);

    await expect(card(page, "Edited later")).toContainText("Out of date");
    await expect(card(page, "Untouched")).not.toContainText("Out of date");
  });

  test("tablet shows two columns: Needs you, and everything else", async ({ page }) => {
    await page.setViewportSize(SIZES.tablet);
    await openBoard(page);

    await expect(groups(page).getByRole("heading", { level: 2 })).toHaveText([
      "Needs you 2",
      "In progress 3",
      "Finished 2",
    ]);
    const needsYou = await group(page, "needs-you").boundingBox();
    const inProgress = await group(page, "in-progress").boundingBox();
    const finished = await group(page, "finished").boundingBox();
    expect(inProgress?.x).toBeGreaterThan((needsYou?.x ?? 0) + (needsYou?.width ?? 0) - 1);
    expect(finished?.x).toBe(inProgress?.x);
    expect(finished?.y).toBeGreaterThan(inProgress?.y ?? 0);
    expect(needsYou?.y).toBe(inProgress?.y);
  });

  test("phone shows one column with Needs you first and Finished folded away", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await openBoard(page);

    await expect(groups(page).getByRole("heading", { level: 2 })).toHaveText([
      "Needs you 2",
      "In progress 3",
      "Finished 2",
    ]);
    const needsYou = group(page, "needs-you").getByRole("button", { name: "Needs you 2" });
    const finished = group(page, "finished").getByRole("button", { name: "Finished 2" });
    await expect(needsYou).toHaveAttribute("aria-expanded", "true");
    await expect(finished).toHaveAttribute("aria-expanded", "false");
    await expect(card(page, "The Lighthouse Keeper")).toBeVisible();
    await expect(card(page, "Small Steps")).toBeVisible();
    await expect(card(page, "The Long Road Home")).toBeHidden();

    await finished.click();
    await expect(finished).toHaveAttribute("aria-expanded", "true");
    await expect(card(page, "The Long Road Home")).toBeVisible();

    await needsYou.click();
    await expect(card(page, "The Lighthouse Keeper")).toBeHidden();

    const widths = await page
      .getByRole("article")
      .evaluateAll((cards) => cards.map((element) => element.getBoundingClientRect().width));
    expect(Math.min(...widths)).toBeGreaterThan(300);
  });

  for (const width of [360, 768, 1280, 1920]) {
    test(`UX-01 the Board with episodes fits at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await openBoard(page, [
        ...SAMPLE_EPISODES,
        episode(8, { idea: `${"Unbreakable".repeat(12)} and a long idea ${"word ".repeat(60)}` }),
      ]);
      await expect(page.getByRole("article").first()).toBeVisible();

      expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
    });
  }

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`UX-05 axe finds no violations on the Board with episodes on ${size}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openBoard(page);
      await expect(page.getByRole("article").first()).toBeVisible();

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
  }

  test("UX-04 group headers on a phone are at least 44 px tall", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await openBoard(page);

    await expect(groups(page).getByRole("button")).toHaveCount(3);
    for (const header of await groups(page).getByRole("button").all()) {
      expect((await header.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    }
  });
});

test.describe("UX-06 the Board has loading, empty and error states", () => {
  test("while the episodes load it says so, and never claims there are none", async ({ page }) => {
    let answer: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      answer = resolve;
    });
    await page.route("**/api/v1/episodes?*", async (route: Route) => {
      await held;
      await route.fulfill({
        json: { episodes: SAMPLE_EPISODES, total: SAMPLE_EPISODES.length, limit: 50, offset: 0 },
      });
    });
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    await expect(page.getByTestId("board-loading")).toBeVisible();
    await expect(page.getByTestId("board-loading")).toHaveAttribute("aria-busy", "true");
    await expect(page.getByTestId("board-loading")).toContainText("Loading the episodes");
    await expect(page.getByText("No episodes yet")).toBeHidden();
    await expect(page.getByText("0 episodes")).toBeHidden();

    answer();
    await expect(card(page, "The Lighthouse Keeper")).toBeVisible();
    await expect(page.getByTestId("board-loading")).toBeHidden();
  });

  test("with no episodes it explains what belongs here", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page, []);

    await expect(page.getByRole("heading", { name: "No episodes yet" })).toBeVisible();
    await expect(page.getByText("0 episodes")).toBeVisible();
    await expect(groups(page)).toBeHidden();
  });

  test("when the API refuses, it shows the reason and Try again, not an empty Board", async ({
    page,
  }) => {
    let broken = true;
    await page.route("**/api/v1/episodes?*", async (route: Route) => {
      if (broken) {
        await route.fulfill({
          status: 503,
          json: {
            error: {
              code: "unavailable",
              message: "The database is not answering. Start it and try again.",
            },
          },
        });
      } else {
        await route.fulfill({
          json: { episodes: SAMPLE_EPISODES, total: SAMPLE_EPISODES.length, limit: 50, offset: 0 },
        });
      }
    });
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    const alert = page.getByTestId("board-error");
    await expect(alert).toHaveRole("alert");
    await expect(alert).toContainText("The episodes could not be loaded");
    await expect(alert).toContainText("The database is not answering. Start it and try again.");
    await expect(page.getByText("No episodes yet")).toBeHidden();
    await expect(page.getByText("0 episodes")).toBeHidden();

    broken = false;
    await alert.getByRole("button", { name: "Try again" }).click();
    await expect(card(page, "The Lighthouse Keeper")).toBeVisible();
    await expect(alert).toBeHidden();
  });

  test("when the API does not answer at all, it says what to check", async ({ page }) => {
    await page.route("**/api/v1/episodes?*", (route: Route) => route.abort());
    await page.setViewportSize(SIZES.phone);
    await open(page);

    const alert = page.getByTestId("board-error");
    await expect(alert).toContainText("The episodes could not be loaded");
    await expect(alert).toContainText("The API is not answering");
    await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
    await expect(page.getByText("No episodes yet")).toBeHidden();
  });

  test("it picks up changes by itself", async ({ page }) => {
    let list = [episode(1, { title: "The Second Bowl", state: "research" })];
    await page.clock.install();
    await mockEpisodes(page, () => list);
    await page.setViewportSize(SIZES.desktop);
    await open(page);
    await expect(card(page, "The Second Bowl")).toContainText("Checking sources");

    list = [
      episode(1, {
        title: "The Second Bowl",
        state: "direction",
        awaiting_approval: true,
        gate: "plan",
      }),
    ];
    await page.clock.fastForward(6_000);

    await expect(group(page, "needs-you").getByRole("article")).toContainText("Approve the plan");
  });

  test("a refresh that fails keeps the episodes on screen and says they may be old", async ({
    page,
  }) => {
    let broken = false;
    await page.clock.install();
    await page.route("**/api/v1/episodes?*", async (route: Route) => {
      if (broken) {
        return route.abort();
      }
      await route.fulfill({
        json: { episodes: SAMPLE_EPISODES, total: SAMPLE_EPISODES.length, limit: 50, offset: 0 },
      });
    });
    await page.setViewportSize(SIZES.desktop);
    await open(page);
    await expect(card(page, "The Lighthouse Keeper")).toBeVisible();

    broken = true;
    await page.clock.fastForward(6_000);

    await expect(page.getByTestId("board-stale")).toContainText("could not be refreshed");
    await expect(card(page, "The Lighthouse Keeper")).toBeVisible();

    broken = false;
    await page.clock.fastForward(6_000);
    await expect(page.getByTestId("board-stale")).toBeHidden();
  });

  test("more episodes than one page are never cut off silently", async ({ page }) => {
    const many = Array.from({ length: 120 }, (_, index) =>
      episode(index + 1, { title: `Episode ${index + 1}`, state: "done" }),
    );
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page, many);

    await expect(page.getByText("120 episodes", { exact: true })).toBeVisible();
    await expect(page.getByText("Showing 50 of 120 episodes")).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(50);

    await page.getByRole("button", { name: "Show more" }).click();
    await expect(page.getByText("Showing 100 of 120 episodes")).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(100);

    await page.getByRole("button", { name: "Show more" }).click();
    await expect(page.getByRole("article")).toHaveCount(120);
    await expect(page.getByRole("button", { name: "Show more" })).toBeHidden();
    await expect(page.getByText(/Showing \d+ of/)).toBeHidden();
  });

  test("the status strip counts the episodes that wait for you", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page);

    await expect(page.getByTestId("waiting-status")).toHaveAccessibleName("2 waiting for you");
  });
});

test.describe("New episode", () => {
  const dialog = (page: Page) => page.getByRole("dialog", { name: "New episode" });
  const idea = (page: Page) => dialog(page).getByRole("textbox", { name: "Idea" });
  const start = (page: Page) => dialog(page).getByRole("button", { name: "Start" });

  /** Collect what the dialog sends, and answer it. */
  async function mockCreate(
    page: Page,
    answer: (body: unknown) => { status: number; json: unknown },
  ) {
    const sent: unknown[] = [];
    await page.route("**/api/v1/episodes", async (route: Route) => {
      if (route.request().method() !== "POST") {
        return route.fallback();
      }
      const body: unknown = route.request().postDataJSON();
      sent.push(body);
      await route.fulfill(answer(body));
    });
    return sent;
  }

  test("on desktop it opens as a centred dialog 560 px wide", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page);

    await page.getByTestId("side-nav").getByRole("link", { name: "New episode" }).click();
    await expect(page).toHaveURL(/\/episodes\/new$/);
    await expect(dialog(page)).toBeVisible();
    const box = await dialog(page).boundingBox();
    expect(box?.width).toBe(560);
    expect(Math.round((box?.x ?? 0) + 280)).toBe(720);
    await expect(idea(page)).toBeFocused();
    await expect(dialog(page).getByRole("radio", { name: "45 seconds" })).toBeChecked();
    await expect(dialog(page).getByRole("radio", { name: "60 seconds" })).not.toBeChecked();
    await expect(start(page)).toBeVisible();
  });

  test("on tablet it is the same 560 px dialog", async ({ page }) => {
    await page.setViewportSize(SIZES.tablet);
    await openBoard(page);
    await page.goto("/episodes/new");

    expect((await dialog(page).boundingBox())?.width).toBe(560);
  });

  test("UX-03 on a phone it is a full-screen sheet", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await openBoard(page);

    await page.getByTestId("floating-new-episode").click();
    await expect(dialog(page)).toBeVisible();
    expect(await dialog(page).boundingBox()).toEqual({ x: 0, y: 0, width: 390, height: 844 });
    expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
  });

  test("Start sends the idea and the length, then opens the episode", async ({
    page,
  }) => {
    const list = [...SAMPLE_EPISODES];
    await mockEpisodes(page, () => list);
    const sent = await mockCreate(page, () => {
      const created = episode(50, { idea: "A clock that only runs when someone is kind" });
      list.unshift(created);
      return { status: 201, json: { ...created, jobs: [] } };
    });
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/episodes/new");

    await idea(page).fill("  A clock that only runs when someone is kind  ");
    await dialog(page).getByRole("radio", { name: "60 seconds" }).check();
    await start(page).click();

    await expect(page).toHaveURL(/\/episodes\/00000000-0000-4000-8000-000000000050$/);
    await expect(dialog(page)).toBeHidden();
    expect(sent).toEqual([
      { idea: "A clock that only runs when someone is kind", target_duration_s: 60, start: true },
    ]);

    await page.goto("/");
    await expect(
      page
        .getByTestId("group-planning")
        .getByRole("heading", { name: "A clock that only runs when someone is kind" }),
    ).toBeVisible();
  });

  test("Start without an idea asks for one and sends nothing", async ({ page }) => {
    await mockEpisodes(page, () => []);
    const sent = await mockCreate(page, () => ({ status: 500, json: {} }));
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/episodes/new");

    await idea(page).fill("   ");
    await start(page).click();

    await expect(dialog(page).getByText("Write the idea first.")).toBeVisible();
    await expect(idea(page)).toHaveAttribute("aria-invalid", "true");
    await expect(idea(page)).toBeFocused();
    expect(sent).toEqual([]);

    await idea(page).fill("Now there is one");
    await expect(dialog(page).getByText("Write the idea first.")).toBeHidden();
  });

  test("an idea longer than the API takes cannot be typed past the limit", async ({ page }) => {
    await mockEpisodes(page, () => []);
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/episodes/new");

    await expect(idea(page)).toHaveAttribute("maxlength", "4000");
  });

  test("when the API refuses, the reason is shown and the idea is kept", async ({ page }) => {
    await mockEpisodes(page, () => []);
    let refuse = true;
    const sent = await mockCreate(page, () =>
      refuse
        ? {
            status: 503,
            json: {
              error: { code: "unavailable", message: "The database is not answering. Try again." },
            },
          }
        : { status: 201, json: { ...episode(51, { idea: "Keep me" }), jobs: [] } },
    );
    await page.setViewportSize(SIZES.phone);
    await open(page, "/episodes/new");

    await idea(page).fill("Keep me");
    await start(page).click();

    await expect(dialog(page).getByRole("alert")).toContainText(
      "The database is not answering. Try again.",
    );
    await expect(idea(page)).toHaveValue("Keep me");
    await expect(start(page)).toBeEnabled();
    await expect(page).toHaveURL(/\/episodes\/new$/);

    refuse = false;
    await start(page).click();
    await expect(page).toHaveURL(/\/episodes\/00000000-0000-4000-8000-000000000051$/);
    expect(sent).toHaveLength(2);
  });

  test("when the API does not answer, it says what to check", async ({ page }) => {
    await mockEpisodes(page, () => []);
    await page.route("**/api/v1/episodes", (route: Route) =>
      route.request().method() === "POST" ? route.abort() : route.fallback(),
    );
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/episodes/new");

    await idea(page).fill("An idea");
    await start(page).click();

    await expect(dialog(page).getByRole("alert")).toContainText("The API is not answering");
    await expect(idea(page)).toHaveValue("An idea");
  });

  test("while it starts, Start cannot be pressed twice", async ({ page }) => {
    await mockEpisodes(page, () => []);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let posts = 0;
    await page.route("**/api/v1/episodes", async (route: Route) => {
      if (route.request().method() !== "POST") {
        return route.fallback();
      }
      posts += 1;
      await held;
      await route.fulfill({ status: 201, json: { ...episode(52), jobs: [] } });
    });
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/episodes/new");

    await idea(page).fill("An idea");
    await start(page).click();

    const busy = dialog(page).getByRole("button", { name: "Starting" });
    await expect(busy).toBeDisabled();
    release();
    await expect(page).toHaveURL(/\/episodes\/00000000-0000-4000-8000-000000000052$/);
    expect(posts).toBe(1);
  });

  test("Escape, Cancel and Close all go back to the Board", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openBoard(page);

    await page.goto("/episodes/new");
    await expect(dialog(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/\/$/);
    await expect(dialog(page)).toBeHidden();
    await expect(page.getByRole("heading", { level: 1, name: "Board" })).toBeVisible();

    await page.goto("/episodes/new");
    await dialog(page).getByRole("link", { name: "Cancel" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.goto("/episodes/new");
    await dialog(page).getByRole("link", { name: "Close" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("UX-04 the dialog can be used with the keyboard alone", async ({ page }) => {
    const list: EpisodeRow[] = [];
    await mockEpisodes(page, () => list);
    const sent = await mockCreate(page, () => ({
      status: 201,
      json: { ...episode(53), jobs: [] },
    }));
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/episodes/new");

    await expect(idea(page)).toBeFocused();
    await page.keyboard.type("Typed with the keyboard");
    await page.keyboard.press("Tab");
    await expect(dialog(page).getByRole("radio", { name: "45 seconds" })).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(dialog(page).getByRole("radio", { name: "60 seconds" })).toBeChecked();
    await page.keyboard.press("Tab");
    await expect(dialog(page).getByRole("link", { name: "Cancel" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(start(page)).toBeFocused();
    const outline = await start(page).evaluate((element) => getComputedStyle(element).outlineStyle);
    expect(outline).not.toBe("none");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/episodes\/00000000-0000-4000-8000-000000000053$/);
    expect(sent).toEqual([
      { idea: "Typed with the keyboard", target_duration_s: 60, start: true },
    ]);
  });

  for (const size of ["phone", "tablet"] as const) {
    test(`UX-04 touch targets in the dialog are at least 44 by 44 px on ${size}`, async ({
      page,
    }) => {
      await mockEpisodes(page, () => []);
      await page.setViewportSize(SIZES[size]);
      await open(page, "/episodes/new");
      await expect(dialog(page)).toBeVisible();

      const targets = dialog(page).locator("a:visible, button:visible, label:has(input[type=radio])");
      expect(await targets.count()).toBe(5);
      for (const target of await targets.all()) {
        const box = await target.boundingBox();
        const name = (await target.innerText()).trim() || (await target.getAttribute("aria-label"));
        expect(box?.width, `"${name}" is too narrow`).toBeGreaterThanOrEqual(44);
        expect(box?.height, `"${name}" is too short`).toBeGreaterThanOrEqual(44);
      }
    });
  }
});

test.describe("UX-03 an episode from idea to the plan gate, through the real API", () => {
  test("on a 390 px phone: New episode, idea, Start, and later the Board asks to approve the plan", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await page.setViewportSize(SIZES.phone);
    await open(page);

    await page.getByTestId("floating-new-episode").click();
    const dialog = page.getByRole("dialog", { name: "New episode" });
    await dialog.getByRole("textbox", { name: "Idea" }).fill("A keeper who climbs the hill every night");
    const created = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/episodes") && response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Start" }).click();
    const response = await created;
    expect(response.status()).toBe(201);
    const { id } = (await response.json()) as { id: string };

    await expect(page).toHaveURL(new RegExp(`/episodes/${id}$`));
    await page.goto("/");
    const mine = page.locator(`[data-episode-id="${id}"]:visible`);
    await expect(mine).toBeVisible();
    await expect(mine).toContainText("Approve the plan", { timeout: 150_000 });
    await expect(page.getByTestId("group-needs-you").locator(`[data-episode-id="${id}"]`)).toBeVisible();
  });
});

test.describe("Board and New episode match their approved screenshots", () => {
  test.skip(process.platform !== "linux", "screenshots are compared in the Linux test image only");

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`Board with episodes at ${viewport.width} px (${size})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openBoard(page);
      await expect(card(page, "The Lighthouse Keeper")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      await expect(page).toHaveScreenshot(`board-episodes-${viewport.width}.png`, {
        fullPage: true,
      });
    });

    test(`New episode at ${viewport.width} px (${size})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await mockEpisodes(page, () => SAMPLE_EPISODES);
      await open(page, "/episodes/new");
      await expect(page.getByRole("dialog", { name: "New episode" })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      await expect(page).toHaveScreenshot(`new-episode-${viewport.width}.png`);
    });
  }
});
