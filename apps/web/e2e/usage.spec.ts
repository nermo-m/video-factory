// End-to-end tests for the Usage page, the model picker in Settings and the provider
// warning in the status strip (design doc section 11.5 "Model picker and usage", FR-33,
// FR-34). The provider and settings routes are answered from fixed data.
import AxeBuilder from "@axe-core/playwright";
import { type Page, type Route, expect, test } from "@playwright/test";

import { SIZES, WCAG_TAGS, mockEpisodes, open, sidewaysOverflow } from "./support";

type Json = Record<string, unknown>;

function usage(calls: number, images = 0, cost = "0.000000") {
  return { calls, images, input_tokens: calls * 900, output_tokens: calls * 300, cost_usd: cost };
}

function provider(fields: Json): Json {
  return {
    id: "claude_plan",
    title: "Claude plan",
    billing: "plan",
    state: "ok",
    state_source: "app",
    limited_until: null,
    last_checked_at: null,
    last_error: null,
    usage: { five_hours: usage(5), seven_days: usage(40) },
    usage_source: "app",
    budget: { calls_5h: 20, calls_7d: 150, images_5h: 5, images_7d: 30, usd_5h: "0", usd_7d: "0" },
    budget_used: 0.27,
    ...fields,
  };
}

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
/** A time later today or tomorrow, shown as hours and minutes in the browser's own zone. */
const LIMITED_UNTIL = new Date(Date.now() + 90 * 60_000).toISOString();

const CLAUDE_READY = () => provider({ last_checked_at: minutesAgo(3) });
const CHATGPT_LIMITED = () =>
  provider({
    id: "chatgpt_plan",
    title: "ChatGPT plan",
    state: "limited",
    state_source: "tool",
    limited_until: LIMITED_UNTIL,
    last_checked_at: minutesAgo(3),
    last_error: "You've hit your usage limit.",
    usage: { five_hours: usage(4, 5), seven_days: usage(30, 19) },
    budget_used: 1,
  });
const CHATGPT_READY = () =>
  provider({ id: "chatgpt_plan", title: "ChatGPT plan", usage: { five_hours: usage(2, 1), seven_days: usage(9, 4) } });
const CLAUDE_NEAR = () =>
  provider({ state: "near_budget", usage: { five_hours: usage(17), seven_days: usage(60) }, budget_used: 0.85 });
const CLAUDE_PAUSED = () =>
  provider({ state: "paused_by_budget", usage: { five_hours: usage(20), seven_days: usage(60) }, budget_used: 1 });

interface Fake {
  providers: Json[];
  afterCheck: Json[] | null;
  settings: Json;
  refuseBudget: { status: number; body: Json } | null;
  requests: { method: string; path: string; body: unknown }[];
  holdCheck: Promise<void> | null;
}

function fake(providers: Json[], mode = "subscription"): Fake {
  return {
    providers,
    afterCheck: null,
    settings: {
      provider_mode: mode,
      use_paid_apis: false,
      paid_apis_active: false,
      paid_apis_message: "Paid APIs are off: the 'Use paid APIs' switch in Settings is off.",
      secrets: { ANTHROPIC_API_KEY: false, OPENAI_API_KEY: false },
    },
    refuseBudget: null,
    requests: [],
    holdCheck: null,
  };
}

async function mockProviders(page: Page, state: Fake) {
  await mockEpisodes(page, () => []);
  await page.route("**/api/v1/providers**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.split("/api/v1")[1] ?? "";
    const method = request.method();
    const body: unknown = request.postData() ? request.postDataJSON() : null;
    if (method !== "GET") {
      state.requests.push({ method, path, body });
    }
    if (method === "POST" && path === "/providers/check") {
      await state.holdCheck;
      state.providers = state.afterCheck ?? state.providers;
    } else if (method === "PUT" && path.endsWith("/budget")) {
      if (state.refuseBudget) {
        return route.fulfill({ status: state.refuseBudget.status, json: state.refuseBudget.body });
      }
      const id = path.split("/")[2];
      state.providers = state.providers.map((row) =>
        row.id === id ? { ...row, budget: { ...(row.budget as Json), ...(body as Json) } } : row,
      );
    }
    await route.fulfill({ json: { providers: state.providers } });
  });
  await page.route("**/api/v1/settings", async (route: Route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { use_paid_apis: boolean };
      state.requests.push({ method: "PUT", path: "/settings", body });
      state.settings = { ...state.settings, use_paid_apis: body.use_paid_apis };
    }
    await route.fulfill({ json: state.settings });
  });
}

