// End-to-end tests for what follows the plan gate in milestone M2: the pictures gate, the
// Render tab, a rendered episode and a step that failed (design doc sections 4.1, 4.4 and
// 11.5, FR-16). The episode routes are answered by a stand-in. The same journey through
// the real API and worker is in demo.spec.ts.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { SAMPLE_EPISODES, SIZES, WCAG_TAGS, mockEpisodes, open, sidewaysOverflow } from "./support";
import {
  type FakeEpisode,
  SHEET_URL,
  VIDEO_URL,
  fakeEpisode,
  job,
  mockEpisode,
  render,
  workspacePath,
} from "./workspace-support";

async function openWorkspace(page: Page, fake: FakeEpisode) {
  await mockEpisodes(page, () => [fake.episode, ...SAMPLE_EPISODES.slice(2)]);
  await mockEpisode(page, fake);
  // No video file is behind the stand-in. The player only needs an answer.
  await page.route("**/api/v1/files/**", (route) => route.fulfill({ status: 404, body: "" }));
  await open(page, workspacePath());
  return fake;
}

const status = (page: Page) => page.getByTestId("episode-status");
const gate = (page: Page) => page.getByTestId("gate-bar");
const pipeline = (page: Page) => page.getByRole("list", { name: "Pipeline" });
const panel = (page: Page) => page.getByRole("tabpanel");
const trouble = (page: Page) => page.getByTestId("step-failed");
const sent = (fake: FakeEpisode, method: string, path: string) =>
  fake.requests.filter((request) => request.method === method && request.path === path);

async function renderTab(page: Page) {
  await page.getByRole("tab", { name: "Render" }).click();
  return panel(page);
}

function jobs(type: string, statuses: string[]) {
  return statuses.map((state) => job(type, state));
}

const atPictures = () =>
  fakeEpisode({ state: "asset_gen", awaiting_approval: true, gate: "assets" });

function rendered(): FakeEpisode {
  const fake = fakeEpisode({ state: "render", awaiting_approval: false, gate: null, resting: true });
  fake.jobs = [job("render.join", "succeeded"), ...jobs("render.scene", Array(3).fill("succeeded"))];
  fake.renders = [render()];
  return fake;
}

test.describe("Pictures gate", () => {
  test("says what waits and that the library pictures need no new work", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, atPictures());

    await expect(status(page)).toHaveText("Pictures need you");
    await expect(gate(page)).toContainText("The pictures are ready.");
    await expect(gate(page).getByRole("button", { name: "Approve pictures" })).toBeVisible();
  });

  test("Approve pictures passes the gate, and the voice starts", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, atPictures());

    await gate(page).getByRole("button", { name: "Approve pictures" }).click();

    await expect(gate(page)).toBeHidden();
    await expect(status(page)).toHaveText("Recording the voice");
    expect(sent(fake, "POST", "/approve")).toHaveLength(1);
  });

  test("UX-03 on a phone the pictures gate stays in reach above the bottom bar", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await openWorkspace(page, atPictures());

    const button = gate(page).getByRole("button", { name: "Approve pictures" });
    await expect(button).toBeInViewport();
    const box = await button.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
  });
});

