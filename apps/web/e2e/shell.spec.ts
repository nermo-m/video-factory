// End-to-end tests for the app shell (design doc section 11.5), run against the Compose
// stack in demo mode. Requirement IDs are in the test names.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

const SIZES = {
  phone: { width: 390, height: 844 },
  tablet: { width: 820, height: 1180 },
  desktop: { width: 1440, height: 900 },
} as const;

const ROUTES = [
  { path: "/", heading: "Board" },
  { path: "/videos", heading: "Videos" },
  { path: "/library", heading: "Library" },
  { path: "/jobs", heading: "Jobs" },
  { path: "/settings", heading: "Settings" },
  { path: "/episodes/new", heading: "New episode" },
];

/** Open a page and wait until the status strip has heard from the API. */
async function open(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.getByTestId("demo-badge")).toBeVisible();
}

const sideNav = (page: Page) => page.getByTestId("side-nav");
const bottomNav = (page: Page) => page.getByTestId("bottom-nav");

test.describe("UX-02 navigation follows the screen size", () => {
  test("desktop shows a 232 px sidebar with labels and the New episode button on top", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    await expect(sideNav(page)).toBeVisible();
    await expect(bottomNav(page)).toBeHidden();
    expect((await sideNav(page).boundingBox())?.width).toBe(232);
    const links = sideNav(page).getByRole("link");
    await expect(links).toHaveText(["New episode", "Board", "Videos", "Library", "Jobs", "Settings"]);
    await expect(sideNav(page).getByText("Videos")).toBeVisible();
    await expect(sideNav(page).getByRole("link", { name: "Board" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("the desktop sidebar collapses to a 64 px rail and remembers it", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    await page.getByRole("button", { name: "Collapse the sidebar" }).click();
    await expect.poll(async () => (await sideNav(page).boundingBox())?.width).toBe(64);
    await expect(sideNav(page).getByRole("link", { name: "Videos" })).toBeVisible();

    await page.reload();
    await expect(page.getByRole("button", { name: "Expand the sidebar" })).toBeVisible();
    expect((await sideNav(page).boundingBox())?.width).toBe(64);

    await page.getByRole("button", { name: "Expand the sidebar" }).click();
    await expect.poll(async () => (await sideNav(page).boundingBox())?.width).toBe(232);
  });

  test("tablet shows a 64 px icon rail with tooltips", async ({ page }) => {
    await page.setViewportSize(SIZES.tablet);
    await open(page);

    await expect(sideNav(page)).toBeVisible();
    await expect(bottomNav(page)).toBeHidden();
    expect((await sideNav(page).boundingBox())?.width).toBe(64);
    await expect(page.getByRole("button", { name: /the sidebar/ })).toBeHidden();

    const videos = sideNav(page).getByRole("link", { name: "Videos" });
    await videos.hover();
    await expect(page.getByRole("tooltip", { name: "Videos" })).toBeVisible();
  });

  test("phone shows a bottom bar with Board, Videos, Jobs and More", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await open(page);

    await expect(sideNav(page)).toBeHidden();
    await expect(bottomNav(page)).toBeVisible();
    await expect(bottomNav(page).getByRole("link")).toHaveText(["Board", "Videos", "Jobs"]);
    await expect(bottomNav(page).getByRole("button", { name: "More" })).toBeVisible();
  });

  test("phone keeps Library and Settings inside More, and Escape closes it", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await open(page);

    await page.getByRole("button", { name: "More" }).click();
    const sheet = page.getByRole("dialog", { name: "More" });
    await expect(sheet.getByRole("link")).toHaveText(["Library", "Settings"]);

    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();

    await page.getByRole("button", { name: "More" }).click();
    await sheet.getByRole("link", { name: "Settings" }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    await expect(sheet).toBeHidden();
  });

  test("the floating New episode button shows on Board and Videos only", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    const floating = page.getByTestId("floating-new-episode");

    await open(page, "/");
    await expect(floating).toBeVisible();
    await open(page, "/videos");
    await expect(floating).toBeVisible();
    await open(page, "/jobs");
    await expect(floating).toBeHidden();
  });

  for (const size of ["tablet", "desktop"] as const) {
    test(`every navigation item opens its screen on ${size}`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await open(page);

      for (const route of ROUTES.filter((item) => item.path !== "/episodes/new")) {
        await sideNav(page).getByRole("link", { name: route.heading, exact: true }).click();
        await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
        await expect(
          sideNav(page).getByRole("link", { name: route.heading, exact: true }),
        ).toHaveAttribute("aria-current", "page");
      }
    });
  }
});

