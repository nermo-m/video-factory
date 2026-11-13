// End-to-end tests for the episode workspace and its Plan tab (design doc sections 11.2
// and 11.5, FR-03, and the workspace mockups). The episode routes are answered by a
// stand-in, except in the last group, which goes through the real API and worker.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { SAMPLE_EPISODES, SIZES, WCAG_TAGS, mockEpisodes, open, sidewaysOverflow } from "./support";
import {
  EPISODE_ID,
  type FakeEpisode,
  type Scene,
  fakeEpisode,
  mockEpisode,
  workspacePath,
} from "./workspace-support";

async function openWorkspace(page: Page, fake: FakeEpisode = fakeEpisode()) {
  await mockEpisodes(page, () => [fake.episode, ...SAMPLE_EPISODES.slice(2)]);
  await mockEpisode(page, fake);
  await open(page, workspacePath());
  return fake;
}

const scene = (page: Page, number: number) =>
  page.getByRole("article").filter({ has: page.getByRole("heading", { name: `Scene ${number},` }) });
const status = (page: Page) => page.getByTestId("episode-status");
const pipeline = (page: Page) => page.getByRole("list", { name: "Pipeline" });
const gate = (page: Page) => page.getByTestId("gate-bar");
const duration = (page: Page) => page.getByTestId("duration");
const sent = (fake: FakeEpisode, method: string, path: string) =>
  fake.requests.filter((request) => request.method === method && request.path === path);

test.describe("Workspace frame", () => {
  test("shows the title, what the episode needs, its length and where it came from", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page);

    await expect(page.getByRole("heading", { level: 1, name: "The Gardener Nobody Watched" })).toBeVisible();
    await expect(status(page)).toHaveText("Plan needs you");
    await expect(page.getByText("45 seconds, 3 scenes")).toBeVisible();
    const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(crumbs).toContainText("Board");
    await expect(crumbs).toContainText("The Gardener Nobody Watched");
    await crumbs.getByRole("link", { name: "Board" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("the pipeline lists eight steps and says how far each one is", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page);

    await expect(pipeline(page).getByRole("listitem")).toHaveText([
      /Brief.*done/,
      /Research.*done/,
      /Script.*done/,
      /Plan.*waiting for you/,
      /Assets.*not started/,
      /Voice.*not started/,
      /Render.*not started/,
      /Review.*not started/,
    ]);
    await expect(pipeline(page).locator('[aria-current="step"]')).toContainText("Plan");
  });

  test("on desktop the pipeline is a column beside the content, on a phone a row above it", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page);
    const items = pipeline(page).getByRole("listitem");
    const first = await items.nth(0).boundingBox();
    const second = await items.nth(1).boundingBox();
    expect(second?.y).toBeGreaterThan(first?.y ?? 0);
    expect(second?.x).toBe(first?.x);

    await page.setViewportSize(SIZES.phone);
    const firstOnPhone = await items.nth(0).boundingBox();
    const secondOnPhone = await items.nth(1).boundingBox();
    expect(secondOnPhone?.x).toBeGreaterThan(firstOnPhone?.x ?? 0);
    expect(secondOnPhone?.y).toBe(firstOnPhone?.y);
    expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
  });

  test("the tabs are Plan, Assets, Voice, Render and Export, and the later ones say so honestly", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page);

    const tabs = page.getByRole("tablist", { name: "Episode" }).getByRole("tab");
    await expect(tabs).toHaveText(["Plan", "Assets", "Voice", "Render", "Export"]);
    await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");

    // Voice and Export are still to come, and say so.
    await tabs.nth(2).click();
    await expect(page.getByRole("tabpanel", { name: "Voice" })).toContainText("Not built yet");
    await tabs.nth(4).click();
    await expect(page.getByRole("tabpanel", { name: "Export" })).toContainText("Not built yet");

    await tabs.nth(1).click();
    await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel", { name: "Assets" })).toContainText(
      "The pictures appear here after the plan is approved.",
    );
    await expect(scene(page, 1)).toBeHidden();

    await tabs.nth(1).press("ArrowLeft");
    await expect(tabs.nth(0)).toBeFocused();
    await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");
    await expect(scene(page, 1)).toBeVisible();
  });

  test("while the plan is being written it shows the steps ticking off", async ({ page }) => {
    const fake = fakeEpisode({ state: "research", awaiting_approval: false, gate: null, title: null });
    fake.spec = null;
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "A gardener who waters one bed every morning",
    );
    await expect(status(page)).toHaveText("Checking sources");
    await expect(page.getByTestId("plan-pending")).toContainText("The plan is being written");
    await expect(pipeline(page).getByRole("listitem").nth(0)).toHaveText(/Brief.*done/);
    await expect(pipeline(page).getByRole("listitem").nth(1)).toHaveText(/Research.*in progress/);
    await expect(gate(page)).toBeHidden();

    fake.spec = fakeEpisode().spec;
    fake.episode = { ...fake.episode, state: "direction", awaiting_approval: true, gate: "plan" };
    await expect(scene(page, 1)).toBeVisible({ timeout: 10_000 });
    await expect(status(page)).toHaveText("Plan needs you");
  });

  test("an episode that was not started offers to start planning", async ({ page }) => {
    const fake = fakeEpisode({ state: "idea", awaiting_approval: false, gate: null });
    fake.spec = null;
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await page.getByRole("button", { name: "Start planning" }).click();
    await expect(page.getByTestId("plan-pending")).toContainText("The plan is being written");
    expect(sent(fake, "POST", "/advance")).toHaveLength(1);
  });
});

