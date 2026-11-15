// A plan of shots (Director mode): what it holds beyond the scenes, and how an edit of one
// shot is written back into the plan. No React and no requests here.
import type { Scene, Spec } from "./workspace";

export interface Character {
  id: string;
  name: string;
  description: string;
}

export type ChangeKind = "added" | "changed" | "not_possible";

/** One thing the studio added to the owner's prompt, changed in it, or could not do. */
export interface Change {
  scene?: string;
  kind: ChangeKind;
  what: string;
  why: string;
}

/** A picture of the plan. Only what the Plan tab reads is named. */
export interface PlanAsset {
  id: string;
  prompt?: string;
  characters?: string[];
  text_in_picture?: boolean;
  [key: string]: unknown;
}

export interface TextLine {
  content: string;
  position: string;
}

/** The camera moves of the plain look, with the words the screens use for them. */
export const CAMERAS: readonly (readonly [string, string])[] = [
  ["none", "Still"],
  ["push_in", "Slow push in"],
  ["pull_out", "Slow pull out"],
  ["pan_left", "Pan left"],
  ["pan_right", "Pan right"],
  ["tilt_up", "Tilt up"],
  ["tilt_down", "Tilt down"],
];

export const POSITIONS: readonly (readonly [string, string])[] = [
  ["top", "Top"],
  ["middle", "Middle"],
  ["bottom", "Bottom"],
];

/** A silent shot that is given no length lasts this long. */
export const SILENT_SHOT_S = 3;
export const MAX_TEXT_LINES = 4;

/** True for a plan of shots, which is built from the owner's own prompt. */
export function isOwnersPlan(spec: Spec): boolean {
  return typeof spec.spec_version === "string" && spec.spec_version !== "2.0";
}

export function charactersOf(spec: Spec): Character[] {
  return Array.isArray(spec.characters) ? (spec.characters as Character[]) : [];
}

export function changesOf(spec: Spec): Change[] {
  return Array.isArray(spec.changes) ? (spec.changes as Change[]) : [];
}

export function assetsOf(spec: Spec): PlanAsset[] {
  return Array.isArray(spec.assets) ? (spec.assets as PlanAsset[]) : [];
}

export function cameraLabel(camera: string | undefined): string {
  return CAMERAS.find(([id]) => id === camera)?.[1] ?? "Slow push in";
}

export const CHANGE_GROUPS: readonly (readonly [ChangeKind, string])[] = [
  ["added", "Added"],
  ["changed", "Changed"],
  ["not_possible", "Not possible yet"],
];

/** Where a change belongs, in words: "Scene 3", or "Whole video" when it names no scene. */
export function changePlace(change: Change, scenes: Scene[]): string {
  const index = scenes.findIndex((scene) => scene.id === change.scene);
  return index === -1 ? "Whole video" : `Scene ${index + 1}`;
}

/** What the owner can change about one shot, as the form holds it. */
export interface ShotDraft {
  narration: string;
  lines: TextLine[];
  seconds: string;
  prompt: string;
  characters: string[];
  camera: string;
  motion: string;
  clip: boolean;
}

function visualOf(scene: Scene): Record<string, unknown> {
  return (scene.visual ?? {}) as Record<string, unknown>;
}

export function draftOfShot(scene: Scene, asset: PlanAsset | undefined): ShotDraft {
  const visual = visualOf(scene);
  const text = (scene.text ?? []) as { content?: string; position?: string }[];
  return {
    narration: scene.narration ?? "",
    lines: text.map((item) => ({ content: item.content ?? "", position: item.position ?? "bottom" })),
    seconds: typeof scene.duration_s === "number" ? String(scene.duration_s) : "",
    prompt: asset?.prompt ?? "",
    characters: [...(asset?.characters ?? [])],
    camera: typeof visual.camera === "string" ? visual.camera : "push_in",
    motion: typeof visual.motion === "string" ? visual.motion : "",
    clip: visual.clip === true,
  };
}

function without<T extends Record<string, unknown>>(value: T, keys: string[]): T {
  return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key))) as T;
}

/**
 * The shot and its picture as the form leaves them. A field that was emptied is left out
 * of the plan, not stored as "". A line the owner typed is the owner's line. A shot
 * without a spoken line needs a length, and gets three seconds when none was given.
 */
export function editedShot(
  scene: Scene,
  asset: PlanAsset,
  draft: ShotDraft,
): { scene: Scene; asset: PlanAsset } {
  const narration = draft.narration.trim();
  const dropped: string[] = [];
  const next: Scene = { ...scene, narration };

  if (!narration) {
    dropped.push("narration_from");
  } else if (narration !== (scene.narration ?? "").trim() || !scene.narration_from) {
    next.narration_from = "owner";
  }

  const before = (scene.text ?? []) as Record<string, unknown>[];
  const lines = draft.lines
    .map((line, index) => ({ line, kept: before[index] ?? {} }))
    .filter(({ line }) => line.content.trim());
  if (lines.length > 0) {
    next.text = lines.map(({ line, kept }) => ({
      ...kept,
      content: line.content.trim(),
      style: "plain",
      position: line.position,
    }));
  } else {
    dropped.push("text");
  }

  const seconds = Number(draft.seconds.replace(",", "."));
  if (draft.seconds.trim() && Number.isFinite(seconds) && seconds > 0) {
    next.duration_s = seconds;
  } else if (!narration) {
    next.duration_s = SILENT_SHOT_S;
  } else {
    dropped.push("duration_s");
  }

  const visual: Record<string, unknown> = {
    ...without(visualOf(scene), ["motion"]),
    camera: draft.camera,
    clip: draft.clip,
  };
  if (draft.motion.trim()) {
    visual.motion = draft.motion.trim();
  }
  next.visual = visual as Scene["visual"];

  return {
    scene: without(next, dropped) as Scene,
    asset: { ...asset, prompt: draft.prompt.trim(), characters: draft.characters },
  };
}

/** The plan with one shot and its picture replaced. */
export function withShot(spec: Spec, index: number, scene: Scene, asset: PlanAsset): Spec {
  return {
    ...spec,
    scenes: (spec.scenes ?? []).map((old, position) => (position === index ? scene : old)),
    assets: assetsOf(spec).map((old) => (old.id === asset.id ? asset : old)),
  };
}

/** The plan with its look and its characters replaced. An emptied style is left out. */
export function withLook(spec: Spec, style: string, characters: Character[]): Spec {
  const next: Spec = {
    ...spec,
    characters: characters.map((character) => ({
      ...character,
      name: character.name.trim(),
      description: character.description.trim(),
    })),
  };
  if (style.trim()) {
    next.style = style.trim();
    return next;
  }
  return without(next, ["style"]) as Spec;
}