async function openUsage(page: Page, state: Fake) {
  await mockProviders(page, state);
  await open(page, "/settings/usage");
  return state;
}

const card = (page: Page, title: string) => page.getByRole("region", { name: title });
const chip = (page: Page, title: string) => card(page, title).getByTestId("provider-state");
const sent = (state: Fake, method: string, path: string) =>
  state.requests.filter((request) => request.method === method && request.path === path);
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

test.describe("FR-33 Usage page", () => {
  test("shows each provider with its state, both windows against the budget and who counted", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await openUsage(page, fake([CLAUDE_READY(), CHATGPT_LIMITED()]));

    await expect(page.getByRole("heading", { level: 1, name: "Usage and limits" })).toBeVisible();
    await expect(page.getByText("Subscription mode.")).toBeVisible();

    const claude = card(page, "Claude plan");
    await expect(chip(page, "Claude plan")).toHaveText("Ready");
    await expect(claude).toContainText("Through Claude Code on this PC");
    await expect(claude.getByTestId("usage-5h-calls")).toHaveText(/Last 5 hours.*5 of 20 calls/);
    await expect(claude.getByTestId("usage-7d-calls")).toHaveText(/Last 7 days.*40 of 150 calls/);
    await expect(claude).toContainText("Counted by this app");
    await expect(claude).toContainText("Last checked 3 min ago");

    const chatgpt = card(page, "ChatGPT plan");
    await expect(chip(page, "ChatGPT plan")).toHaveText(`Limited until ${clock(LIMITED_UNTIL)}`);
    await expect(chatgpt).toContainText("Through Codex on this PC");
    await expect(chatgpt.getByTestId("usage-5h-images")).toHaveText(/Last 5 hours.*5 of 5 images/);
    await expect(chatgpt.getByTestId("usage-7d-images")).toHaveText(/Last 7 days.*19 of 30 images/);
    await expect(chatgpt).toContainText("Limit reported by the tool");
    await expect(chatgpt).toContainText("You've hit your usage limit.");
  });

  test("a bar is as full as the budget is used, and never says it by colour alone", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openUsage(page, fake([CLAUDE_NEAR()]));

    const bar = card(page, "Claude plan").getByTestId("usage-5h-calls").getByRole("progressbar");
    await expect(bar).toHaveAttribute("aria-valuenow", "85");
    await expect(bar).toHaveAccessibleName("Last 5 hours, calls");
    await expect(chip(page, "Claude plan")).toHaveText("Near budget");
  });

  test("a paused provider says why and what frees it", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await openUsage(page, fake([CLAUDE_PAUSED()]));

    await expect(chip(page, "Claude plan")).toHaveText("Paused");
    await expect(card(page, "Claude plan")).toContainText("Your budget is used up");
  });

  test("a budget of zero allows nothing: the first use fills the bar", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const none = provider({
      state: "paused_by_budget",
      usage: { five_hours: usage(1), seven_days: usage(1) },
      budget: { calls_5h: 0, calls_7d: 150, images_5h: 5, images_7d: 30, usd_5h: "0", usd_7d: "0" },
      budget_used: 1,
    });
    await openUsage(page, fake([none]));

    const line = card(page, "Claude plan").getByTestId("usage-5h-calls");
    await expect(line).toHaveText(/1 of 0 calls/);
    await expect(line.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  test("demo mode says that nothing is sent, and has no budget to set", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const demo = provider({
      id: "demo",
      title: "Demo recordings",
      billing: "demo",
      budget: { calls_5h: 0, calls_7d: 0, images_5h: 0, images_7d: 0, usd_5h: "0", usd_7d: "0" },
      budget_used: 0,
    });
    await openUsage(page, fake([demo], "demo"));

    await expect(page.getByText("Demo mode.", { exact: true })).toBeVisible();
    await expect(card(page, "Demo recordings").getByTestId("usage-5h-calls")).toHaveText(/5 calls/);
    await expect(card(page, "Demo recordings").getByRole("spinbutton")).toHaveCount(0);
  });

  test("a budget is changed and saved", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const state = await openUsage(page, fake([CLAUDE_READY()]));

    const claude = card(page, "Claude plan");
    await expect(claude.getByRole("spinbutton", { name: "Calls per 5 hours" })).toHaveValue("20");
    await claude.getByRole("spinbutton", { name: "Calls per 5 hours" }).fill("60");
    await claude.getByRole("spinbutton", { name: "Calls per 7 days" }).fill("600");
    await claude.getByRole("button", { name: "Save budget" }).click();

    await expect(claude.getByText("Saved.")).toBeVisible();
    await expect(claude.getByTestId("usage-5h-calls")).toHaveText(/5 of 60 calls/);
    expect(sent(state, "PUT", "/providers/claude_plan/budget")[0]?.body).toEqual({
      calls_5h: 60,
      calls_7d: 600,
      images_5h: 5,
      images_7d: 30,
    });
  });

  test("a budget the API refuses shows the reason and keeps what was typed", async ({ page }) => {
    const state = fake([CLAUDE_READY()]);
    state.refuseBudget = {
      status: 409,
      body: {
        error: { code: "budget_conflict", message: "The 5 hour budget cannot be larger than the 7 day budget." },
      },
    };
    await page.setViewportSize(SIZES.desktop);
    await openUsage(page, state);

    const claude = card(page, "Claude plan");
    await claude.getByRole("spinbutton", { name: "Calls per 5 hours" }).fill("900");
    await claude.getByRole("button", { name: "Save budget" }).click();

    await expect(claude.getByRole("alert")).toContainText(
      "The 5 hour budget cannot be larger than the 7 day budget.",
    );
    await expect(claude.getByRole("spinbutton", { name: "Calls per 5 hours" })).toHaveValue("900");
  });

  test("a paid provider is marked, counts money, and its budget is set in dollars", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const paid = provider({
      id: "anthropic_api",
      title: "Anthropic API",
      billing: "api",
      usage: { five_hours: usage(6, 0, "0.420000"), seven_days: usage(21, 0, "1.310000") },
      budget: { calls_5h: 0, calls_7d: 0, images_5h: 0, images_7d: 0, usd_5h: "1", usd_7d: "5" },
      budget_used: 0.42,
    });
    const state = await openUsage(page, fake([paid], "api"));

    const api = card(page, "Anthropic API");
    await expect(page.getByText("API mode.", { exact: true })).toBeVisible();
    await expect(api).toContainText("Anthropic API, paid per use");
    await expect(api.getByTestId("usage-5h-usd")).toHaveText(/Last 5 hours.*0\.42 of 1\.00 USD/);
    await expect(api.getByTestId("usage-7d-usd")).toHaveText(/Last 7 days.*1\.31 of 5\.00 USD/);
    await expect(api.getByTestId("usage-5h-calls")).toHaveText(/6 calls/);

    await expect(api.getByRole("textbox", { name: "US dollars per 5 hours" })).toHaveValue("1");
    await api.getByRole("textbox", { name: "US dollars per 5 hours" }).fill("2.50");
    await api.getByRole("textbox", { name: "US dollars per 7 days" }).fill("10");
    await api.getByRole("button", { name: "Save budget" }).click();

    await expect(api.getByText("Saved.")).toBeVisible();
    await expect(api.getByTestId("usage-5h-usd")).toHaveText(/0\.42 of 2\.50 USD/);
    await expect(api.getByRole("spinbutton")).toHaveCount(0);
    expect(sent(state, "PUT", "/providers/anthropic_api/budget")[0]?.body).toEqual({
      usd_5h: "2.50",
      usd_7d: "10",
    });
  });

  test("UX-06 a failed load shows the reason and Try again", async ({ page }) => {
    let broken = true;
    const state = fake([CLAUDE_READY()]);
    await mockProviders(page, state);
    await page.route("**/api/v1/providers", (route) =>
      broken
        ? route.fulfill({
            status: 503,
            json: { error: { code: "unavailable", message: "The database is not answering." } },
          })
        : route.fallback(),
    );
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/settings/usage");

    const alert = page.getByTestId("usage-error");
    await expect(alert).toHaveRole("alert");
    await expect(alert).toContainText("The database is not answering.");
    broken = false;
    await alert.getByRole("button", { name: "Try again" }).click();
    await expect(card(page, "Claude plan")).toBeVisible();
  });
});