test.describe("Plan tab", () => {
  test("shows the brief, the claims with their sources, and the scenes in order", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page);

    const brief = page.getByRole("region", { name: "Brief" });
    await expect(brief).toContainText("One small thing, done daily, is a start.");
    await expect(brief).toContainText("A gardener waters one bed every morning");
    await expect(brief).toContainText("Someone who thinks one small step is too small to matter.");

    const claims = page.getByRole("region", { name: "Claims" });
    await expect(claims).toContainText("daily gardeners kept the habit for a year");
    await expect(
      claims.getByRole("link", { name: "Example Garden Study (test fixture)" }),
    ).toHaveAttribute("href", "https://example.org/fixture/garden-study");

    await expect(page.getByRole("article").getByRole("heading")).toHaveText([
      "Scene 1, Title",
      "Scene 2, THE GARDEN",
      "Scene 3, Outro",
    ]);
  });

  test("a scene card shows narration, on-screen text, visual, overlays, sound, the question and its seconds", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page);

    const second = scene(page, 2);
    await expect(second).toContainText(
      "The gardener watered the same bed every morning. Nobody asked her to.",
    );
    await expect(second).toContainText("Text: THE GARDEN / DAY ONE / nobody was watching");
    await expect(second).toContainText("Picture: a_garden_dawn");
    await expect(second).toContainText("Tag: EVERY MORNING");
    await expect(second).toContainText("Sprite: moon, glow");
    await expect(second).toContainText("Sound: paper_unroll");
    await expect(second).toContainText("Out: smoke");
    await expect(second).toContainText("Leaves the viewer asking: Why would anyone do this unseen?");
    await expect(second).toContainText("about 5.9 s");
    await expect(scene(page, 1)).toContainText("Text: ONE PLANT / IS A START.");
  });

  test("a plan without claims says that it states no facts", async ({ page }) => {
    const fake = fakeEpisode();
    if (fake.spec) {
      fake.spec.claims = [];
    }
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await expect(page.getByRole("region", { name: "Claims" })).toContainText(
      "This plan states no facts that need a source.",
    );
  });

  test("the duration bar gives the estimate against the target", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page);

    await expect(duration(page)).toContainText("Planned length");
    await expect(duration(page)).toContainText("about 14.3 s of 45 s");
    await expect(duration(page)).toHaveAttribute("data-fits", "true");
  });

  test("the duration bar turns red and says why when the plan does not fit", async ({ page }) => {
    const fake = fakeEpisode();
    fake.fits = false;
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await expect(duration(page)).toHaveAttribute("data-fits", "false");
    await expect(duration(page)).toContainText("too short");
    const colour = await duration(page)
      .getByTestId("duration-value")
      .evaluate((element) => getComputedStyle(element).color);
    expect(colour).toBe("rgb(255, 107, 107)");
  });

  test("FR-03 a scene is edited in place and saved as a new version", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await scene(page, 2).getByRole("button", { name: "Edit scene 2" }).click();
    const narration = scene(page, 2).getByRole("textbox", { name: "Narration" });
    await expect(narration).toHaveValue(
      "The gardener watered the same bed every morning. Nobody asked her to.",
    );
    await narration.fill("She watered the same bed every morning.");
    await scene(page, 2).getByRole("textbox", { name: "Title" }).fill("THE BED");
    await scene(page, 2).getByRole("textbox", { name: "Sublabel" }).fill("");
    await scene(page, 2).getByRole("textbox", { name: "Question it leaves" }).fill("Why bother?");
    await scene(page, 2).getByRole("button", { name: "Save" }).click();

    await expect(scene(page, 2)).toContainText("She watered the same bed every morning.");
    await expect(scene(page, 2).getByRole("textbox")).toHaveCount(0);
    const puts = sent(fake, "PUT", "/spec");
    expect(puts).toHaveLength(1);
    const saved = (puts[0]?.body as { scenes: Scene[] }).scenes;
    expect(saved[1]).toMatchObject({
      id: "s02_garden",
      narration: "She watered the same bed every morning.",
      title: "THE BED",
      label: "DAY ONE",
      retention_device: "Why bother?",
    });
    expect(saved[1]).not.toHaveProperty("sublabel");
    expect(saved[0]).toEqual(fakeEpisode().spec?.scenes[0]);
    expect(saved[2]).toEqual(fakeEpisode().spec?.scenes[2]);
    await expect(page.getByText("Version 2")).toBeVisible();
  });

  test("Cancel leaves the scene as it was and sends nothing", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await scene(page, 2).getByRole("button", { name: "Edit scene 2" }).click();
    await scene(page, 2).getByRole("textbox", { name: "Narration" }).fill("Something else.");
    await scene(page, 2).getByRole("button", { name: "Cancel" }).click();

    await expect(scene(page, 2)).toContainText("Nobody asked her to.");
    expect(sent(fake, "PUT", "/spec")).toHaveLength(0);
  });

  test("an edit the API refuses shows every problem and keeps what was typed", async ({ page }) => {
    const fake = fakeEpisode();
    fake.refuseSpec = {
      status: 422,
      body: {
        error: {
          code: "invalid_spec",
          message: "The spec is not valid.",
          details: { problems: ["/scenes/1/narration: '' should be non-empty", "/scenes/1: too short"] },
        },
      },
    };
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await scene(page, 2).getByRole("button", { name: "Edit scene 2" }).click();
    await scene(page, 2).getByRole("textbox", { name: "Narration" }).fill("Kept.");
    await scene(page, 2).getByRole("button", { name: "Save" }).click();

    const alert = scene(page, 2).getByRole("alert");
    await expect(alert).toContainText("The spec is not valid.");
    await expect(alert).toContainText("/scenes/1/narration: '' should be non-empty");
    await expect(alert).toContainText("/scenes/1: too short");
    await expect(scene(page, 2).getByRole("textbox", { name: "Narration" })).toHaveValue("Kept.");
  });

  test("on a phone a scene folds to narration and seconds, and opens on a tap", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await openWorkspace(page);

    const second = scene(page, 2);
    await expect(second).toContainText("Nobody asked her to.");
    await expect(second).toContainText("about 5.9 s");
    await expect(second.getByText("Tag: EVERY MORNING")).toBeHidden();

    await second.getByRole("button", { name: "Details of scene 2" }).click();
    await expect(second.getByText("Tag: EVERY MORNING")).toBeVisible();
    await expect(second.getByRole("button", { name: "Edit scene 2" })).toBeVisible();
  });
});

