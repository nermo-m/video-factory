// A small stand-in for the episode routes, so the workspace tests do not depend on the
// database or the worker. It keeps one episode and answers the way the API does.
import type { Page, Route } from "@playwright/test";

import { type EpisodeRow, episode } from "./support";

export const EPISODE_ID = "00000000-0000-4000-8000-000000000001";

type Json = Record<string, unknown>;

export interface Scene extends Json {
  id: string;
  kind: string;
  narration: string;
}

export function sampleSpec(): { scenes: Scene[] } & Json {
  return {
    spec_version: "2.0",
    episode_id: EPISODE_ID,
    format: { width: 1080, height: 1920, fps: 30, target_duration_s: 45 },
    theme: "night_scrolls",
    voice: { voice_id: "bm_george", speed: 1 },
    seed: 7,
    claims: [
      {
        id: "c_garden_study",
        text: "In this made-up study, daily gardeners kept the habit for a year.",
        source_url: "https://example.org/fixture/garden-study",
        source_name: "Example Garden Study (test fixture)",
        source_date: "2026-01-15",
        passage: "Daily gardeners kept the habit for a year.",
        retrieved_at: "2026-11-11T09:30:00Z",
      },
    ],
    assets: [],
    scenes: [
      {
        id: "s01_hook",
        kind: "title",
        narration: "To everyone who waters one plant and thinks it is nothing.",
        text: [
          { content: "ONE PLANT", style: "slam", cue: { word: 4 } },
          { content: "IS A START.", style: "slam_accent", cue: { word: 6 } },
        ],
        sound: [{ cue_id: "slam", cue: { word: 4 } }],
        retention_device: "A start of what?",
        transition_out: "smoke",
      },
      {
        id: "s02_garden",
        kind: "scroll",
        title: "THE GARDEN",
        label: "DAY ONE",
        sublabel: "nobody was watching",
        visual: { asset_id: "a_garden_dawn" },
        narration: "The gardener watered the same bed every morning. Nobody asked her to.",
        overlays: [
          { type: "tag", lines: ["EVERY", "MORNING"], side: "left", cue: { word: 6 } },
          { type: "sprite", name: "moon", action: "glow", cue: { scene_start_s: 0 } },
        ],
        sound: [{ cue_id: "paper_unroll", cue: { scene_start_s: 0.1 }, gain_db: -3 }],
        retention_device: "Why would anyone do this unseen?",
        transition_out: "smoke",
      },
      {
        id: "s03_outro",
        kind: "outro",
        narration: "One plant is a start.",
        text: [{ content: "ONE PLANT IS A START.", style: "slam_accent" }],
        hold_s: 2,
      },
    ],
  };
}

const WORDS_PER_SECOND = 2.3;

function planOf(spec: { scenes: Scene[] } | null, fits: boolean | null): Json {
  const scenes = (spec?.scenes ?? []).map((scene) => {
    const words = scene.narration.split(/\s+/).filter(Boolean).length;
    return { id: scene.id, words, estimated_s: Math.round((words / WORDS_PER_SECOND + 0.7) * 10) / 10 };
  });
  const total = scenes.reduce((sum, scene) => sum + scene.estimated_s, 0);
  return {
    brief: spec
      ? {
          angle: "A gardener waters one bed every morning, and a year later the street is green.",
          lesson: "One small thing, done daily, is a start.",
          audience: "Someone who thinks one small step is too small to matter.",
          titles: ["The Gardener Nobody Watched"],
        }
      : null,
    scenes,
    estimated_total_s: spec ? Math.round(total * 10) / 10 : null,
    target_duration_s: 45,
    shortest_s: 41,
    longest_s: 49.4,
    fits: spec ? (fits ?? true) : null,
  };
}

export interface Revision {
  status: "queued" | "running" | "succeeded" | "failed";
  summary?: string;
  message?: string;
  /** Applied to the spec when the owner presses Apply. */
  change?: (spec: { scenes: Scene[] }) => void;
  changes?: { op: string; path: string; old?: unknown; new?: unknown }[];
  can_apply?: boolean;
}

export interface FakeEpisode {
  episode: EpisodeRow;
  spec: ({ scenes: Scene[] } & Json) | null;
  version: number;
  /** What the plan route says about fitting. Null means: follow the spec. */
  fits: boolean | null;
  /** What the next PUT /spec answers with instead of storing, when set. */
  refuseSpec: { status: number; body: Json } | null;
  /** The revision the next comment gets. */
  revision: Revision;
  /** How many times a revision is read before it stops being "running". */
  revisionReadsUntilReady: number;
  /** The episode's latest jobs, newest first, as GET /episodes/{id} lists them. */
  jobs: Json[];
  /** The episode's videos, newest first. */
  renders: Json[];
  requests: { method: string; path: string; body: unknown }[];
}

let jobNumber = 0;

/** One row of an episode's jobs. */
export function job(type: string, status: string, fields: Json = {}): Json {
  jobNumber += 1;
  return {
    id: `00000000-0000-4000-8000-${String(jobNumber).padStart(12, "0")}`,
    type,
    status,
    error_class: null,
    error_message: null,
    attempts: status === "queued" ? 0 : 1,
    created_at: "2026-11-12T08:05:00Z",
    started_at: status === "queued" ? null : "2026-11-12T08:05:01Z",
    finished_at: status === "succeeded" || status === "failed" ? "2026-11-12T08:05:09Z" : null,
    ...fields,
  };
}

export const VIDEO_URL = "/api/v1/files/jobs/render.join/ab/abcdef/video.mp4";
export const SHEET_URL = "/api/v1/files/jobs/render.join/ab/abcdef/video_contact_sheet.jpg";

