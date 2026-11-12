// Shared helpers for the browser tests.
import { type Page, type Route, expect } from "@playwright/test";

export const SIZES = {
  phone: { width: 390, height: 844 },
  tablet: { width: 820, height: 1180 },
  desktop: { width: 1440, height: 900 },
} as const;

export const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/** One row of GET /episodes, as the API sends it. */
export interface EpisodeRow {
  id: string;
  idea: string;
  title: string | null;
  state: string;
  awaiting_approval: boolean;
  gate: string | null;
  spec_version: number | null;
  stale_from_state: string | null;
  stale_scenes: Record<string, string[]>;
  target_duration_s: number;
  created_at: string;
}

export function episode(number: number, fields: Partial<EpisodeRow> = {}): EpisodeRow {
  return {
    id: `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`,
    idea: `Idea number ${number}`,
    title: null,
    state: "brief",
    awaiting_approval: false,
    gate: null,
    spec_version: null,
    stale_from_state: null,
    stale_scenes: {},
    target_duration_s: 45,
    created_at: "2026-11-12T08:00:00Z",
    ...fields,
  };
}

/** The episodes of the Board mockups, plus one that has no title yet. */
export const SAMPLE_EPISODES: EpisodeRow[] = [
  episode(1, {
    title: "The Lighthouse Keeper",
    state: "direction",
    awaiting_approval: true,
    gate: "plan",
    spec_version: 1,
  }),
  episode(2, {
    title: "Two Chairs",
    state: "critique",
    awaiting_approval: true,
    gate: "review",
    spec_version: 2,
  }),
  episode(3, { title: "The Second Bowl", state: "research" }),
  episode(4, { title: "Small Steps", state: "asset_gen", spec_version: 1 }),
  episode(5, { title: "The Long Road Home", state: "done", spec_version: 3 }),
  episode(6, { title: "What the River Kept", state: "done", spec_version: 1 }),
  episode(7, { idea: "A baker who gives away the first loaf every morning", state: "brief" }),
];

function listBody(all: EpisodeRow[], url: string) {
  const query = new URL(url).searchParams;
  const limit = Number(query.get("limit") ?? 50);
  const offset = Number(query.get("offset") ?? 0);
  return { episodes: all.slice(offset, offset + limit), total: all.length, limit, offset };
}

/**
 * Answer GET /episodes from a fixed list, so a test does not depend on what other tests
 * left in the database. Other requests go on to the real API.
 */
export async function mockEpisodes(page: Page, episodes: () => EpisodeRow[]) {
  await page.route("**/api/v1/episodes?*", async (route: Route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    await route.fulfill({ json: listBody(episodes(), route.request().url()) });
  });
}

/** Open a page and wait until the status strip has heard from the API. */
export async function open(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.getByTestId("demo-badge")).toBeVisible();
}

export async function sidewaysOverflow(page: Page) {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}
