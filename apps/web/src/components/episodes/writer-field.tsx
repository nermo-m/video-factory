"use client";

import { needsModel, WRITERS } from "@/lib/writer";
import { cn } from "@/lib/utils";

const control = "min-h-11 w-full rounded-lg border bg-raised px-3 text-base sm:text-sm";

/**
 * Who writes the plan: a list of the models of the owner's two plans, and a box for the
 * name of another model. `keep` adds a first choice that leaves the video's writer as it
 * is, for a plan that is sent back.
 */
export function WriterField({
  id,
  choice,
  typed,
  invalid,
  keep,
  onChoice,
  onTyped,
}: {
  id: string;
  choice: string;
  typed: string;
  invalid: boolean;
  keep?: string;
  onChoice: (choice: string) => void;
  onTyped: (typed: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="font-semibold">
        Plan written by
      </label>
      <select id={id} value={choice} onChange={(event) => onChoice(event.target.value)} className={control}>
        {keep !== undefined && <option value="keep">{keep}</option>}
        {WRITERS.map(([value, words]) => (
          <option key={value} value={value}>
            {words}
          </option>
        ))}
      </select>
      {needsModel(choice) && (
        <>
          <label htmlFor={`${id}-model`} className="text-sm">
            Model name
          </label>
          <input
            id={`${id}-model`}
            value={typed}
            maxLength={80}
            onChange={(event) => onTyped(event.target.value)}
            aria-invalid={invalid || undefined}
            aria-describedby={`${id}-hint`}
            autoComplete="off"
            spellCheck={false}
            className={cn(control, invalid && "border-danger")}
          />
        </>
      )}
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        {invalid ? (
          <span className="font-semibold text-danger">
            Type the model&apos;s name the way its tool takes it: letters, digits, dots and dashes.
          </span>
        ) : (
          "It runs on your own Claude or ChatGPT plan. The pictures are always made by ChatGPT."
        )}
      </p>
    </div>
  );
}
