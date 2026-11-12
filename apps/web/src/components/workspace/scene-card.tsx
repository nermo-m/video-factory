"use client";

import { type FormEvent, useId, useState } from "react";

import { type ApiFailure, failureOf } from "@/lib/api-error";
import { quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { type Scene, sceneChips, sceneHeading } from "@/lib/workspace";

export function Problems({ failure }: { failure: ApiFailure }) {
  return (
    <div role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
      <p>{failure.message}</p>
      {failure.problems.length > 0 && (
        <ul className="mt-2 list-disc pl-5 font-mono text-xs">
          {failure.problems.map((problem) => (
            <li key={problem} className="wrap-anywhere">
              {problem}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const fieldLook = "w-full rounded-lg border bg-raised px-3.5 py-2.5 text-base sm:text-sm";

function Field({
  label,
  value,
  onChange,
  rows,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-semibold text-muted-foreground">
        {label}
      </label>
      {rows ? (
        <textarea
          id={id}
          rows={rows}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={cn(fieldLook, "resize-y leading-normal")}
        />
      ) : (
        <input
          id={id}
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={cn(fieldLook, "h-11 py-0")}
        />
      )}
    </div>
  );
}

/** The text fields of a scene that can be edited in place. */
const OPTIONAL = [
  ["title", "Title"],
  ["label", "Label"],
  ["sublabel", "Sublabel"],
] as const;

function edited(scene: Scene, draft: Draft): Scene {
  // An optional field that was emptied is left out of the scene, not stored as "".
  const emptied = new Set<string>();
  const next: Scene = { ...scene, narration: draft.narration };
  for (const [key] of OPTIONAL) {
    if (key in draft.optional) {
      const value = draft.optional[key]?.trim();
      if (value) {
        next[key] = value;
      } else {
        emptied.add(key);
      }
    }
  }
  if (scene.text) {
    next.text = scene.text.map((item, index) => ({ ...item, content: draft.lines[index] ?? "" }));
  }
  if (draft.question.trim()) {
    next.retention_device = draft.question.trim();
  } else {
    emptied.add("retention_device");
  }
  return Object.fromEntries(Object.entries(next).filter(([key]) => !emptied.has(key))) as Scene;
}

interface Draft {
  narration: string;
  optional: Partial<Record<(typeof OPTIONAL)[number][0], string>>;
  lines: string[];
  question: string;
}

function draftOf(scene: Scene): Draft {
  // Title, label and sublabel belong to scenes that draw them: scroll and steps.
  const drawsLabels = scene.kind === "scroll" || scene.kind === "steps";
  return {
    narration: scene.narration ?? "",
    optional: Object.fromEntries(
      OPTIONAL.filter(([key]) => drawsLabels || key in scene).map(([key]) => [key, scene[key] ?? ""]),
    ),
    lines: (scene.text ?? []).map((item) => item.content ?? ""),
    question: scene.retention_device ?? "",
  };
}

/**
 * One scene of the plan (design doc section 11.2): narration, what is on screen, what is
 * heard, the question it leaves, and its estimated seconds. Edit changes its text fields
 * in place. Everything else about a scene is changed in words or in the raw JSON.
 *
 * On a phone the card shows narration and seconds, and Details opens the rest.
 */
export function SceneCard({
  scene,
  index,
  seconds,
  onSave,
}: {
  scene: Scene;
  index: number;
  seconds: number | undefined;
  onSave: (scene: Scene) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const detailsId = useId();
  const number = index + 1;
  const chips = sceneChips(scene);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) {
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      await onSave(edited(scene, draft));
      setDraft(null);
    } catch (error) {
      setFailure(failureOf(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <article
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-lg border bg-card px-4 py-4 sm:px-4.5",
        draft && "border-info",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <h3
          className={cn(
            "font-sans text-xs font-semibold tracking-[0.06em] uppercase",
            draft ? "text-info" : "text-muted-foreground",
          )}
        >
          {sceneHeading(scene, index)}
        </h3>
        {seconds !== undefined && (
          <p className="shrink-0 font-mono text-xs text-muted-foreground">about {seconds} s</p>
        )}
      </div>

      {draft ? (
        <form onSubmit={(event) => void save(event)} className="flex flex-col gap-3">
          <Field
            label="Narration"
            rows={3}
            value={draft.narration}
            onChange={(narration) => setDraft({ ...draft, narration })}
          />
          {OPTIONAL.filter(([key]) => key in draft.optional).map(([key, label]) => (
            <Field
              key={key}
              label={label}
              value={draft.optional[key] ?? ""}
              onChange={(value) => setDraft({ ...draft, optional: { ...draft.optional, [key]: value } })}
            />
          ))}
          {draft.lines.map((line, position) => (
            <Field
              key={position}
              label={`On-screen line ${position + 1}`}
              value={line}
              onChange={(value) =>
                setDraft({
                  ...draft,
                  lines: draft.lines.map((old, at) => (at === position ? value : old)),
                })
              }
            />
          ))}
          <Field
            label="Question it leaves"
            value={draft.question}
            onChange={(question) => setDraft({ ...draft, question })}
          />
          {failure && <Problems failure={failure} />}
          <div className="flex gap-3">
            <button type="submit" disabled={saving} className={cn(quietAction, "border-info")}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(null);
                setFailure(null);
              }}
              className={quietAction}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="text-[0.9375rem] leading-normal wrap-anywhere">
            {scene.narration?.trim() || <span className="text-muted-foreground">No narration.</span>}
          </p>
          <div id={detailsId} className={cn("flex-col gap-3 sm:flex", open ? "flex" : "hidden")}>
            {chips.length > 0 && (
              <ul className="flex flex-wrap gap-2 text-xs">
                {chips.map((chip, position) => (
                  <li key={position} className="rounded-md bg-raised px-2.5 py-1 wrap-anywhere">
                    {chip}
                  </li>
                ))}
              </ul>
            )}
            {scene.retention_device && (
              <p className="text-[0.8125rem] text-muted-foreground">
                Leaves the viewer asking: {scene.retention_device}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              aria-label={`Edit scene ${number}`}
              onClick={() => setDraft(draftOf(scene))}
              className={quietAction}
            >
              Edit scene
            </button>
            <button
              type="button"
              aria-label={`Details of scene ${number}`}
              aria-expanded={open}
              aria-controls={detailsId}
              onClick={() => setOpen((current) => !current)}
              className={cn(quietAction, "sm:hidden")}
            >
              {open ? "Hide details" : "Details"}
            </button>
          </div>
        </>
      )}
    </article>
  );
}
