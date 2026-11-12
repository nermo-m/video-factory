// How an episode is shown on the Board (design doc section 11.2 and the Board mockups):
// which group it belongs to, where it is in the pipeline, and what it is doing in words.
// No React and no requests here, only what follows from the episode itself.
import type { EpisodeDetail, EpisodeOut, EpisodeState, JobOut } from "@/api/client";

export type GroupId = "needs-you" | "planning" | "producing" | "finished";

const PLANNING_STATES: readonly EpisodeState[] = ["idea", "brief", "research", "script", "direction"];

/** Anything waiting for the owner comes first, whatever state it is in. */
export function groupOf(episode: EpisodeOut): GroupId {
  if (episode.awaiting_approval) {
    return "needs-you";
  }
  // A rendered episode has done everything that is built so far.
  if (episode.state === "done" || episode.resting) {
    return "finished";
  }
  return PLANNING_STATES.includes(episode.state) ? "planning" : "producing";
}

/** The seven steps of the progress strip. Each covers one or more pipeline states. */
export const STEPS: readonly { label: string; states: readonly EpisodeState[] }[] = [
  { label: "Brief", states: ["brief"] },
  { label: "Research", states: ["research"] },
  { label: "Script", states: ["script"] },
  { label: "Direction", states: ["direction"] },
  { label: "Pictures", states: ["asset_plan", "asset_gen"] },
  { label: "Video", states: ["voice", "render", "qc", "critique"] },
  { label: "Export", states: ["package", "export"] },
];

export type StepTone = "done" | "working" | "waiting" | "todo";

export interface Progress {
  tones: StepTone[];
  /** The same fact in words, for screen readers and for anyone who cannot tell the colours apart. */
  label: string;
}

export function progressOf(episode: EpisodeOut): Progress {
  if (episode.state === "done") {
    return { tones: STEPS.map(() => "done"), label: `All ${STEPS.length} steps finished` };
  }
  const current = STEPS.findIndex((step) => step.states.includes(episode.state));
  const step = STEPS[current];
  if (!step) {
    return { tones: STEPS.map(() => "todo"), label: "Not started" };
  }
  const now: StepTone = episode.resting ? "done" : episode.awaiting_approval ? "waiting" : "working";
  return {
    tones: STEPS.map((_, index) => (index < current ? "done" : index === current ? now : "todo")),
    label: `Step ${current + 1} of ${STEPS.length}, ${step.label}: ${
      episode.resting ? "done" : episode.awaiting_approval ? "waiting for you" : "in progress"
    }`,
  };
}

const GATE_ACTIONS: Record<string, string> = {
  plan: "Approve the plan",
  assets: "Approve the pictures",
  review: "Review the video",
};

const WORKING: Record<EpisodeState, string> = {
  idea: "Waiting to start",
  brief: "Writing the brief",
  research: "Checking sources",
  script: "Writing the script",
  direction: "Directing the scenes",
  asset_plan: "Planning the pictures",
  asset_gen: "Making pictures and clips",
  voice: "Recording the voice",
  render: "Rendering the video",
  qc: "Checking the video",
  critique: "Reviewing the video",
  package: "Writing the title and description",
  export: "Exporting",
  done: "Exported",
};

export type StatusTone = "waiting" | "working" | "finished" | "idle";

/** The one line under the progress strip: what the episode is doing, or what it needs. */
export function statusOf(episode: EpisodeOut): { tone: StatusTone; label: string } {
  if (episode.awaiting_approval) {
    return {
      tone: "waiting",
      label: GATE_ACTIONS[episode.gate ?? ""] ?? "Waiting for your approval",
    };
  }
  if (episode.state === "done") {
    return { tone: "finished", label: WORKING.done };
  }
  if (episode.resting) {
    return { tone: "finished", label: "Video rendered" };
  }
  return { tone: episode.state === "idea" ? "idle" : "working", label: WORKING[episode.state] };
}

/** What a state is doing, in words: "Recording the voice". */
export const workingOn = (state: EpisodeState) => WORKING[state];

/** The job types of each state that has jobs (design doc section 4.1). */
const STATE_JOBS: Partial<Record<EpisodeState, readonly string[]>> = {
  brief: ["plan.brief"],
  research: ["plan.research"],
  script: ["plan.script"],
  direction: ["plan.direct"],
  asset_plan: ["plan.assets"],
  asset_gen: ["gen.image", "gen.clip"],
  voice: ["gen.voice"],
  render: ["render.scene", "render.join"],
  qc: ["qc.run"],
  critique: ["agent.critic"],
  package: ["plan.package"],
  export: ["export.pack"],
};

/** The jobs of the state the episode is in, among its latest jobs. */
export function jobsOfState(episode: EpisodeDetail): JobOut[] {
  const types = STATE_JOBS[episode.state] ?? [];
  return episode.jobs.filter((job) => types.includes(job.type));
}

/**
 * Why the episode's current step stopped, or null while it works, waits for the owner or
 * is done. A step has stopped when one of its jobs failed and none is waiting or running
 * any more, so nothing will move it on by itself (section 4.4). The same reason is given
 * once, however many jobs it stopped.
 */
export function stoppedOf(episode: EpisodeDetail): { reasons: string[] } | null {
  if (episode.awaiting_approval || episode.resting || episode.state === "done") {
    return null;
  }
  const jobs = jobsOfState(episode);
  const failed = jobs.filter((job) => job.status === "failed");
  if (failed.length === 0 || jobs.some((job) => job.status === "queued" || job.status === "running")) {
    return null;
  }
  const reasons = failed.map((job) => job.error_message?.trim() || "The job failed without saying why.");
  return { reasons: [...new Set(reasons)] };
}

/** The title once the brief has written one. Until then, the owner's idea. */
export function displayTitle(episode: EpisodeOut): string {
  return episode.title?.trim() || episode.idea;
}

export function isOutOfDate(episode: EpisodeOut): boolean {
  return episode.stale_from_state !== null;
}

export function episodeCount(count: number): string {
  return `${count} ${count === 1 ? "episode" : "episodes"}`;
}
