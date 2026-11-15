// Director mode in the Plan tab: a plan of shots built from the owner's own prompt. What
// the studio changed is listed, the look and the characters are written once, and every
// field of every shot can be edited before anything is generated. The episode routes are
// answered by the stand-in of the workspace tests, with a plan of shots in it.
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

type Json = Record<string, unknown>;

const KEEPER = "A woman of about sixty, grey braid, yellow oilskin coat, lean and upright.";

function shots(): { scenes: Scene[] } & Json {
  return {
    spec_version: "2.1",
    episode_id: EPISODE_ID,
    format: { width: 1080, height: 1920, fps: 30, target_duration_s: 15 },
    theme: "plain",
    voice: { voice_id: "bm_george", speed: 1 },
    seed: 7,
    style: "Soft watercolour, muted blues, grain of rough paper.",
    captions: true,
    music: true,
    characters: [{ id: "keeper", name: "The keeper", description: KEEPER }],
    changes: [
      {
        scene: "lamp",
        kind: "added",
        what: "Low warm light from the left.",
        why: "The prompt gave no lighting for this scene.",
      },
      {
        scene: "hill",
        kind: "changed",
        what: "The scene lasts as long as its line.",
        why: "The line takes about 4 seconds to speak and the scene was given 2.",
      },
      {
        kind: "not_possible",
        what: "A piano under the last scene.",
        why: "The studio can only play its own soft music bed under the whole video.",
      },
    ],
    claims: [],
    scenes: [
      {
        id: "hill",
        kind: "shot",
        narration: "Every evening she climbed the same hill.",
        narration_from: "owner",
        visual: {
          asset_id: "a_hill",
          clip: true,
          camera: "tilt_up",
          motion: "She walks up the path, the grass moves in the wind.",
        },
        text: [{ content: "Every evening", style: "plain", position: "top" }],
      },
      {
        id: "lamp",
        kind: "shot",
        narration: "Then she lit the lamp.",
        narration_from: "studio",
        visual: { asset_id: "a_lamp", clip: false, camera: "push_in" },
      },
      {
        id: "sea",
        kind: "shot",
        narration: "",
        duration_s: 4,
        visual: { asset_id: "a_sea", clip: false, camera: "none" },
      },
    ],
    assets: [
      {
        id: "a_hill",
        kind: "image",
        origin: "generated",
        prompt: "A steep green hill at dusk, a narrow path, a lighthouse at the top, seen from below.",
        characters: ["keeper"],
        contains_third_party_ip: false,
        rights_status: "needs_review",
      },
      {
        id: "a_lamp",
        kind: "image",
        origin: "generated",
        prompt: "The lamp room of a lighthouse at night, one warm flame behind a great glass lens.",
        characters: ["keeper"],
        contains_third_party_ip: false,
        rights_status: "needs_review",
      },
      {
        id: "a_sea",
        kind: "image",
        origin: "generated",
        prompt: "A flat grey sea at dawn, seen from the top of the lighthouse, wide lens.",
        characters: [],
        contains_third_party_ip: false,
        rights_status: "needs_review",
      },
    ],
  };
}

async function openPlan(page: Page, change: (spec: Json) => void = () => undefined) {
  const fake: FakeEpisode = fakeEpisode({ title: "The Keeper's Hill" });
  const spec = shots();
  change(spec);
  fake.spec = spec;
  await mockEpisodes(page, () => [fake.episode, ...SAMPLE_EPISODES.slice(2)]);
  await mockEpisode(page, fake);
  await open(page, workspacePath());
  return fake;
}

const scene = (page: Page, number: number) =>
  page.getByRole("article").filter({ has: page.getByRole("heading", { name: `Scene ${number},` }) });
const changes = (page: Page) => page.getByTestId("changes-panel");
const look = (page: Page) => page.getByTestId("look-panel");
const saved = (fake: FakeEpisode) =>
  fake.requests.filter((request) => request.method === "PUT" && request.path === "/spec");
const lastSaved = (fake: FakeEpisode) => saved(fake).at(-1)?.body as ReturnType<typeof shots>;

