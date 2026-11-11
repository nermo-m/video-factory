import { defineConfig, devices } from "@playwright/test";

// The tests expect the Compose stack in demo mode. Run them with `make e2e`, which uses
// the pinned Playwright image so screenshots are identical on every machine.
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  expect: {
    // Right after the stack starts, the first requests are slow. Wait longer than the
    // 5 second default before deciding that something did not appear.
    timeout: 15_000,
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
