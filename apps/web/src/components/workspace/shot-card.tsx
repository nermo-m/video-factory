"use client";

import { type FormEvent, useId, useState } from "react";

import { type ApiFailure, failureOf } from "@/lib/api-error";
import {
  CAMERAS,
  type Character,
  MAX_TEXT_LINES,
  POSITIONS,
  type PlanAsset,
  type ShotDraft,
  cameraLabel,
  draftOfShot,
  editedShot,
} from "@/lib/director";
import { quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { Scene } from "@/lib/workspace";

import { Field, Problems } from "./scene-card";

const selectLook = "h-11 w-full rounded-lg border bg-raised px-3 text-base sm:text-sm";
const smallLabel = "text-xs font-semibold text-muted-foreground";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <p className={smallLabel}>{label}</p>
      <div className="text-[0.875rem] leading-normal wrap-anywhere">{children}</div>
    </div>
  );
}

/**
 * One shot of the plan (Director mode): the spoken line and whose words it is, the text on
 * screen, the seconds, the picture prompt, who is in the picture, the camera move, the
 * motion for the clip, and whether the scene is to move. Every one of them can be edited
 * before anything is generated.
 *
 * On a phone the card shows the line and the seconds, and Details opens the rest.
 */
export function ShotCard({
  scene,
  asset,
  index,
  seconds,
  characters,
  onSave,
}: {
  scene: Scene;
  asset: PlanAsset | undefined;
  index: number;
  seconds: number | undefined;
  characters: Character[];
  onSave: (scene: Scene, asset: PlanAsset) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ShotDraft | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const detailsId = useId();
  const cameraId = useId();
  const secondsId = useId();
  const number = index + 1;
  const visual = (scene.visual ?? {}) as Record<string, unknown>;
  const lines = (scene.text ?? []) as { content?: string; position?: string }[];
  const shown = (asset?.characters ?? [])
    .map((id) => characters.find((character) => character.id === id)?.name)
    .filter((name): name is string => Boolean(name));
  const spoken = scene.narration?.trim();

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || !asset) {
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      const next = editedShot(scene, asset, draft);
      await onSave(next.scene, next.asset);
      setDraft(null);
    } catch (error) {
      setFailure(failureOf(error));
    } finally {
      setSaving(false);
    }
  }

  function setLine(at: number, fields: Partial<ShotDraft["lines"][number]>) {
    if (draft) {
      setDraft({
        ...draft,
        lines: draft.lines.map((old, position) => (position === at ? { ...old, ...fields } : old)),
      });
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
          Scene {number}, shot
        </h3>
        {seconds !== undefined && (
          <p className="shrink-0 font-mono text-xs text-muted-foreground">about {seconds} s</p>
        )}
      </div>

      {draft ? (
        <form onSubmit={(event) => void save(event)} className="flex flex-col gap-3">
          <Field
            label="Spoken line"
            rows={3}
            value={draft.narration}
            onChange={(narration) => setDraft({ ...draft, narration })}
          />
          {draft.lines.map((line, at) => (
            <div key={at} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_9rem]">
              <Field
                label={`On-screen line ${at + 1}`}
                value={line.content}
                onChange={(content) => setLine(at, { content })}
              />
              <div className="flex flex-col gap-1.5">
                <label htmlFor={`${detailsId}-position-${at}`} className={smallLabel}>
                  Position of line {at + 1}
                </label>
                <select
                  id={`${detailsId}-position-${at}`}
                  value={line.position}
                  onChange={(event) => setLine(at, { position: event.target.value })}
                  className={selectLook}
                >
                  {POSITIONS.map(([id, label]) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ))}
          {draft.lines.length < MAX_TEXT_LINES && (
            <div>
              <button
                type="button"
                onClick={() =>
                  setDraft({ ...draft, lines: [...draft.lines, { content: "", position: "bottom" }] })
                }
                className={quietAction}
              >
                Add a line of on-screen text
              </button>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label htmlFor={secondsId} className={smallLabel}>
                Seconds
              </label>
              <input
                id={secondsId}
                type="text"
                inputMode="decimal"
                value={draft.seconds}
                onChange={(event) => setDraft({ ...draft, seconds: event.target.value })}
                aria-describedby={`${secondsId}-hint`}
                className={cn(selectLook, "px-3.5")}
              />
              <p id={`${secondsId}-hint`} className="text-xs text-muted-foreground">
                Leave empty to let the spoken line decide. A line is never cut short.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={cameraId} className={smallLabel}>
                Camera
              </label>
              <select
                id={cameraId}
                value={draft.camera}
                onChange={(event) => setDraft({ ...draft, camera: event.target.value })}
                className={selectLook}
              >
                {CAMERAS.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <Field
            label="Picture"
            rows={7}
            value={draft.prompt}
            onChange={(prompt) => setDraft({ ...draft, prompt })}
          />
          {characters.length > 0 && (
            <fieldset className="flex flex-col gap-2">
              <legend className={cn(smallLabel, "mb-1.5")}>Who is in it</legend>
              <div className="flex flex-wrap gap-2">
                {characters.map((character) => (
                  <label
                    key={character.id}
                    className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg border bg-raised px-3.5 has-checked:border-info"
                  >
                    <input
                      type="checkbox"
                      checked={draft.characters.includes(character.id)}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          characters: event.target.checked
                            ? [...draft.characters, character.id]
                            : draft.characters.filter((id) => id !== character.id),
                        })
                      }
                      className="size-4 accent-info"
                    />
                    {character.name}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          <Field
            label="Motion"
            rows={3}
            value={draft.motion}
            onChange={(motion) => setDraft({ ...draft, motion })}
          />
          <div className="flex flex-col gap-1.5">
            <label className="flex min-h-11 cursor-pointer items-center gap-2.5">
              <input
                type="checkbox"
                checked={draft.clip}
                onChange={(event) => setDraft({ ...draft, clip: event.target.checked })}
                className="size-4 accent-info"
              />
              Make it a moving clip
            </label>
            <p className="text-xs text-muted-foreground">
              Clips arrive with the next step. Until then this scene shows its picture with the
              camera move.
            </p>
          </div>
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
          <div className="flex flex-col gap-1.5">
            <p className="text-[0.9375rem] leading-normal wrap-anywhere">
              {spoken || <span className="text-muted-foreground">No spoken line.</span>}
            </p>
            {spoken && (
              <p className="text-xs text-muted-foreground">
                {scene.narration_from === "studio" ? "Written by the studio" : "Your line"}
              </p>
            )}
          </div>
          <div id={detailsId} className={cn("flex-col gap-3 sm:flex", open ? "flex" : "hidden")}>
            {lines.length > 0 && (
              <Fact label="On-screen text">
                <ul className="flex flex-wrap gap-2 text-xs">
                  {lines.map((line, at) => (
                    <li key={at} className="rounded-md bg-raised px-2.5 py-1 wrap-anywhere">
                      {line.position ?? "bottom"}: {line.content}
                    </li>
                  ))}
                </ul>
              </Fact>
            )}
            <Fact label="Picture">
              {asset?.prompt?.trim() || (
                <span className="text-muted-foreground">This shot has no picture prompt.</span>
              )}
            </Fact>
            {shown.length > 0 && <Fact label="Who is in it">{shown.join(", ")}</Fact>}
            <Fact label="Camera">{cameraLabel(visual.camera as string | undefined)}</Fact>
            {typeof visual.motion === "string" && <Fact label="Motion">{visual.motion}</Fact>}
            {visual.clip === true && (
              <p className="text-[0.8125rem] text-muted-foreground">
                To be a moving clip. Clips arrive with the next step. Until then this scene shows
                its picture with the camera move.
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              aria-label={`Edit scene ${number}`}
              disabled={!asset}
              onClick={() => setDraft(draftOfShot(scene, asset))}
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
