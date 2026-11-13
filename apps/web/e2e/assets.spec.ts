// End-to-end tests for the Assets tab (design doc sections 11.2 and 11.5, FR-05, FR-06)
// and the download link of the Render tab. The episode routes are answered by a stand-in.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { SAMPLE_EPISODES, SIZES, WCAG_TAGS, mockEpisodes, open, sidewaysOverflow } from "./support";
import {
  type FakeEpisode,
  VIDEO_URL,
  fakeEpisode,
  job,
  mockEpisode,
  picture,
  render,
  workspacePath,
} from "./workspace-support";

// A one-pixel PNG, so a picture on the page has something to show.
const PIXEL = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function openWorkspace(page: Page, fake: FakeEpisode) {
  await mockEpisodes(page, () => [fake.episode, ...SAMPLE_EPISODES.slice(2)]);
  await mockEpisode(page, fake);
  await page.route("**/api/v1/files/**", (route) =>
    route.request().url().endsWith(".png")
      ? route.fulfill({ contentType: "image/png", body: PIXEL })
      : route.fulfill({ status: 404, body: "" }),
  );
  await open(page, workspacePath());
  return fake;
}

const panel = (page: Page) => page.getByRole("tabpanel");
const gate = (page: Page) => page.getByTestId("gate-bar");
const card = (page: Page, name: string) =>
  panel(page).getByRole("listitem").filter({ has: page.getByRole("heading", { name }) });
const sent = (fake: FakeEpisode, method: string, path: string) =>
  fake.requests.filter((request) => request.method === method && request.path === path);

async function assetsTab(page: Page) {
  await page.getByRole("tab", { name: "Assets" }).click();
  return panel(page);
}

function atPictures(): FakeEpisode {
  const fake = fakeEpisode({ state: "asset_gen", awaiting_approval: true, gate: "assets" });
  fake.assets = [
    picture("a_garden_dawn", { used_in: ["s02_garden"] }),
    picture("a_watering_can", { used_in: ["s02_garden", "s03_outro"] }),
    picture("a_hill_dawn", {
      origin: "library",
      prompt: null,
      model: null,
      licence: "MIT",
      rights_status: "cleared",
      image_url: "/api/v1/files/library/a_hill_dawn/v1.png",
      used_in: ["s03_outro"],
    }),
  ];
  return fake;
}

test.describe("Assets tab", () => {
  test("FR-05 shows every picture with where it comes from, its prompt and its scenes", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, atPictures());

    const tab = await assetsTab(page);

    await expect(tab).toContainText("3 pictures: 2 made for this episode, 1 from the library.");
    await expect(tab.getByRole("listitem")).toHaveCount(3);
    const dawn = card(page, "Garden dawn");
    await expect(dawn.getByRole("img", { name: "Garden dawn" })).toHaveAttribute(
      "src",
      "/api/v1/files/jobs/gen.image/ab/abcdef/a_garden_dawn.png",
    );
    await expect(dawn).toContainText("Generated");
    await expect(dawn).toContainText("Shown in scene 2");
    await expect(dawn).toContainText("A picture of garden dawn, flat paper-cut shapes.");
    await expect(dawn).toContainText("Rights need your review");
    await expect(card(page, "Watering can")).toContainText("Shown in scenes 2 and 3");
    const library = card(page, "Hill dawn");
    await expect(library).toContainText("From the library");
    await expect(library).toContainText("Rights cleared");
    await expect(library.getByRole("button", { name: /Make again/ })).toHaveCount(0);
  });

  test("the pictures gate points at the Assets tab", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, atPictures());

    await expect(gate(page)).toContainText("The pictures are ready.");
    await expect(gate(page)).toContainText("Look at them in the Assets tab");
  });

  test("before the plan is approved it says when the pictures appear", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openWorkspace(page, fakeEpisode());

    const tab = await assetsTab(page);

    await expect(tab).toContainText("The pictures appear here after the plan is approved.");
  });

  test("UX-06 a picture that is not made yet, and one that is being made, say so", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = fakeEpisode({ state: "asset_gen", awaiting_approval: false, gate: null });
    fake.jobs = [job("gen.image", "running"), job("gen.image", "queued")];
    fake.assets = [
      picture("a_garden_dawn", { resolved: false, image_url: null, generating: true, versions: 0 }),
      picture("a_my_photo", {
        origin: "uploaded",
        prompt: null,
        filename: "my_photo.png",
        resolved: false,
        image_url: null,
        versions: 0,
      }),
    ];
    await openWorkspace(page, fake);

    const tab = await assetsTab(page);

    await expect(tab).toContainText("2 are not there yet");
    await expect(card(page, "Garden dawn")).toContainText("Being made");
    await expect(card(page, "Garden dawn").getByRole("img")).toHaveCount(0);
    await expect(card(page, "My photo")).toContainText("Waits for your upload: my_photo.png");
  });

  test("FR-06 Make again asks for a note, queues one picture and shows that it is being made", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, atPictures());
    await assetsTab(page);
    const dawn = card(page, "Garden dawn");

    await dawn.getByRole("button", { name: "Make again" }).click();
    await expect(dawn).toContainText("Uses one picture of your plan");
    await dawn.getByRole("textbox", { name: "What should be different? (optional)" }).fill("Make it dawn.");
    await dawn.getByRole("button", { name: "Make a new one" }).click();

    await expect(dawn).toContainText("Being made");
    await expect(dawn.getByRole("button", { name: "Make again" })).toHaveCount(0);
    expect(sent(fake, "POST", "/assets/a_garden_dawn/regenerate")[0]?.body).toEqual({
      note: "Make it dawn.",
    });
  });

  test("Make again without a note sends none, and Cancel sends nothing", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, atPictures());
    await assetsTab(page);
    const can = card(page, "Watering can");

    await can.getByRole("button", { name: "Make again" }).click();
    await can.getByRole("button", { name: "Cancel" }).click();
    expect(sent(fake, "POST", "/assets/a_watering_can/regenerate")).toHaveLength(0);

    await can.getByRole("button", { name: "Make again" }).click();
    await can.getByRole("button", { name: "Make a new one" }).click();
    await expect(can).toContainText("Being made");
    expect(sent(fake, "POST", "/assets/a_watering_can/regenerate")[0]?.body).toEqual({});
  });

  test("UX-06 a request the API refuses shows the reason", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = atPictures();
    await openWorkspace(page, fake);
    await page.route("**/assets/a_garden_dawn/regenerate", (route) =>
      route.fulfill({
        status: 409,
        json: { error: { code: "already_generating", message: "This picture is already being made." } },
      }),
    );
    await assetsTab(page);
    const dawn = card(page, "Garden dawn");

    await dawn.getByRole("button", { name: "Make again" }).click();
    await dawn.getByRole("button", { name: "Make a new one" }).click();

    await expect(dawn.getByRole("alert")).toContainText("This picture is already being made.");
  });
});