test.describe("Render tab", () => {
  test("before anything is made it says when the video appears", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fakeEpisode());

    const tab = await renderTab(page);

    await expect(tab).toContainText("The video appears here after the plan and the pictures are approved.");
    await expect(tab.locator("video")).toHaveCount(0);
  });

  test("UX-06 while the voice is recorded it says how many scenes are done", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = fakeEpisode({ state: "voice", awaiting_approval: false, gate: null });
    fake.jobs = jobs("gen.voice", ["running", "queued", "queued", "queued", "succeeded", "succeeded", "succeeded"]);
    await openWorkspace(page, fake);

    const tab = await renderTab(page);

    await expect(tab.getByRole("heading", { name: "Recording the voice" })).toBeVisible();
    await expect(tab).toContainText("3 of 7 scenes");
    const bar = tab.getByRole("progressbar", { name: "Recording the voice" });
    await expect(bar).toHaveAttribute("aria-valuenow", "3");
    await expect(bar).toHaveAttribute("aria-valuemax", "7");
  });

  test("UX-06 while scenes are encoded it counts them, and then says that it joins them", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = fakeEpisode({ state: "render", awaiting_approval: false, gate: null });
    fake.jobs = [
      ...jobs("render.scene", ["running", "running", "succeeded", "succeeded", "succeeded", "succeeded", "succeeded"]),
      ...jobs("gen.voice", Array(7).fill("succeeded")),
    ];
    await openWorkspace(page, fake);

    const tab = await renderTab(page);
    await expect(tab.getByRole("heading", { name: "Rendering the video" })).toBeVisible();
    await expect(tab).toContainText("5 of 7 scenes");

    fake.jobs = [job("render.join", "running"), ...jobs("render.scene", Array(7).fill("succeeded"))];
    await expect(tab).toContainText("Joining the scenes and mixing the sound");
  });

  test("FR-16 a rendered episode shows its video, its length and the plan it came from", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, rendered());

    const tab = await renderTab(page);

    const video = tab.locator("video");
    await expect(video).toHaveAttribute("src", VIDEO_URL);
    await expect(video).toHaveAttribute("controls", "");
    await expect(video).toHaveAttribute("preload", "none");
    await expect(video).toHaveAccessibleName("Draft video of The Gardener Nobody Watched");
    await expect(tab).toContainText("Draft video, 44 seconds");
    await expect(tab).toContainText("version 1 of the plan");
    await expect(tab.getByRole("link", { name: "Open the contact sheet" })).toHaveAttribute("href", SHEET_URL);
    await expect(tab).toContainText("Quality checks, the review and the export are not built yet.");
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Render");
  });

  test("on a wide screen the preview beside the plan shows the video, and the Render tab shows it once", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await openWorkspace(page, rendered());

    const preview = page.getByRole("complementary", { name: "Preview" });
    await expect(preview.locator("video")).toHaveAttribute("src", VIDEO_URL);
    await expect(page.locator("video:visible")).toHaveCount(1);

    await renderTab(page);
    await expect(preview).toBeHidden();
    await expect(page.locator("video:visible")).toHaveCount(1);
  });

  test("a video that is longer than a minute gives minutes and seconds", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = rendered();
    fake.renders = [render({ duration_s: 61.4, spec_version: 3 })];
    await openWorkspace(page, fake);

    const tab = await renderTab(page);

    await expect(tab).toContainText("Draft video, 1 minute 1 second");
    await expect(tab).toContainText("version 3 of the plan");
  });

  test("the video is never cropped: 9 by 16 and at most 70 percent of the screen high", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, rendered());

    const box = await (await renderTab(page)).locator("video").boundingBox();

    const { width, height } = box ?? { width: 0, height: 0 };
    expect(height).toBeGreaterThan(200);
    expect(height).toBeLessThanOrEqual(SIZES.desktop.height * 0.7 + 1);
    expect(width / height).toBeCloseTo(9 / 16, 1);
  });
});

test.describe("A rendered episode", () => {
  test("reads as finished: the chip, the pipeline and no gate", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, rendered());

    await expect(status(page)).toHaveText("Video rendered");
    await expect(pipeline(page).getByRole("listitem").filter({ hasText: "Render" })).toHaveText(
      "Render, done",
    );
    await expect(pipeline(page).getByRole("listitem").filter({ hasText: "Review" })).toHaveText(
      "Review, not started",
    );
    await expect(pipeline(page).locator("[aria-current]")).toHaveCount(0);
    await expect(gate(page)).toBeHidden();
  });

  test("is listed under Finished on the Board with Video rendered", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = rendered();
    await mockEpisodes(page, () => [fake.episode, ...SAMPLE_EPISODES.slice(2)]);
    await open(page);

    const card = page.getByTestId("group-finished").getByRole("article").filter({
      hasText: "The Gardener Nobody Watched",
    });
    await expect(card).toContainText("Video rendered");
    await expect(page.getByTestId("group-producing")).not.toContainText("The Gardener Nobody Watched");
  });
});