test.describe("Raw JSON", () => {
  test("the switch shows the spec as JSON, and a valid edit is saved", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await page.getByRole("button", { name: "Raw JSON" }).click();
    await expect(page.getByRole("button", { name: "Raw JSON" })).toHaveAttribute("aria-pressed", "true");
    const editor = page.getByRole("textbox", { name: "Spec as JSON" });
    const text = await editor.inputValue();
    expect(JSON.parse(text)).toEqual(fakeEpisode().spec);

    await editor.fill(text.replace('"seed": 7', '"seed": 8'));
    await page.getByRole("button", { name: "Save JSON" }).click();

    await expect(page.getByText("Version 2")).toBeVisible();
    expect((sent(fake, "PUT", "/spec")[0]?.body as { seed: number }).seed).toBe(8);
  });

  test("text that is not JSON is refused before anything is sent", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await page.getByRole("button", { name: "Raw JSON" }).click();
    await page.getByRole("textbox", { name: "Spec as JSON" }).fill('{"scenes": [');
    await page.getByRole("button", { name: "Save JSON" }).click();

    await expect(page.getByTestId("json-panel").getByRole("alert")).toContainText("This is not valid JSON");
    expect(sent(fake, "PUT", "/spec")).toHaveLength(0);
  });

  test("what the schema refuses is listed", async ({ page }) => {
    const fake = fakeEpisode();
    fake.refuseSpec = {
      status: 422,
      body: {
        error: {
          code: "invalid_spec",
          message: "The spec is not valid.",
          details: { problems: ["/seed: 'x' is not of type 'integer'"] },
        },
      },
    };
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await page.getByRole("button", { name: "Raw JSON" }).click();
    await page.getByRole("button", { name: "Save JSON" }).click();

    await expect(page.getByTestId("json-panel").getByRole("alert")).toContainText(
      "/seed: 'x' is not of type 'integer'",
    );
  });

  test("below 1024 px the JSON can be read but not edited", async ({ page }) => {
    await page.setViewportSize(SIZES.tablet);
    await openWorkspace(page);

    await page.getByRole("button", { name: "Raw JSON" }).click();
    await expect(page.getByRole("textbox", { name: "Spec as JSON" })).toHaveAttribute("readonly", "");
    await expect(page.getByTestId("json-panel")).toContainText("needs a screen at least 1024 px wide");
    await expect(page.getByRole("button", { name: "Save JSON" })).toBeHidden();
  });
});