test.describe("What the studio changed", () => {
  test("lists what was added, what was changed and what is not possible, each with its reason", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openPlan(page);

    await expect(changes(page).getByRole("heading", { level: 2 })).toHaveText("What the studio changed");
    await expect(changes(page).getByRole("heading", { level: 3 })).toHaveText([
      "Added 1",
      "Changed 1",
      "Not possible yet 1",
    ]);
    const items = changes(page).getByRole("listitem");
    await expect(items).toHaveCount(3);
    await expect(items.nth(0)).toContainText("Scene 2");
    await expect(items.nth(0)).toContainText("Low warm light from the left.");
    await expect(items.nth(0)).toContainText("The prompt gave no lighting for this scene.");
    await expect(items.nth(1)).toContainText("Scene 1");
    await expect(items.nth(2)).toContainText("Whole video");
    await expect(items.nth(2)).toContainText("A piano under the last scene.");
  });

  test("says so in words when nothing was changed", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openPlan(page, (spec) => {
      spec.changes = [];
    });

    await expect(changes(page)).toContainText(
      "Nothing was changed. The plan is your prompt as you wrote it.",
    );
    await expect(changes(page).getByRole("listitem")).toHaveCount(0);
  });

  test("a plan of shots has no brief, and a plan of the first design has no change list", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openPlan(page);
    await expect(page.getByRole("region", { name: "Brief" })).toHaveCount(0);

    const old = fakeEpisode();
    await mockEpisode(page, old);
    await page.reload();
    await expect(scene(page, 1)).toBeVisible();
    await expect(changes(page)).toHaveCount(0);
    await expect(look(page)).toHaveCount(0);
  });
});

test.describe("Look and characters", () => {
  test("shows the style and each character, described once", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openPlan(page);

    await expect(look(page)).toContainText("Described once, used in every picture that shows them.");
    await expect(look(page)).toContainText("Soft watercolour, muted blues, grain of rough paper.");
    await expect(look(page)).toContainText("The keeper");
    await expect(look(page)).toContainText(KEEPER);
  });

  test("a character's description is edited once and saved for the whole plan", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openPlan(page);

    await look(page).getByRole("button", { name: "Edit look and characters" }).click();
    await expect(look(page).getByRole("textbox", { name: "Description of character 1" })).toHaveValue(KEEPER);
    await look(page)
      .getByRole("textbox", { name: "Description of character 1" })
      .fill("A woman of about sixty in a red coat.");
    await look(page).getByRole("textbox", { name: "Style" }).fill("Ink and wash, black on cream.");
    await look(page).getByRole("button", { name: "Save" }).click();

    await expect(look(page)).toContainText("A woman of about sixty in a red coat.");
    await expect(page.getByText("Version 2")).toBeVisible();
    expect(saved(fake)).toHaveLength(1);
    expect(lastSaved(fake).characters).toEqual([
      { id: "keeper", name: "The keeper", description: "A woman of about sixty in a red coat." },
    ]);
    expect(lastSaved(fake).style).toBe("Ink and wash, black on cream.");
    // The pictures keep pointing at the character. Nothing else in the plan moved.
    expect(lastSaved(fake).assets).toEqual(shots().assets);
    expect(lastSaved(fake).scenes).toEqual(shots().scenes);
  });

  test("Cancel leaves the look as it was and sends nothing", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openPlan(page);

    await look(page).getByRole("button", { name: "Edit look and characters" }).click();
    await look(page).getByRole("textbox", { name: "Style" }).fill("Something else.");
    await look(page).getByRole("button", { name: "Cancel" }).click();

    await expect(look(page)).toContainText("Soft watercolour, muted blues, grain of rough paper.");
    expect(saved(fake)).toHaveLength(0);
  });
});

