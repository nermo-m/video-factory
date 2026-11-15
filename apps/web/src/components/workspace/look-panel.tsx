"use client";

import { type FormEvent, useState } from "react";

import { type ApiFailure, failureOf } from "@/lib/api-error";
import type { Character } from "@/lib/director";
import { quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";

import { Field, Problems } from "./scene-card";

interface Draft {
  style: string;
  characters: Character[];
}

/**
 * The look and the characters of a plan of shots (Director mode). Each is written once and
 * used in every picture: the style goes in front of every picture prompt, and a
 * character's description goes into every picture that shows the character. So editing
 * one description here changes all of that character's pictures.
 */
export function LookPanel({
  style,
  characters,
  onSave,
}: {
  style: string;
  characters: Character[];
  onSave: (style: string, characters: Character[]) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) {
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      await onSave(draft.style, draft.characters);
      setDraft(null);
    } catch (error) {
      setFailure(failureOf(error));
    } finally {
      setSaving(false);
    }
  }

  function change(index: number, fields: Partial<Character>) {
    if (!draft) {
      return;
    }
    setDraft({
      ...draft,
      characters: draft.characters.map((old, at) => (at === index ? { ...old, ...fields } : old)),
    });
  }

  return (
    <section
      aria-labelledby="look-heading"
      data-testid="look-panel"
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-lg border bg-card px-4 py-4 sm:px-4.5",
        draft && "border-info",
      )}
    >
      <div className="flex flex-col gap-1">
        <h2
          id="look-heading"
          className={cn(
            "font-sans text-xs font-semibold tracking-[0.06em] uppercase",
            draft ? "text-info" : "text-muted-foreground",
          )}
        >
          Look and characters
        </h2>
        <p className="text-[0.8125rem] text-muted-foreground">
          Described once, used in every picture that shows them.
        </p>
      </div>

      {draft ? (
        <form onSubmit={(event) => void save(event)} className="flex flex-col gap-3">
          <Field
            label="Style"
            rows={3}
            value={draft.style}
            onChange={(value) => setDraft({ ...draft, style: value })}
          />
          {draft.characters.map((character, index) => (
            <fieldset key={character.id} className="flex flex-col gap-3 rounded-md border p-3">
              <legend className="px-1 text-xs font-semibold text-muted-foreground">
                Character {index + 1}
              </legend>
              <Field
                label={`Name of character ${index + 1}`}
                value={character.name}
                onChange={(name) => change(index, { name })}
              />
              <Field
                label={`Description of character ${index + 1}`}
                rows={4}
                value={character.description}
                onChange={(description) => change(index, { description })}
              />
            </fieldset>
          ))}
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
          <div className="flex flex-col gap-1">
            <p className="text-xs font-semibold text-muted-foreground">Style</p>
            <p className="text-[0.9375rem] leading-normal wrap-anywhere">
              {style.trim() || <span className="text-muted-foreground">No style is set.</span>}
            </p>
          </div>
          {characters.length === 0 ? (
            <p className="text-[0.8125rem] text-muted-foreground">This video has no characters.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {characters.map((character) => (
                <li key={character.id} className="rounded-md bg-raised px-3 py-2.5 wrap-anywhere">
                  <p className="text-[0.9375rem] font-semibold">{character.name}</p>
                  <p className="mt-1 text-[0.875rem] leading-normal">{character.description}</p>
                </li>
              ))}
            </ul>
          )}
          <div>
            <button
              type="button"
              onClick={() => setDraft({ style, characters: characters.map((item) => ({ ...item })) })}
              className={quietAction}
            >
              Edit look and characters
            </button>
          </div>
        </>
      )}
    </section>
  );
}