test.describe("FR-03 a change asked for in words", () => {
  const comment = (page: Page) => page.getByRole("textbox", { name: "What should change?" });
  const proposal = (page: Page) => page.getByTestId("proposal");

  test("the comment becomes a proposal with its diff, and Apply stores it", async ({ page }) => {
    const fake = fakeEpisode();
    fake.revisionReadsUntilReady = 2;
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await comment(page).fill("End the hook with a hard cut.");
    await page.getByRole("button", { name: "Propose changes" }).click();

    await expect(proposal(page)).toContainText("Writing the proposal");
    await expect(proposal(page)).toContainText("The hook now ends with a hard cut instead of smoke.");
    await expect(proposal(page)).toContainText("Scene 1, transition out");
    await expect(proposal(page)).toContainText("smoke");
    await expect(proposal(page)).toContainText("cut");
    expect(sent(fake, "POST", "/revise")[0]?.body).toEqual({ comment: "End the hook with a hard cut." });
    expect(sent(fake, "PUT", "/spec")).toHaveLength(0);

    await proposal(page).getByRole("button", { name: "Apply" }).click();

    await expect(proposal(page)).toBeHidden();
    await expect(page.getByText("Version 2")).toBeVisible();
    await expect(scene(page, 1)).toContainText("Out: cut");
    await expect(comment(page)).toHaveValue("");
    expect(sent(fake, "POST", "/revise/apply")).toHaveLength(1);
    expect(sent(fake, "POST", "/revise/apply")[0]?.body).toHaveProperty("job_id");
  });

  test("Discard drops the proposal and changes nothing", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await comment(page).fill("End the hook with a hard cut.");
    await page.getByRole("button", { name: "Propose changes" }).click();
    await proposal(page).getByRole("button", { name: "Discard" }).click();

    await expect(proposal(page)).toBeHidden();
    await expect(scene(page, 1)).toContainText("Out: smoke");
    expect(sent(fake, "POST", "/revise/apply")).toHaveLength(0);
  });

  test("an added and a removed value are shown as such", async ({ page }) => {
    const fake = fakeEpisode();
    fake.revision.changes = [
      { op: "add", path: "/scenes/1/pad_after_s", new: 0.6 },
      { op: "remove", path: "/scenes/1/sublabel", old: "nobody was watching" },
      { op: "replace", path: "/voice/speed", old: 1, new: 1.1 },
    ];
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await comment(page).fill("Slow the second scene.");
    await page.getByRole("button", { name: "Propose changes" }).click();

    const rows = proposal(page).getByRole("listitem");
    await expect(rows).toHaveText([
      /Scene 2, pad after s.*Added.*0\.6/,
      /Scene 2, sublabel.*Removed.*nobody was watching/,
      /voice, speed.*1.*1\.1/,
    ]);
  });

  test("a proposal that failed says why and can be asked again", async ({ page }) => {
    const fake = fakeEpisode();
    fake.revision = { status: "failed", message: "The model's answer did not leave a valid spec." };
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fake);

    await comment(page).fill("Make it better.");
    await page.getByRole("button", { name: "Propose changes" }).click();

    await expect(proposal(page).getByRole("alert")).toContainText(
      "The model's answer did not leave a valid spec.",
    );
    await expect(proposal(page).getByRole("button", { name: "Apply" })).toBeHidden();
    await expect(comment(page)).toHaveValue("Make it better.");
    await expect(page.getByRole("button", { name: "Propose changes" })).toBeEnabled();
  });

  test("an empty comment asks for one and sends nothing", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await page.getByRole("button", { name: "Propose changes" }).click();

    await expect(page.getByText("Say what should change first.")).toBeVisible();
    expect(sent(fake, "POST", "/revise")).toHaveLength(0);
  });
});