test.describe("One card per shot", () => {
  test("shows the line and whose it is, the text, the picture, who is in it, the camera and the motion", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openPlan(page);

    const first = scene(page, 1);
    await expect(first).toContainText("Every evening she climbed the same hill.");
    await expect(first).toContainText("Your line");
    await expect(first).toContainText("top: Every evening");
    await expect(first).toContainText("A steep green hill at dusk");
    await expect(first).toContainText("The keeper");
    await expect(first).toContainText("Tilt up");
    await expect(first).toContainText("She walks up the path, the grass moves in the wind.");
    await expect(first).toContainText(
      "To be a moving clip, made on your graphics card after the pictures.",
    );
    await expect(scene(page, 2)).toContainText("Written by the studio");
    await expect(scene(page, 2)).not.toContainText("To be a moving clip");
    await expect(scene(page, 3)).toContainText("No spoken line.");
    await expect(scene(page, 3)).toContainText("Still");
  });

  test("every field of a shot is edited in place and saved as a new version", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openPlan(page);
    const second = scene(page, 2);

    await second.getByRole("button", { name: "Edit scene 2" }).click();
    await second.getByRole("textbox", { name: "Spoken line" }).fill("Then she lit the great lamp.");
    await second.getByRole("button", { name: "Add a line of on-screen text" }).click();
    await second.getByRole("textbox", { name: "On-screen line 1" }).fill("Every night");
    await second.getByRole("combobox", { name: "Position of line 1" }).selectOption("middle");
    await second.getByRole("textbox", { name: "Seconds" }).fill("6");
    await second.getByRole("combobox", { name: "Camera" }).selectOption("pan_left");
    await second
      .getByRole("textbox", { name: "Picture" })
      .fill("The lamp room at night, the keeper's hands on the brass crank, one warm flame.");
    await second.getByRole("checkbox", { name: "The keeper" }).uncheck();
    await second.getByRole("textbox", { name: "Motion" }).fill("The flame grows slowly.");
    await second.getByRole("checkbox", { name: "Make it a moving clip" }).check();
    await second.getByRole("button", { name: "Save" }).click();

    await expect(second.getByRole("textbox")).toHaveCount(0);
    await expect(second).toContainText("Then she lit the great lamp.");
    await expect(second).toContainText("Your line");
    await expect(page.getByText("Version 2")).toBeVisible();
    expect(saved(fake)).toHaveLength(1);
    expect(lastSaved(fake).scenes[1]).toEqual({
      id: "lamp",
      kind: "shot",
      narration: "Then she lit the great lamp.",
      // A line the owner typed is the owner's line.
      narration_from: "owner",
      visual: {
        asset_id: "a_lamp",
        clip: true,
        camera: "pan_left",
        motion: "The flame grows slowly.",
      },
      text: [{ content: "Every night", style: "plain", position: "middle" }],
      duration_s: 6,
    });
    expect((lastSaved(fake).assets as Json[])[1]).toMatchObject({
      id: "a_lamp",
      prompt: "The lamp room at night, the keeper's hands on the brass crank, one warm flame.",
      characters: [],
    });
    expect(lastSaved(fake).scenes[0]).toEqual(shots().scenes[0]);
    expect((lastSaved(fake).assets as Json[])[0]).toEqual((shots().assets as Json[])[0]);
  });

  test("a shot whose line is emptied becomes a silent shot of three seconds", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openPlan(page);
    const second = scene(page, 2);

    await second.getByRole("button", { name: "Edit scene 2" }).click();
    await second.getByRole("textbox", { name: "Spoken line" }).fill("  ");
    await second.getByRole("button", { name: "Save" }).click();

    await expect(second).toContainText("No spoken line.");
    const stored = lastSaved(fake).scenes[1];
    expect(stored).toMatchObject({ narration: "", duration_s: 3 });
    expect(stored).not.toHaveProperty("narration_from");
  });

  test("emptied on-screen text and an emptied length are left out, not stored empty", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openPlan(page, (spec) => {
      ((spec.scenes as Scene[])[0] as Json).duration_s = 9;
    });
    const first = scene(page, 1);

    await first.getByRole("button", { name: "Edit scene 1" }).click();
    await expect(first.getByRole("textbox", { name: "Seconds" })).toHaveValue("9");
    await first.getByRole("textbox", { name: "On-screen line 1" }).fill("");
    await first.getByRole("textbox", { name: "Seconds" }).fill("");
    await first.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Version 2")).toBeVisible();
    const stored = lastSaved(fake).scenes[0];
    expect(stored).not.toHaveProperty("text");
    expect(stored).not.toHaveProperty("duration_s");
    // The line was not touched, so it is still marked as it was.
    expect(stored).toMatchObject({ narration_from: "owner" });
  });

  test("Cancel leaves the shot as it was and sends nothing", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openPlan(page);

    await scene(page, 1).getByRole("button", { name: "Edit scene 1" }).click();
    await scene(page, 1).getByRole("textbox", { name: "Picture" }).fill("Something else.");
    await scene(page, 1).getByRole("button", { name: "Cancel" }).click();

    await expect(scene(page, 1)).toContainText("A steep green hill at dusk");
    expect(saved(fake)).toHaveLength(0);
  });

  test("a plan that is refused says what is wrong and keeps what was typed", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openPlan(page);
    fake.refuseSpec = {
      status: 422,
      body: {
        error: {
          code: "invalid_spec",
          message: "The plan refers to something it does not have.",
          details: { problems: ["/assets/0/characters/0: the picture a_hill shows the character 'keeper'."] },
        },
      },
    };

    await scene(page, 1).getByRole("button", { name: "Edit scene 1" }).click();
    await scene(page, 1).getByRole("textbox", { name: "Picture" }).fill("A hill.");
    await scene(page, 1).getByRole("button", { name: "Save" }).click();

    await expect(scene(page, 1).getByRole("alert")).toContainText(
      "The plan refers to something it does not have.",
    );
    await expect(scene(page, 1).getByRole("textbox", { name: "Picture" })).toHaveValue("A hill.");
  });
});