test.describe("FR-34 Check limits now", () => {
  test("runs the check, shows that it runs, and confirms a provider that is ready again", async ({
    page,
  }) => {
    const state = fake([CLAUDE_READY(), CHATGPT_LIMITED()]);
    let release: () => void = () => undefined;
    state.holdCheck = new Promise<void>((resolve) => {
      release = resolve;
    });
    state.afterCheck = [
      provider({ last_checked_at: new Date().toISOString() }),
      { ...CHATGPT_READY(), last_checked_at: new Date().toISOString() },
    ];
    await page.setViewportSize(SIZES.desktop);
    await openUsage(page, state);
    await expect(chip(page, "ChatGPT plan")).toContainText("Limited until");

    await page.getByRole("button", { name: "Check limits now" }).click();
    await expect(page.getByRole("button", { name: "Checking" })).toBeDisabled();
    release();

    await expect(chip(page, "ChatGPT plan")).toHaveText("Ready");
    await expect(page.getByTestId("check-result")).toContainText(
      "ChatGPT plan is ready again. Its waiting jobs resume.",
    );
    await expect(card(page, "ChatGPT plan")).toContainText("Last checked just now");
    await expect(page.getByRole("button", { name: "Check limits now" })).toBeEnabled();
    expect(sent(state, "POST", "/providers/check")).toHaveLength(1);
  });

  test("a check that fails says so and leaves the page as it was", async ({ page }) => {
    const state = fake([CLAUDE_READY()]);
    await mockProviders(page, state);
    await page.route("**/api/v1/providers/check", (route) => route.abort());
    await page.setViewportSize(SIZES.desktop);
    await open(page, "/settings/usage");

    await page.getByRole("button", { name: "Check limits now" }).click();

    await expect(page.getByTestId("check-result")).toContainText("The API is not answering");
    await expect(chip(page, "Claude plan")).toHaveText("Ready");
  });
});