/** One video of an episode, as GET /episodes/{id}/renders lists it. */
export function render(fields: Json = {}): Json {
  return {
    id: "00000000-0000-4000-8000-0000000000f1",
    kind: "draft",
    created_at: "2026-11-12T08:09:00Z",
    duration_s: 44.25,
    video_url: VIDEO_URL,
    contact_sheet_url: SHEET_URL,
    spec_version: 1,
    ...fields,
  };
}

export function fakeEpisode(fields: Partial<EpisodeRow> = {}): FakeEpisode {
  return {
    episode: episode(1, {
      id: EPISODE_ID,
      title: "The Gardener Nobody Watched",
      idea: "A gardener who waters one bed every morning",
      state: "direction",
      awaiting_approval: true,
      gate: "plan",
      spec_version: 1,
      ...fields,
    }),
    spec: sampleSpec(),
    version: 1,
    fits: null,
    refuseSpec: null,
    revision: {
      status: "succeeded",
      summary: "The hook now ends with a hard cut instead of smoke.",
      change: (spec) => {
        const first = spec.scenes[0];
        if (first) {
          first.transition_out = "cut";
        }
      },
      changes: [{ op: "replace", path: "/scenes/0/transition_out", old: "smoke", new: "cut" }],
      can_apply: true,
    },
    revisionReadsUntilReady: 1,
    jobs: [],
    renders: [],
    requests: [],
  };
}

const JOB_ID = "00000000-0000-4000-8000-0000000000aa";

function error(status: number, code: string, message: string, details: Json = {}) {
  return { status, json: { error: { code, message, details } } };
}

/** Answer every route of one episode from `fake`. */
export async function mockEpisode(page: Page, fake: FakeEpisode) {
  let comment = "";
  let reads = 0;

  const specOut = () => ({
    version: fake.version,
    author: fake.version === 1 ? "model" : "owner",
    skill_version: null,
    created_at: "2026-11-12T08:00:00Z",
    spec: fake.spec,
  });
  const detail = () => ({
    ...fake.episode,
    spec_version: fake.spec ? fake.version : null,
    jobs: fake.jobs,
  });
  const revision = () => {
    reads += 1;
    const ready = reads > fake.revisionReadsUntilReady;
    const result = fake.revision;
    return {
      job_id: JOB_ID,
      status: ready ? result.status : "running",
      base_version: fake.version,
      comment,
      summary: ready ? (result.summary ?? null) : null,
      patch: ready && result.changes ? [] : null,
      changes: ready ? (result.changes ?? null) : null,
      can_apply: ready && (result.can_apply ?? false),
      message: ready ? (result.message ?? null) : null,
    };
  };

  await page.route(`**/api/v1/episodes/${fake.episode.id}**`, async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.split(`/episodes/${fake.episode.id}`)[1] ?? "";
    const method = request.method();
    const body: unknown = method === "GET" ? null : request.postDataJSON();
    if (method !== "GET") {
      fake.requests.push({ method, path, body });
    }

    if (method === "GET" && path === "") {
      return route.fulfill({ json: detail() });
    }
    if (method === "GET" && path === "/spec") {
      return fake.spec
        ? route.fulfill({ json: specOut() })
        : route.fulfill(error(404, "no_spec", "This episode has no spec yet. The plan writes it."));
    }
    if (method === "GET" && path === "/plan") {
      return route.fulfill({ json: planOf(fake.spec, fake.fits) });
    }
    if (method === "PUT" && path === "/spec") {
      if (fake.refuseSpec) {
        return route.fulfill({ status: fake.refuseSpec.status, json: fake.refuseSpec.body });
      }
      fake.spec = body as FakeEpisode["spec"];
      fake.version += 1;
      return route.fulfill({ json: specOut() });
    }
    if (method === "POST" && path === "/revise") {
      comment = (body as { comment: string }).comment;
      reads = 0;
      return route.fulfill({
        status: 202,
        json: { ...revision(), status: "queued", summary: null, changes: null, can_apply: false },
      });
    }
    if (method === "GET" && path === `/revisions/${JOB_ID}`) {
      return route.fulfill({ json: revision() });
    }
    if (method === "POST" && path === "/revise/apply") {
      if (fake.spec) {
        fake.revision.change?.(fake.spec);
      }
      fake.version += 1;
      return route.fulfill({ json: specOut() });
    }
    if (method === "GET" && path === "/renders") {
      return route.fulfill({
        json: { renders: fake.renders, total: fake.renders.length, limit: 24, offset: 0 },
      });
    }
    if (method === "POST" && path === "/approve") {
      const next = fake.episode.gate === "assets" ? "voice" : "asset_plan";
      fake.episode = { ...fake.episode, state: next, awaiting_approval: false, gate: null };
      return route.fulfill({ json: detail() });
    }
    if (method === "POST" && path === "/rerun") {
      fake.episode = { ...fake.episode, state: (body as { state: string }).state };
      fake.jobs = [job("gen.voice", "queued")];
      return route.fulfill({ json: detail() });
    }
    if (method === "POST" && path === "/reject") {
      fake.episode = { ...fake.episode, awaiting_approval: false, gate: null };
      return route.fulfill({ json: detail() });
    }
    if (method === "POST" && path === "/advance") {
      fake.episode = { ...fake.episode, state: "brief" };
      return route.fulfill({ json: detail() });
    }
    return route.fulfill(error(404, "not_found", "This does not exist."));
  });
}

export const workspacePath = (id = EPISODE_ID) => `/episodes/${id}`;