test.describe("Download", () => {
  test("the Render tab offers the finished video as a file", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = fakeEpisode({ state: "render", awaiting_approval: false, gate: null, resting: true });
    fake.jobs = [job("render.join", "succeeded")];
    fake.renders = [render()];
    await openWorkspace(page, fake);

    await page.getByRole("tab", { name: "Render" }).click();

    const link = panel(page).getByRole("link", { name: "Download the video" });
    await expect(link).toHaveAttribute("href", VIDEO_URL);
    await expect(link).toHaveAttribute("download", "the-gardener-nobody-watched.mp4");
  });
});

test.describe("Assets tab at every size", () => {
  for (const width of [360, 768, 1280, 1920]) {
    test(`UX-01 it fits at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await openWorkspace(page, atPictures());
      await expect((await assetsTab(page)).getByRole("listitem")).toHaveCount(3);

      expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
    });
  }

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`UX-05 axe finds no violations on ${size}, also with the form open`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openWorkspace(page, atPictures());
      await assetsTab(page);
      await card(page, "Garden dawn").getByRole("button", { name: "Make again" }).click();
      await expect(card(page, "Garden dawn").getByRole("textbox")).toBeVisible();

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();

      expect(results.violations.map((violation) => violation.id)).toEqual([]);
    });
  }

  for (const size of ["phone", "tablet"] as const) {
    test(`UX-04 touch targets are at least 44 by 44 px on ${size}`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await openWorkspace(page, atPictures());
      const tab = await assetsTab(page);
      await card(page, "Garden dawn").getByRole("button", { name: "Make again" }).click();

      const targets = tab.locator("a:visible, button:visible, textarea:visible");
      expect(await targets.count()).toBeGreaterThan(3);
      for (const target of await targets.all()) {
        const box = await target.boundingBox();
        expect(box?.width).toBeGreaterThanOrEqual(44);
        expect(box?.height).toBeGreaterThanOrEqual(44);
      }
    });
  }
});

test.describe("Your own pictures (FR-07)", () => {
  const file = (name: string, mimeType = "image/png") => ({ name, mimeType, buffer: PIXEL });
  const own = (page: Page) => page.getByTestId("match-files");
  const uploads = (fake: FakeEpisode) => fake.requests.filter((request) => request.path.endsWith("/upload"));

  test("Upload your own stores the file as the picture and says where it comes from", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, atPictures());
    await assetsTab(page);
    const garden = card(page, "Garden dawn");
    await expect(garden).toContainText("Generated");

    await garden
      .getByLabel("Upload your own picture for Garden dawn")
      .setInputFiles(file("anything.jpg", "image/jpeg"));

    await expect(garden).toContainText("Your upload");
    expect(sent(fake, "POST", "/assets/a_garden_dawn/upload")[0]?.body).toEqual({ sent_as: "image/jpeg" });
  });

  test("a library picture has no upload, and a picture that waits for one asks for it", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = atPictures();
    fake.assets.push(
      picture("a_my_photo", {
        origin: "uploaded",
        prompt: null,
        filename: "my_photo.png",
        resolved: false,
        image_url: null,
        model: null,
        versions: 0,
      }),
    );
    await openWorkspace(page, fake);
    await assetsTab(page);

    await expect(card(page, "Hill dawn").locator("input[type=file]")).toHaveCount(0);
    await expect(card(page, "My photo")).toContainText("Upload this picture");
    await expect(card(page, "My photo").getByRole("button", { name: "Make again" })).toHaveCount(0);
  });

  test("UX-06 a file the API refuses shows the reason and the picture stays as it was", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = atPictures();
    fake.refuseUpload = {
      status: 422,
      body: {
        error: {
          code: "too_small",
          message: "The picture is 120 by 200 pixels. Its short side must be at least 256 pixels.",
          details: {},
        },
      },
    };
    await openWorkspace(page, fake);
    await assetsTab(page);
    const garden = card(page, "Garden dawn");

    await garden.locator("input[type=file]").setInputFiles(file("small.png"));

    await expect(garden.getByRole("alert")).toContainText("120 by 200 pixels");
    await expect(garden).toContainText("Generated");
  });

  test("a file that is not a picture is refused before anything is sent", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, atPictures());
    await assetsTab(page);
    const garden = card(page, "Garden dawn");

    await garden.locator("input[type=file]").setInputFiles(file("notes.txt", "text/plain"));

    await expect(garden.getByRole("alert")).toHaveText("Choose a PNG, JPEG or WebP picture.");
    expect(uploads(fake)).toHaveLength(0);
  });

  test("FR-07 several files are matched by name and shown before anything is stored", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, atPictures());
    await assetsTab(page);

    await own(page)
      .getByLabel("Choose your own pictures")
      .setInputFiles([file("Garden Dawn.png"), file("holiday.png"), file("watering-can.png")]);

    const matches = own(page).getByRole("list", { name: "Matches" }).getByRole("listitem");
    await expect(matches).toHaveText([
      /Garden Dawn\.png\s*goes to Garden dawn/,
      /holiday\.png\s*is left out\. No picture of this episode has this name\./,
      /watering-can\.png\s*goes to Watering can/,
    ]);
    expect(sent(fake, "POST", "/assets/match")[0]?.body).toEqual({
      filenames: ["Garden Dawn.png", "holiday.png", "watering-can.png"],
    });
    expect(uploads(fake)).toHaveLength(0);

    await own(page).getByRole("button", { name: "Use 2 pictures" }).click();

    await expect(own(page).getByRole("status")).toHaveText("2 pictures stored.");
    await expect(card(page, "Garden dawn")).toContainText("Your upload");
    await expect(card(page, "Watering can")).toContainText("Your upload");
    expect(uploads(fake).map((request) => request.path)).toEqual([
      "/assets/a_garden_dawn/upload",
      "/assets/a_watering_can/upload",
    ]);
  });

  test("FR-07 Cancel stores nothing, and nothing can be stored when no file matches", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const fake = await openWorkspace(page, atPictures());
    await assetsTab(page);
    const choose = own(page).getByLabel("Choose your own pictures");

    await choose.setInputFiles([file("holiday.png")]);
    await expect(own(page).getByRole("button", { name: "Use 0 pictures" })).toBeDisabled();
    await own(page).getByRole("button", { name: "Cancel" }).click();

    await expect(own(page).getByRole("list", { name: "Matches" })).toBeHidden();
    await expect(choose).toBeAttached();
    expect(uploads(fake)).toHaveLength(0);
  });

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`UX-05 the matches have no accessibility violations and fit on ${size}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openWorkspace(page, atPictures());
      await assetsTab(page);
      await own(page)
        .getByLabel("Choose your own pictures")
        .setInputFiles([
          file("garden_dawn.png"),
          file("a-very-long-file-name-that-matches-no-picture-of-this-episode.png"),
        ]);
      await expect(own(page).getByRole("list", { name: "Matches" })).toBeVisible();

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();

      expect(results.violations).toEqual([]);
      expect(await sidewaysOverflow(page)).toBe(0);
    });
  }
});