test.describe("Paid APIs switch", () => {
  test("is off, says what it needs, and asks before it is turned on", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const state = await openUsage(page, fake([CLAUDE_READY()]));

    const toggle = page.getByRole("switch", { name: "Use paid APIs" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(card(page, "Paid APIs")).toContainText("Paid APIs are off");

    await toggle.click();
    await expect(card(page, "Paid APIs")).toContainText("Paid APIs bill per use");
    expect(sent(state, "PUT", "/settings")).toHaveLength(0);
    await card(page, "Paid APIs").getByRole("button", { name: "Cancel" }).click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");

    await toggle.click();
    await card(page, "Paid APIs").getByRole("button", { name: "Turn on" }).click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(sent(state, "PUT", "/settings")[0]?.body).toEqual({ use_paid_apis: true });

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(sent(state, "PUT", "/settings")[1]?.body).toEqual({ use_paid_apis: false });
  });
});

test.describe("FR-33 model picker in Settings", () => {
  test("lists the models of the mode with state, bars and the counted or reported label", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    await mockProviders(page, fake([CLAUDE_NEAR(), CHATGPT_LIMITED()]));
    await open(page, "/settings");

    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    const picker = page.getByTestId("model-picker");
    await expect(picker).toContainText("Numbers are counted by this app unless marked.");
    const options = picker.getByRole("listitem");
    await expect(options).toHaveCount(2);
    await expect(options.nth(0)).toContainText("Claude plan");
    await expect(options.nth(0)).toContainText("Near budget");
    await expect(options.nth(0)).toContainText("17 of 20");
    await expect(options.nth(1)).toContainText(`Limited until ${clock(LIMITED_UNTIL)}`);
    await expect(options.nth(1)).toContainText(`Reported by the tool. Back at ${clock(LIMITED_UNTIL)}.`);
    await expect(options.nth(1)).toHaveAttribute("data-available", "false");
    await expect(options.nth(0)).toHaveAttribute("data-available", "true");

    await page.getByRole("main").getByRole("link", { name: "Usage and limits" }).click();
    await expect(page).toHaveURL(/\/settings\/usage$/);
  });
});

test.describe("Status strip warning", () => {
  test("names the provider that is limited and leads to the Usage page", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await mockProviders(page, fake([CLAUDE_READY(), CHATGPT_LIMITED()]));
    await open(page);

    const warning = page.getByTestId("provider-warning");
    await expect(warning).toHaveText("ChatGPT plan limited");
    await warning.click();
    await expect(page).toHaveURL(/\/settings\/usage$/);
  });

  test("says near budget and paused in words, and counts when there are several", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    const state = fake([CLAUDE_NEAR()]);
    await mockProviders(page, state);
    await open(page);
    await expect(page.getByTestId("provider-warning")).toHaveText("Claude plan near budget");

    state.providers = [CLAUDE_PAUSED(), CHATGPT_LIMITED()];
    await page.reload();
    await expect(page.getByTestId("provider-warning")).toHaveText("2 providers need attention");
  });

  test("is absent while every provider is ready, and keeps its words for screen readers on a phone", async ({
    page,
  }) => {
    await page.setViewportSize(SIZES.desktop);
    const state = fake([CLAUDE_READY()]);
    await mockProviders(page, state);
    await open(page);
    await expect(page.getByTestId("demo-badge")).toBeVisible();
    await expect(page.getByTestId("provider-warning")).toBeHidden();

    state.providers = [CHATGPT_LIMITED()];
    await page.setViewportSize(SIZES.phone);
    await page.reload();
    await expect(page.getByTestId("provider-warning")).toHaveAccessibleName("ChatGPT plan limited");
    const box = await page.getByTestId("provider-warning").boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
    expect(await sidewaysOverflow(page)).toBeLessThanOrEqual(0);
  });
});

