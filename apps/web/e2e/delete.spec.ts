// Deleting videos from the Board and from a video's own page (Director mode design,
// "Deleting videos"). The list is answered from a fixed list that the delete calls change,
// except in the last test, which goes through the real API.
import AxeBuilder from "@axe-core/playwright";
import { type Page, type Route, expect, test } from "@playwright/test";

import { type EpisodeRow, SIZES, WCAG_TAGS, episode, mockEpisodes, open } from "./support";

const card = (page: Page, title: string) =>
  page.getByRole("article").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
const dialog = (page: Page) => page.getByRole("alertdialog");

const TWO_CHAIRS = episode(2).id;
const SMALL_STEPS = episode(3).id;

function threeVideos(): EpisodeRow[] {
  return [
    episode(1, { title: "The Lighthouse Keeper", state: "direction", awaiting_approval: true, gate: "plan" }),
    episode(2, { title: "Two Chairs" }),
    episode(3, { title: "Small Steps", state: "asset_gen" }),
  ];
}

/** A Board whose delete calls remove from the list. `failing` ids answer with an error. */
async function boardWith(page: Page, failing: string[] = []) {
  let rows = threeVideos();
  const deleted: string[] = [];
  await mockEpisodes(page, () => rows);
  await page.route("**/api/v1/episodes/*", async (route: Route) => {
    if (route.request().method() !== "DELETE") {
      return route.fallback();
    }
    const id = route.request().url().split("/").pop() ?? "";
    if (failing.includes(id)) {
      return route.fulfill({ status: 500, json: { error: { code: "internal", message: "It broke." } } });
    }
    deleted.push(id);
    rows = rows.filter((row) => row.id !== id);
    await route.fulfill({ status: 204 });
  });
  await open(page);
  return deleted;
}

test.describe("Deleting one video from its card", () => {
  test("asks first, then removes the card and says so", async ({ page }) => {
    const deleted = await boardWith(page);

    await card(page, "Two Chairs").getByRole("button", { name: 'Delete "Two Chairs"' }).click();

    await expect(dialog(page)).toContainText('Delete "Two Chairs"?');
    await expect(dialog(page)).toContainText(
      "The plan, pictures, voice and rendered files are removed for good.",
    );
    await expect(dialog(page).getByRole("button", { name: "Cancel" })).toBeFocused();
    await dialog(page).getByRole("button", { name: "Delete", exact: true }).click();

    await expect(card(page, "Two Chairs")).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: "Deleted." })).toBeVisible();
    await expect(page.getByText("2 episodes")).toBeVisible();
    expect(deleted).toEqual([TWO_CHAIRS]);
  });

  test("Cancel and Escape keep the video", async ({ page }) => {
    const deleted = await boardWith(page);

    await card(page, "Two Chairs").getByRole("button", { name: 'Delete "Two Chairs"' }).click();
    await dialog(page).getByRole("button", { name: "Cancel" }).click();
    await expect(dialog(page)).toHaveCount(0);

    await card(page, "Two Chairs").getByRole("button", { name: 'Delete "Two Chairs"' }).click();
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);

    await expect(card(page, "Two Chairs")).toBeVisible();
    expect(deleted).toEqual([]);
  });

  test("a delete that fails keeps the card and says which video", async ({ page }) => {
    await boardWith(page, [TWO_CHAIRS]);

    await card(page, "Two Chairs").getByRole("button", { name: 'Delete "Two Chairs"' }).click();
    await dialog(page).getByRole("button", { name: "Delete", exact: true }).click();

    await expect(page.getByRole("alert").filter({ hasText: "Two Chairs could not be deleted. Try again." })).toBeVisible();
    await expect(card(page, "Two Chairs")).toBeVisible();
  });
});

test.describe("Deleting several videos", () => {
  test("Select turns the cards into choices and deletes the chosen ones", async ({ page }) => {
    const deleted = await boardWith(page);

    await page.getByRole("button", { name: "Select", exact: true }).click();
    await expect(page.getByRole("button", { name: "Delete 0 videos" })).toBeDisabled();
    await page.getByRole("checkbox", { name: "Two Chairs" }).check();
    await page.getByRole("checkbox", { name: "Small Steps" }).check();
    await page.getByRole("button", { name: "Delete 2 videos" }).click();

    await expect(dialog(page)).toContainText("Delete 2 videos?");
    await dialog(page).getByRole("button", { name: "Delete", exact: true }).click();

    await expect(page.getByRole("article")).toHaveCount(1);
    await expect(card(page, "The Lighthouse Keeper")).toBeVisible();
    expect(deleted.sort()).toEqual([TWO_CHAIRS, SMALL_STEPS].sort());
    // Selecting ends with the delete.
    await expect(page.getByRole("button", { name: "Select", exact: true })).toBeVisible();
  });

  test("Done leaves selecting without deleting, and a card opens its video again", async ({ page }) => {
    const deleted = await boardWith(page);

    await page.getByRole("button", { name: "Select", exact: true }).click();
    await page.getByRole("checkbox", { name: "Two Chairs" }).check();
    await page.getByRole("button", { name: "Done", exact: true }).click();

    await expect(page.getByRole("checkbox")).toHaveCount(0);
    await expect(card(page, "Two Chairs").getByRole("link")).toBeVisible();
    expect(deleted).toEqual([]);
  });

  for (const size of ["phone", "desktop"] as const) {
    test(`selecting has no accessibility problems on a ${size}`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await boardWith(page);
      await page.getByRole("button", { name: "Select", exact: true }).click();
      await page.getByRole("checkbox", { name: "Two Chairs" }).check();
      await page.getByRole("button", { name: "Delete 1 video", exact: true }).click();
      await expect(dialog(page)).toBeVisible();

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(results.violations).toEqual([]);
    });
  }
});

test.describe("Deleting through the real API", () => {
  test("a video deleted on its own page is gone from the Board for good", async ({ page, request }) => {
    const idea = `A video to delete ${Date.now()}`;
    const created = await request.post("/api/v1/episodes", { data: { idea, start: false } });
    expect(created.status()).toBe(201);
    const { id } = (await created.json()) as { id: string };

    await open(page, `/episodes/${id}`);
    await page.getByRole("button", { name: "Delete video" }).click();
    await expect(dialog(page)).toContainText("removed for good");
    await dialog(page).getByRole("button", { name: "Delete", exact: true }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("status").filter({ hasText: "Deleted." })).toBeVisible();
    expect((await request.get(`/api/v1/episodes/${id}`)).status()).toBe(404);
    await page.reload();
    await expect(page.locator(`[data-episode-id="${id}"]`)).toHaveCount(0);
  });
});
