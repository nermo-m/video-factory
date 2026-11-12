// How the episode workspace words things (design doc sections 11.2 and 11.5, and the
// workspace mockups): the eight steps of the pipeline, what a scene shows, and how a
// proposed change reads. No React and no requests here.
import type { ChangeOut, EpisodeOut, EpisodeState } from "@/api/client";

import { statusOf } from "./episodes";

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
        : index < current
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

/** The chip beside the title. */
export function chipOf(episode: EpisodeOut): { waiting: boolean; label: string } {
  if (episode.awaiting_approval) {
    return { waiting: true, label: NEEDS_YOU[episode.gate ?? ""] ?? "Needs you" };
  }
  return { waiting: false, label: statusOf(episode).label };
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