test.describe("Usage and Settings at every size", () => {
  for (const width of [360, 768, 1280, 1920]) {
    test(`UX-01 both fit at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await mockProviders(page, fake([CLAUDE_NEAR(), CHATGPT_LIMITED()]));
      for (const path of ["/settings/usage", "/settings"]) {
        await open(page, path);
        await expect(page.getByText("ChatGPT plan").first()).toBeVisible();
        expect(await sidewaysOverflow(page), path).toBeLessThanOrEqual(0);
      }
    });
  }

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`UX-05 axe finds no violations on ${size}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await mockProviders(page, fake([CLAUDE_NEAR(), CHATGPT_LIMITED(), CLAUDE_PAUSED()].slice(0, 2)));
      for (const path of ["/settings/usage", "/settings"]) {
        await open(page, path);
        await expect(page.getByText("ChatGPT plan").first()).toBeVisible();
        const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
        expect(results.violations.map((violation) => violation.id), path).toEqual([]);
      }
    });
  }

  for (const size of ["phone", "tablet"] as const) {
    test(`UX-04 touch targets are at least 44 by 44 px on ${size}`, async ({ page }) => {
      await page.setViewportSize(SIZES[size]);
      await mockProviders(page, fake([CLAUDE_NEAR(), CHATGPT_LIMITED()]));
      for (const path of ["/settings/usage", "/settings"]) {
        await open(page, path);
        await expect(page.getByText("ChatGPT plan").first()).toBeVisible();
        const targets = page.getByRole("main").locator("a:visible, button:visible, input:visible");
        expect(await targets.count()).toBeGreaterThan(1);
        for (const target of await targets.all()) {
          const box = await target.boundingBox();
          const name = (await target.getAttribute("aria-label")) ?? (await target.innerText().catch(() => "input"));
          expect(box?.width, `"${name}" on ${path} is too narrow`).toBeGreaterThanOrEqual(44);
          expect(box?.height, `"${name}" on ${path} is too short`).toBeGreaterThanOrEqual(44);
        }
      }
    });
  }
});

test.describe("Usage page through the real API", () => {
  test("demo mode shows the demo provider, and a check answers", async ({ page }) => {
    await page.setViewportSize(SIZES.desktop);
    await mockEpisodes(page, () => []);
    await open(page, "/settings/usage");

    await expect(page.getByText("Demo mode.", { exact: true })).toBeVisible();
    await expect(chip(page, "Demo recordings")).toHaveText("Ready");
    await page.getByRole("button", { name: "Check limits now" }).click();
    await expect(page.getByRole("button", { name: "Check limits now" })).toBeEnabled();
    await expect(chip(page, "Demo recordings")).toHaveText("Ready");
    await expect(page.getByRole("switch", { name: "Use paid APIs" })).toHaveAttribute("aria-checked", "false");
  });
});

test.describe("Usage page matches its approved screenshots", () => {
  test.skip(process.platform !== "linux", "screenshots are compared in the Linux test image only");

  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`Usage at ${viewport.width} px (${size})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      // Fixed times, so the picture does not change with the clock.
      await page.clock.setFixedTime(new Date("2026-11-12T16:00:00Z"));
      const state = fake([
        provider({ last_checked_at: "2026-11-12T15:57:00Z" }),
        {
          ...CHATGPT_LIMITED(),
          limited_until: "2026-11-12T17:40:00Z",
          last_checked_at: "2026-11-12T15:57:00Z",
        },
      ]);
      await mockProviders(page, state);
      await open(page, "/settings/usage");
      await expect(card(page, "ChatGPT plan")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      await expect(page).toHaveScreenshot(`usage-${viewport.width}.png`, { fullPage: true });
    });
  }
});
