// How the episode workspace words things (design doc sections 11.2 and 11.5, and the
// workspace mockups): the eight steps of the pipeline, what a scene shows, and how a
// proposed change reads. No React and no requests here.
import type {
  AssetOut,
  ChangeOut,
  EpisodeDetail,
  EpisodeOut,
  EpisodeState,
  JobOut,
  RenderOut,
} from "@/api/client";

import { jobsOfState, statusOf, stoppedOf, workingOn } from "./episodes";

/** The spec as the API sends it. Only what the Plan tab reads is named. */
export interface Scene {
  id: string;
  kind: string;
  narration?: string;
  title?: string;
  label?: string;
  sublabel?: string;
  text?: { content?: string }[];
  visual?: { asset_id?: string };
  stat?: { value?: string; label?: string };
  steps?: { text?: string }[];
  overlays?: Record<string, unknown>[];
  sound?: { cue_id?: string }[];
  retention_device?: string;
  transition_out?: string;
  pad_after_s?: number;
  hold_s?: number;
  [key: string]: unknown;
}

export interface Claim {
  id?: string;
  text?: string;
  source_url?: string;
  source_name?: string;
  source_date?: string;
}

export interface Spec {
  scenes?: Scene[];
  claims?: Claim[];
  [key: string]: unknown;
}

/** The pipeline as the workspace shows it. Each step covers one or more states. */
export const PIPELINE: readonly { label: string; states: readonly EpisodeState[] }[] = [
  { label: "Brief", states: ["brief"] },
  { label: "Research", states: ["research"] },
  { label: "Script", states: ["script"] },
  { label: "Plan", states: ["direction"] },
  { label: "Assets", states: ["asset_plan", "asset_gen"] },
  { label: "Voice", states: ["voice"] },
  { label: "Render", states: ["render", "qc"] },
  { label: "Review", states: ["critique", "package", "export"] },
];

export type StepState = "done" | "working" | "waiting" | "todo";

export const STEP_WORDS: Record<StepState, string> = {
  done: "done",
  working: "in progress",
  waiting: "waiting for you",
  todo: "not started",
};

export function pipelineOf(episode: EpisodeOut): { label: string; state: StepState }[] {
  const current =
    episode.state === "done"
      ? PIPELINE.length
      : PIPELINE.findIndex((step) => step.states.includes(episode.state));
  return PIPELINE.map((step, index) => ({
    label: step.label,
    state:
      current === -1 || index > current
        ? "todo"
        : index < current || episode.resting
          ? "done"
          : episode.awaiting_approval
            ? "waiting"
            : "working",
  }));
}

const NEEDS_YOU: Record<string, string> = {
  plan: "Plan needs you",
  assets: "Pictures need you",
  review: "Video needs you",
};

export type ChipTone = "waiting" | "working" | "finished" | "stopped";

/** The chip beside the title. */
export function chipOf(episode: EpisodeDetail): { tone: ChipTone; label: string } {
  if (episode.awaiting_approval) {
    return { tone: "waiting", label: NEEDS_YOU[episode.gate ?? ""] ?? "Needs you" };
  }
  if (stoppedOf(episode)) {
    const step = PIPELINE.find((candidate) => candidate.states.includes(episode.state));
    return { tone: "stopped", label: `${step?.label ?? "Step"} stopped` };
  }
  const status = statusOf(episode);
  return { tone: status.tone === "finished" ? "finished" : "working", label: status.label };
}

/** How far a step that makes one thing per scene has come: "3 of 7 scenes". */
export interface SceneProgress {
  heading: string;
  /** Null while the step does something that is not counted in scenes. */
  done: number | null;
  total: number | null;
  text: string;
}

const count = (jobs: JobOut[], type: string, status?: string) =>
  jobs.filter((job) => job.type === type && (status === undefined || job.status === status)).length;

/**
 * What the Render tab says while the video is being made: null before the voice starts
 * and once the video is there.
 */
export function makingOf(episode: EpisodeDetail): SceneProgress | null {
  if (episode.resting || episode.awaiting_approval) {
    return null;
  }
  if (episode.state !== "voice" && episode.state !== "render") {
    return null;
  }
  const jobs = jobsOfState(episode);
  const heading = workingOn(episode.state);
  const type = episode.state === "voice" ? "gen.voice" : "render.scene";
  const total = count(jobs, type);
  const done = count(jobs, type, "succeeded");
  if (episode.state === "render" && count(jobs, "render.join") > 0) {
    return { heading, done: null, total: null, text: "Joining the scenes and mixing the sound." };
  }
  if (total === 0) {
    return { heading, done: null, total: null, text: "Starting." };
  }
  return { heading, done, total, text: `${done} of ${total} ${total === 1 ? "scene" : "scenes"}` };
}

function plural(amount: number, unit: string): string {
  return `${amount} ${unit}${amount === 1 ? "" : "s"}`;
}

/** A length for people: "44 seconds", "1 minute 1 second". */
export function lengthOf(seconds: number): string {
  const whole = Math.round(seconds);
  if (whole < 60) {
    return plural(whole, "second");
  }
  const rest = whole % 60;
  return rest === 0
    ? plural(Math.floor(whole / 60), "minute")
    : `${plural(Math.floor(whole / 60), "minute")} ${plural(rest, "second")}`;
}

/** The line under a video: what it is, how long, and which plan it was made from. */
export function renderCaption(render: RenderOut): string {
  const kind = { draft: "Draft video", preview: "Preview", final: "Final video" }[render.kind];
  const length = render.duration_s === null ? "" : `, ${lengthOf(render.duration_s)}`;
  const plan = render.spec_version === null ? "" : `, from version ${render.spec_version} of the plan`;
  return `${kind}${length}${plan}`;
}

