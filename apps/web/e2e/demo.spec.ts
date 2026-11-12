// FR-16: the end to end demo. In demo mode, with no keys, no GPU and no accounts, an idea
// typed into the interface becomes a rendered video: the plan is written, one line is
// edited, the plan and the pictures are approved, and the worker speaks, encodes and joins.
// Everything here goes through the real API and the real worker.
//
// The video it makes is saved to e2e/.demo, where CI picks it up as the demo artifact.
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { SIZES, open } from "./support";

const MINUTE = 60_000;

test.describe("FR-16 from an idea to a rendered video, through the real API and worker", () => {
  test("idea, plan, an edited line, Approve plan, Approve pictures, the render, the video", async ({
    page,
  }, testInfo) => {
    // The render encodes seven full-size scenes. On a small CI machine that takes minutes.
    test.setTimeout(25 * MINUTE);
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    await page.getByTestId("side-nav").getByRole("link", { name: "New episode" }).click();
    const dialog = page.getByRole("dialog", { name: "New episode" });
    await dialog.getByRole("textbox", { name: "Idea" }).fill("A keeper who climbs the hill every morning");
    await dialog.getByRole("button", { name: "Start" }).click();

    await expect(page).toHaveURL(/\/episodes\/[0-9a-f-]{36}$/);
    const episodeId = page.url().split("/episodes/")[1] ?? "";
    const status = page.getByTestId("episode-status");
    const gate = page.getByTestId("gate-bar");
    await expect(status).toHaveText("Plan needs you", { timeout: 3 * MINUTE });

    // Edit a line that is shown, not spoken: without the voice model, the bundled voice
    // only knows the words of the sample narration.
    const second = page
      .getByRole("article")
      .filter({ has: page.getByRole("heading", { name: "Scene 2," }) });
    await second.getByRole("button", { name: "Edit scene 2" }).click();
    await second.getByRole("textbox", { name: "Title" }).fill("THE SAME HILL");
    await second.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Version 2")).toBeVisible();
    await expect(second).toContainText("THE SAME HILL");

    await gate.getByRole("button", { name: "Approve plan" }).click();
    await expect(status).toHaveText("Pictures need you", { timeout: 2 * MINUTE });
    await gate.getByRole("button", { name: "Approve pictures" }).click();
    await expect(gate).toBeHidden();

    // Voice, seven scene files and the join run by themselves.
    await expect(status).toHaveText("Video rendered", { timeout: 18 * MINUTE });
    await expect(page.getByTestId("step-failed")).toBeHidden();

    await page.getByRole("tab", { name: "Render" }).click();
    const panel = page.getByRole("tabpanel");
    const video = panel.locator("video");
    await expect(video).toBeVisible();
    await expect(panel).toContainText("version 2 of the plan");
    const videoUrl = (await video.getAttribute("src")) ?? "";
    const sheetUrl =
      (await panel.getByRole("link", { name: "Open the contact sheet" }).getAttribute("href")) ?? "";
    expect(videoUrl).toMatch(/^\/api\/v1\/files\/.+\/video\.mp4$/);

    // The player can seek: the file is served in ranges, through the web address.
    const part = await page.request.get(videoUrl, { headers: { Range: "bytes=0-1023" } });
    expect(part.status()).toBe(206);
    expect(part.headers()["content-type"]).toBe("video/mp4");
    expect((await part.body()).length).toBe(1024);

    const whole = await page.request.get(videoUrl);
    const sheet = await page.request.get(sheetUrl);
    expect(whole.status()).toBe(200);
    expect(sheet.status()).toBe(200);
    expect(sheet.headers()["content-type"]).toBe("image/jpeg");
    const file = await whole.body();
    // An MP4 with its index at the front starts with the "ftyp" box (RN-01, faststart).
    expect(file.subarray(4, 8).toString("latin1")).toBe("ftyp");
    expect(file.length).toBeGreaterThan(1_000_000);

    // What was rendered is the edited plan, and the episode rests: nothing failed after it.
    const renders = await (await page.request.get(`/api/v1/episodes/${episodeId}/renders`)).json();
    expect(renders.total).toBe(1);
    expect(renders.renders[0].kind).toBe("draft");
    expect(renders.renders[0].duration_s).toBeGreaterThan(40);
    expect(renders.renders[0].duration_s).toBeLessThan(48);
    const detail = await (await page.request.get(`/api/v1/episodes/${episodeId}`)).json();
    expect(detail.resting).toBe(true);
    expect(detail.jobs.filter((job: { status: string }) => job.status !== "succeeded")).toEqual([]);
    const spec = await (await page.request.get(`/api/v1/episodes/${episodeId}/spec`)).json();
    expect(spec.spec.scenes[1].title).toBe("THE SAME HILL");

    const folder = path.join(testInfo.project.testDir, ".demo");
    mkdirSync(folder, { recursive: true });
    writeFileSync(path.join(folder, "video.mp4"), file);
    writeFileSync(path.join(folder, "video_contact_sheet.jpg"), await sheet.body());
  });
});