test.describe("A plan of shots at every size", () => {
  for (const width of [360, 768, 1280, 1920]) {
    test(`UX-01 it fits at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await openPlan(page);
      await expect(scene(page, 1)).toBeVisible();

      expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
    });
  }

  test("on a phone a card shows the line, and Details opens the rest", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await openPlan(page);
    const first = scene(page, 1);

    await expect(first).toContainText("Every evening she climbed the same hill.");
    await expect(first.getByText("A steep green hill at dusk")).toBeHidden();
    await first.getByRole("button", { name: "Details of scene 1" }).click();
    await expect(first.getByText("A steep green hill at dusk")).toBeVisible();
  });

  for (const size of ["phone", "tablet", "desktop"] as const) {
    test(`UX-05 axe finds no violations on ${size}, also while editing`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await openPlan(page);
      await expect(scene(page, 1)).toBeVisible();
      expect((await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()).violations).toEqual([]);

      await look(page).getByRole("button", { name: "Edit look and characters" }).click();
      await scene(page, 1).getByRole("button", { name: "Edit scene 1" }).click();
      await expect(scene(page, 1).getByRole("textbox", { name: "Picture" })).toBeVisible();
      expect((await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()).violations).toEqual([]);
    });
  }

  for (const size of ["phone", "tablet"] as const) {
    test(`UX-04 touch targets of a shot being edited are at least 44 by 44 px on ${size}`, async ({
      page,
    }) => {
      await page.setViewportSize(SIZES[size]);
      await openPlan(page);
      await scene(page, 1).getByRole("button", { name: "Edit scene 1" }).click();

      const controls = scene(page, 1).locator("button, select, textarea, input[type=text], label:has(input)");
      for (const control of await controls.all()) {
        const box = await control.boundingBox();
        expect(box?.height ?? 0, await control.evaluate((element) => element.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(44);
      }
    });
  }
});

test.describe("A plan of shots matches its approved screenshots", () => {
  test.skip(process.platform !== "linux", "screenshots are compared in the Linux test image only");

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`Plan tab of shots at ${viewport.width} px (${size})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openPlan(page);
      await expect(scene(page, 1)).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      await expect(page).toHaveScreenshot(`director-plan-${viewport.width}.png`, { fullPage: true });
    });
  }
});