function capital(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function words(name: string): string {
  return name.replaceAll("_", " ");
}

export function sceneHeading(scene: Scene, index: number): string {
  return `Scene ${index + 1}, ${scene.title?.trim() || capital(words(scene.kind))}`;
}

function joined(parts: (string | undefined)[], separator: string): string {
  return parts.filter((part): part is string => Boolean(part?.trim())).join(separator);
}

function overlayChip(overlay: Record<string, unknown>): string {
  const text = (key: string) => (typeof overlay[key] === "string" ? (overlay[key] as string) : undefined);
  const lines = Array.isArray(overlay.lines) ? overlay.lines.map(String).join(" ") : undefined;
  const detail = lines ?? text("text") ?? joined([text("name"), text("action")], ", ");
  const type = capital(words(text("type") ?? "overlay"));
  return detail ? `${type}: ${detail}` : type;
}

/** The short facts under a scene's narration: what is on screen, what is heard, how it ends. */
export function sceneChips(scene: Scene): string[] {
  const chips: string[] = [];
  const onScreen = scene.text?.length
    ? joined(
        scene.text.map((item) => item.content),
        " / ",
      )
    : joined([scene.title, scene.label, scene.sublabel], " / ");
  if (onScreen) {
    chips.push(`Text: ${onScreen}`);
  }
  if (scene.stat) {
    chips.push(`Stat: ${joined([scene.stat.value, scene.stat.label], " ")}`);
  }
  if (scene.steps?.length) {
    chips.push(
      `Steps: ${joined(
        scene.steps.map((step) => step.text),
        " / ",
      )}`,
    );
  }
  if (scene.visual?.asset_id) {
    chips.push(`Picture: ${scene.visual.asset_id}`);
  }
  for (const overlay of scene.overlays ?? []) {
    chips.push(overlayChip(overlay));
  }
  const sounds = new Set((scene.sound ?? []).map((cue) => cue.cue_id).filter(Boolean));
  for (const sound of sounds) {
    chips.push(`Sound: ${sound}`);
  }
  if (typeof scene.pad_after_s === "number") {
    chips.push(`Planned silence ${scene.pad_after_s} s`);
  }
  if (typeof scene.hold_s === "number") {
    chips.push(`Hold ${scene.hold_s} s`);
  }
  if (scene.transition_out) {
    chips.push(`Out: ${scene.transition_out}`);
  }
  return chips;
}

/** A JSON Pointer in plain words: "/scenes/1/pad_after_s" is "Scene 2, pad after s". */
export function changeLabel(path: string): string {
  const parts = path
    .split("/")
    .slice(1)
    .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"));
  const named: string[] = [];
  for (let index = 0; index < parts.length; index += 1) {
    const part = parts[index] ?? "";
    const next = parts[index + 1];
    if (part === "scenes" && next !== undefined && /^\d+$/.test(next)) {
      named.push(`Scene ${Number(next) + 1}`);
      index += 1;
    } else if (/^\d+$/.test(part)) {
      named.push(`item ${Number(part) + 1}`);
    } else {
      named.push(words(part));
    }
  }
  return named.join(", ") || "The whole spec";
}

export function shown(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

export function changeText(change: ChangeOut): { verb: string | null; before: string | null; after: string | null } {
  if (change.op === "add") {
    return { verb: "Added", before: null, after: shown(change.new) };
  }
  if (change.op === "remove") {
    return { verb: "Removed", before: shown(change.old), after: null };
  }
  return { verb: null, before: shown(change.old), after: shown(change.new) };
}

/** Only web addresses become links. A source address comes from a model's answer. */
export function safeLink(url: string | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}


/** A picture's id as a name: `a_garden_dawn` reads "Garden dawn". */
export function pictureName(id: string): string {
  const words = id.replace(/^a_/, "").replaceAll("_", " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function listed(items: string[]): string {
  if (items.length <= 1) {
    return items.join("");
  }
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

/** Which scenes show a picture, by their number in the plan: "Shown in scenes 2 and 3". */
export function shownIn(sceneIds: string[], scenes: Scene[]): string {
  const numbers = sceneIds
    .map((id) => scenes.findIndex((scene) => scene.id === id) + 1)
    .filter((number) => number > 0)
    .sort((a, b) => a - b)
    .map(String);
  if (numbers.length === 0) {
    return "Not shown in any scene";
  }
  return `Shown in ${numbers.length === 1 ? "scene" : "scenes"} ${listed(numbers)}`;
}

/** The line above the pictures: how many there are, where they come from, what is missing. */
export function picturesSummary(assets: AssetOut[]): string {
  const count = (origin: AssetOut["origin"]) => assets.filter((asset) => asset.origin === origin).length;
  const parts = [
    count("generated") > 0 ? `${count("generated")} made for this episode` : "",
    count("library") > 0 ? `${count("library")} from the library` : "",
    count("uploaded") > 0 ? `${count("uploaded")} to upload` : "",
  ].filter(Boolean);
  const missing = assets.filter((asset) => !asset.resolved).length;
  const total = `${assets.length} ${assets.length === 1 ? "picture" : "pictures"}`;
  const summary = `${total}: ${parts.join(", ")}.`;
  if (missing === 0) {
    return summary;
  }
  return `${summary} ${missing} ${missing === 1 ? "is" : "are"} not there yet.`;
}

/** A file name for a download, from the episode's title: "the-lighthouse-keeper.mp4". */
export function videoFileName(title: string): string {
  const slug = title
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug || "video"}.mp4`;
}