test.describe("Gate bar", () => {
  test("Approve plan passes the gate", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await expect(gate(page)).toContainText("The plan is ready. Nothing is generated until you approve.");
    await gate(page).getByRole("button", { name: "Approve plan" }).click();

    await expect(gate(page)).toBeHidden();
    await expect(status(page)).toHaveText("Planning the pictures");
    expect(sent(fake, "POST", "/approve")).toHaveLength(1);
  });

  test("Request changes needs a comment and sends the plan back with it", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page);

    await gate(page).getByRole("button", { name: "Request changes" }).click();
    const reason = gate(page).getByRole("textbox", { name: "What should be different?" });
    await expect(reason).toBeFocused();
    await gate(page).getByRole("button", { name: "Send back" }).click();
    await expect(gate(page).getByText("Say what should be different first.")).toBeVisible();
    expect(sent(fake, "POST", "/reject")).toHaveLength(0);

    await reason.fill("Warmer, and open with the question.");
    await gate(page).getByRole("button", { name: "Send back" }).click();

    await expect(gate(page)).toBeHidden();
    expect(sent(fake, "POST", "/reject")[0]?.body).toEqual({
      comment: "Warmer, and open with the question.",
    });
  });

  test("there is no gate bar while nothing waits for the owner", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fakeEpisode({ state: "voice", awaiting_approval: false, gate: null }));

    await expect(scene(page, 1)).toBeVisible();
    await expect(gate(page)).toBeHidden();
  });

  test("UX-03 on a phone the gate bar stays in reach above the bottom bar", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await openWorkspace(page);

    await page.mouse.wheel(0, 600);
    const approve = gate(page).getByRole("button", { name: "Approve plan" });
    await expect(approve).toBeInViewport();
    const box = await approve.boundingBox();
    const bar = await page.getByTestId("bottom-nav").boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(bar?.y ?? 0);
  });
});