test.describe("A step that failed (section 4.4)", () => {
  const MESSAGE =
    "The voice model files are missing and there is no bundled sample for this narration. " +
    "Download the voice model with: make models";

  function stuck(): FakeEpisode {
    const fake = fakeEpisode({ state: "voice", awaiting_approval: false, gate: null });
    fake.jobs = [
      job("gen.voice", "failed", { error_class: "needs_owner", error_message: MESSAGE }),
      ...jobs("gen.voice", ["succeeded", "succeeded"]),
    ];
    return fake;
  }

  test("shows the reason on the episode page, whatever tab is open", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, stuck());

    await expect(trouble(page)).toHaveRole("alert");
    await expect(trouble(page)).toContainText("Recording the voice stopped");
    await expect(trouble(page)).toContainText(MESSAGE);
    await expect(status(page)).toHaveText("Voice stopped");
    const tab = await renderTab(page);
    await expect(trouble(page)).toContainText(MESSAGE);
    await expect(tab).toContainText("The video appears here once the step that stopped has run again.");
  });

  test("Run this step again runs the state again", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, stuck());

    await trouble(page).getByRole("button", { name: "Run this step again" }).click();

    await expect(trouble(page)).toBeHidden();
    await expect(status(page)).toHaveText("Recording the voice");
    expect(sent(fake, "POST", "/rerun")[0]?.body).toEqual({ state: "voice" });
  });

  test("a failed job is not shown while the step is still working", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = stuck();
    fake.jobs = [job("gen.voice", "running"), ...fake.jobs];
    await openWorkspace(page, fake);

    await expect(status(page)).toHaveText("Recording the voice");
    await expect(trouble(page)).toBeHidden();
  });

  test("the same reason is shown once, however many scenes it stopped", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = stuck();
    fake.jobs = [
      job("gen.voice", "failed", { error_class: "needs_owner", error_message: MESSAGE }),
      ...fake.jobs,
    ];
    await openWorkspace(page, fake);

    await expect(trouble(page).getByText(MESSAGE)).toHaveCount(1);
  });
});

test.describe("Render tab at every size", () => {
  for (const width of [360, 768, 1280, 1920]) {
    test(`UX-01 it fits at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await openWorkspace(page, rendered());
      await expect((await renderTab(page)).locator("video")).toBeVisible();

      expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
    });
  }

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`UX-05 axe finds no violations on ${size}, with the video and with a failed step`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      const fake = rendered();
      await openWorkspace(page, fake);
      await expect((await renderTab(page)).locator("video")).toBeVisible();
      const withVideo = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(withVideo.violations.map((violation) => violation.id)).toEqual([]);

      fake.episode = { ...fake.episode, state: "voice", resting: false };
      fake.renders = [];
      fake.jobs = [job("gen.voice", "failed", { error_class: "needs_owner", error_message: "Run: make models" })];
      await expect(trouble(page)).toBeVisible();
      const withTrouble = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(withTrouble.violations.map((violation) => violation.id)).toEqual([]);
    });
  }

  for (const size of ["phone", "tablet"] as const) {
    test(`UX-04 touch targets are at least 44 by 44 px on ${size}`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await openWorkspace(page, rendered());
      const tab = await renderTab(page);
      await expect(tab.locator("video")).toBeVisible();

      const targets = tab.locator("a:visible, button:visible");
      expect(await targets.count()).toBeGreaterThan(0);
      for (const target of await targets.all()) {
        const box = await target.boundingBox();
        expect(box?.width).toBeGreaterThanOrEqual(44);
        expect(box?.height).toBeGreaterThanOrEqual(44);
      }
    });
  }
});