test.describe("status strip", () => {
  test("shows demo mode, GPU status, jobs and waiting items", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    await expect(page.getByTestId("demo-badge")).toHaveText("Demo mode");
    await expect(page.getByTestId("gpu-status")).toHaveText("GPU not needed");
    await expect(page.getByTestId("jobs-status")).toHaveAccessibleName("No jobs running");
    await expect(page.getByTestId("jobs-status").getByText("No jobs running")).toBeVisible();
    await expect(page.getByTestId("waiting-status")).toHaveAccessibleName("Nothing waiting");
    await expect(page.getByRole("status")).toContainText("Demo mode is on.");

    await page.getByTestId("jobs-status").click();
    await expect(page).toHaveURL(/\/jobs$/);
  });

  test("on a phone it keeps the same facts for screen readers", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await open(page);

    await expect(page.getByTestId("jobs-status")).toHaveAccessibleName(/No jobs running/);
    await expect(page.getByTestId("gpu-status")).toContainText("GPU not needed");
  });

  test("says so when the API does not answer", async ({ page }) => {
    await page.route("**/api/v1/health", (route) => route.abort());
    await page.setViewportSize(SIZES.desktop);
    await page.goto("/");

    await expect(page.getByTestId("gpu-status")).toHaveText("API offline");
    await expect(page.getByRole("status")).toContainText("The API is not answering.");
  });
});

test.describe("UX-01 no horizontal page scroll", () => {
  for (const width of [360, 768, 1280, 1920]) {
    test(`every screen fits at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      for (const route of ROUTES) {
        await open(page, route.path);
        await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow, `${route.path} scrolls sideways at ${width} px`).toBeLessThanOrEqual(0);
      }
    });
  }
});

test.describe("UX-04 keyboard and touch", () => {
  test("Tab reaches the skip link first, then every control, each with a visible focus ring", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();

    const reached: string[] = [];
    // Ten controls follow the skip link. One more Tab would leave the page.
    for (let step = 0; step < 10; step += 1) {
      await page.keyboard.press("Tab");
      const focused = page.locator(":focus");
      reached.push((await focused.getAttribute("aria-label")) ?? (await focused.innerText()).trim());
      const outline = await focused.evaluate((element) => {
        const style = getComputedStyle(element);
        return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) };
      });
      expect(outline.style, `no focus ring on "${reached.at(-1)}"`).not.toBe("none");
      expect(outline.width).toBeGreaterThanOrEqual(2);
    }

    for (const name of [
      "Video Factory",
      "No jobs running",
      "Nothing waiting",
      "New episode",
      "Board",
      "Videos",
      "Library",
      "Jobs",
      "Settings",
      "Collapse the sidebar",
    ]) {
      expect(reached, `"${name}" was not reached with Tab`).toContain(name);
    }
  });

  test("the skip link moves focus to the content", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#content$/);
  });

  for (const size of ["phone", "tablet"] as const) {
    test(`touch targets are at least 44 by 44 px on ${size}`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await open(page);

      // The skip link is a keyboard-only control that stays off screen until focused.
      const targets = page.locator("a:visible:not(.sr-only), button:visible");
      const count = await targets.count();
      expect(count).toBeGreaterThan(4);
      for (let index = 0; index < count; index += 1) {
        const target = targets.nth(index);
        const box = await target.boundingBox();
        const name = (await target.innerText()).trim() || (await target.getAttribute("aria-label"));
        expect(box?.width, `"${name}" is too narrow`).toBeGreaterThanOrEqual(44);
        expect(box?.height, `"${name}" is too short`).toBeGreaterThanOrEqual(44);
      }
    });
  }
});

test.describe("UX-05 accessibility", () => {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`axe finds no WCAG 2.1 AA violations on any screen on ${size}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      for (const route of ROUTES) {
        await open(page, route.path);
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze();
        const summary = results.violations.map(
          (violation) => `${violation.id}: ${violation.nodes.map((node) => node.target).join(", ")}`,
        );
        expect(summary, `axe violations on ${route.path}`).toEqual([]);
      }
    });
  }

  test("axe finds no violations with the More sheet open", async ({ page }) => {
    await page.setViewportSize(SIZES.phone);
    await open(page);
    await page.getByRole("button", { name: "More" }).click();
    await expect(page.getByRole("dialog", { name: "More" })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
});

test.describe("UX-07 reduced motion", () => {
  test("transitions and animations are switched off when the system asks", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    const durations = await page.evaluate(() =>
      [...document.querySelectorAll("*")].map((element) => {
        const style = getComputedStyle(element);
        return Math.max(
          ...`${style.transitionDuration},${style.animationDuration}`
            .split(",")
            .map((value) => Number.parseFloat(value)),
        );
      }),
    );
    expect(Math.max(...durations)).toBeLessThanOrEqual(0.001);
  });

  test("without that setting the sidebar toggle does animate", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await open(page);

    const duration = await page
      .getByRole("button", { name: "Collapse the sidebar" })
      .locator("span")
      .first()
      .evaluate((element) => Number.parseFloat(getComputedStyle(element).transitionDuration));
    expect(duration).toBeGreaterThan(0.05);
  });
});

test.describe("screens match their approved screenshots", () => {
  // Baselines are made inside the pinned Linux image (make e2e-update), so fonts and
  // rendering never differ between machines. Elsewhere this group is skipped.
  test.skip(process.platform !== "linux", "screenshots are compared in the Linux test image only");

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`Board at ${viewport.width} px (${size})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await open(page);
      await expect(page.getByRole("heading", { name: "No episodes yet" })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      await expect(page).toHaveScreenshot(`board-${viewport.width}.png`, { fullPage: true });
    });
  }
});