test.describe("UX-06 workspace states", () => {
  test("an episode that does not exist says so and leads back to the Board", async ({ page }) => {
    await mockEpisodes(page, () => []);
    await page.route(`**/api/v1/episodes/${EPISODE_ID}**`, (route) =>
      route.fulfill({
        status: 404,
        json: { error: { code: "not_found", message: "This episode does not exist." } },
      }),
    );
    await page.setViewportSize(SIZES.desktop);
    await open(page, workspacePath());

    await expect(page.getByRole("heading", { level: 1, name: "This episode does not exist" })).toBeVisible();
    await page.getByRole("main").getByRole("link", { name: "Back to the Board" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("a failed load shows the reason and Try again, and recovers", async ({ page }) => {
    const fake = fakeEpisode();
    let broken = true;
    await mockEpisodes(page, () => []);
    await mockEpisode(page, fake);
    await page.route(`**/api/v1/episodes/${EPISODE_ID}`, (route) =>
      broken
        ? route.fulfill({
            status: 503,
            json: { error: { code: "unavailable", message: "The database is not answering." } },
          })
        : route.fallback(),
    );
    await page.setViewportSize(SIZES.desktop);
    await open(page, workspacePath());

    const alert = page.getByTestId("workspace-error");
    await expect(alert).toHaveRole("alert");
    await expect(alert).toContainText("The database is not answering.");

    broken = false;
    await alert.getByRole("button", { name: "Try again" }).click();
    await expect(scene(page, 1)).toBeVisible();
  });

  test("while it loads it says so", async ({ page }) => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fake = fakeEpisode();
    await mockEpisodes(page, () => []);
    await mockEpisode(page, fake);
    await page.route(`**/api/v1/episodes/${EPISODE_ID}`, async (route) => {
      await held;
      await route.fallback();
    });
    await page.setViewportSize(SIZES.desktop);
    await open(page, workspacePath());

    await expect(page.getByTestId("workspace-loading")).toContainText("Loading the episode");
    release();
    await expect(scene(page, 1)).toBeVisible();
  });
});

test.describe("Workspace at every size", () => {
  for (const width of [360, 768, 1280, 1920]) {
    test(`UX-01 it fits at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await openWorkspace(page);
      await expect(scene(page, 1)).toBeVisible();
      expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);

      await page.getByRole("button", { name: "Raw JSON" }).click();
      await expect(page.getByTestId("json-panel")).toBeVisible();
      expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
    });
  }

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`UX-05 axe finds no violations on ${size}, also while editing`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openWorkspace(page);
      await expect(scene(page, 1)).toBeVisible();
      await scene(page, 2).getByRole("button", { name: "Edit scene 2" }).click({ force: size === "phone" });
      await page.getByRole("textbox", { name: "What should change?" }).fill("A change.");
      await page.getByRole("button", { name: "Propose changes" }).click();
      await expect(page.getByTestId("proposal").getByRole("button", { name: "Apply" })).toBeVisible();

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
  }

  for (const size of ["phone", "tablet"] as const) {
    test(`UX-04 touch targets are at least 44 by 44 px on ${size}`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await openWorkspace(page);
      await expect(scene(page, 1)).toBeVisible();

      const targets = page.getByRole("main").locator("a:visible, button:visible");
      expect(await targets.count()).toBeGreaterThan(8);
      for (const target of await targets.all()) {
        const box = await target.boundingBox();
        const name = (await target.getAttribute("aria-label")) ?? (await target.innerText()).trim();
        expect(box?.width, `"${name}" is too narrow`).toBeGreaterThanOrEqual(44);
        expect(box?.height, `"${name}" is too short`).toBeGreaterThanOrEqual(44);
      }
    });
  }

  test("a Board card opens its workspace", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = fakeEpisode();
    await mockEpisodes(page, () => [fake.episode]);
    await mockEpisode(page, fake);
    await open(page);

    await page.getByRole("link", { name: /The Gardener Nobody Watched/ }).click();

    await expect(page).toHaveURL(new RegExp(`/episodes/${EPISODE_ID}$`));
    await expect(page.getByRole("heading", { level: 1, name: "The Gardener Nobody Watched" })).toBeVisible();
  });
});

test.describe("FR-03 UX-03 from an idea to an approved plan, through the real API", () => {
  test("on a 390 px phone: idea, plan, a change in words, Apply, Approve plan", async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(SIZES.phone);
    await open(page);

    await page.getByTestId("floating-new-episode").click();
    const dialog = page.getByRole("dialog", { name: "New episode" });
    await dialog.getByRole("textbox", { name: "Idea" }).fill("A keeper who climbs the hill every night");
    await dialog.getByRole("button", { name: "Start" }).click();

    await expect(page).toHaveURL(/\/episodes\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("episode-status")).toHaveText("Plan needs you", { timeout: 150_000 });
    await expect(page.getByRole("article").first()).toBeVisible();
    await expect(page.getByText("Version 1")).toBeVisible();

    await page.getByRole("textbox", { name: "What should change?" }).fill("End the hook with a hard cut.");
    await page.getByRole("button", { name: "Propose changes" }).click();
    const proposal = page.getByTestId("proposal");
    await expect(proposal.getByRole("button", { name: "Apply" })).toBeVisible({ timeout: 60_000 });
    await proposal.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByText("Version 2")).toBeVisible();

    await page.getByTestId("gate-bar").getByRole("button", { name: "Approve plan" }).click();
    await expect(page.getByTestId("gate-bar")).toBeHidden();
    await expect(page.getByTestId("episode-status")).not.toHaveText("Plan needs you");
  });
});

test.describe("Workspace matches its approved screenshots", () => {
  test.skip(process.platform !== "linux", "screenshots are compared in the Linux test image only");

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`Plan tab at ${viewport.width} px (${size})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openWorkspace(page);
      await expect(scene(page, 1)).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      await expect(page).toHaveScreenshot(`workspace-plan-${viewport.width}.png`, { fullPage: true });
    });
  }
});
