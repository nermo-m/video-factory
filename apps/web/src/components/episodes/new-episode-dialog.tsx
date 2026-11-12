"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { type FormEvent, useRef, useState } from "react";

import { postEpisode } from "@/api/client";
import { API_NOT_ANSWERING, failureMessage } from "@/lib/api-error";
import { primaryAction, quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";

import { useEpisodes } from "./episodes-provider";

const BOARD = "/";
const LENGTHS = [45, 60] as const;
/** The longest idea the API takes. */
const IDEA_MAX = 4000;

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      aria-hidden="true"
      className="size-5"
    >
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

/**
 * New episode (design doc sections 11.2 and 11.5): one text area for the idea, 45 or 60
 * seconds, and Start. A full-screen sheet on a phone, a centred 560 px dialog from tablet
 * up. It is open whenever the address is /episodes/new, so the New episode buttons are
 * plain links, the Back button closes it, and closing it leads to the Board.
 *
 * Start creates the episode, begins planning at once and opens the episode's workspace.
 * Planning stops by itself at the plan gate, before anything is produced.
 */
export function NewEpisodeDialog() {
  const router = useRouter();
  const { refresh } = useEpisodes();
  const [idea, setIdea] = useState("");
  const [length, setLength] = useState<(typeof LENGTHS)[number]>(45);
  const [missing, setMissing] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);

  async function start(event: FormEvent) {
    event.preventDefault();
    const text = idea.trim();
    if (!text) {
      setMissing(true);
      field.current?.focus();
      return;
    }
    setStarting(true);
    setFailure(null);
    let created: string;
    try {
      const result = await postEpisode({
        body: { idea: text, target_duration_s: length, start: true },
      });
      if (!result.data) {
        setFailure(
          failureMessage(result, "The episode could not be started. Check the idea and press Start again."),
        );
        setStarting(false);
        return;
      }
      created = result.data.id;
    } catch {
      setFailure(API_NOT_ANSWERING);
      setStarting(false);
      return;
    }
    // Start stays disabled from here on: the episode exists, and its workspace is next.
    void refresh();
    router.push(`/episodes/${created}`);
  }

  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) {
          router.push(BOARD);
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            field.current?.focus();
          }}
          className="fixed inset-0 z-50 flex flex-col overflow-y-auto bg-surface sm:inset-auto sm:top-1/2 sm:left-1/2 sm:max-h-[calc(100dvh-2rem)] sm:w-140 sm:max-w-[calc(100vw-2rem)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl sm:border sm:shadow-[0_18px_48px_rgb(0_0_0/0.55)]"
        >
          <form onSubmit={(event) => void start(event)} noValidate className="flex grow flex-col gap-5 p-4 sm:p-6">
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-1.5">
                <Dialog.Title asChild>
                  <h1 className="text-[1.375rem] font-bold">New episode</h1>
                </Dialog.Title>
                <Dialog.Description className="text-muted-foreground">
                  Planning starts at once and stops for your approval before anything is produced.
                </Dialog.Description>
              </div>
              <Link
                href={BOARD}
                aria-label="Close"
                className="-mt-1.5 -mr-1.5 flex size-11 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-raised hover:text-foreground"
              >
                <CloseIcon />
              </Link>
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="new-episode-idea" className="font-semibold">
                Idea
              </label>
              <textarea
                id="new-episode-idea"
                ref={field}
                rows={5}
                maxLength={IDEA_MAX}
                value={idea}
                onChange={(event) => {
                  setIdea(event.target.value);
                  setMissing(false);
                }}
                aria-invalid={missing || undefined}
                aria-describedby="new-episode-idea-hint"
                placeholder="A lighthouse keeper who climbs the stairs every night, one small step at a time."
                className={cn(
                  "min-h-32 resize-y rounded-lg border bg-raised p-3 text-base placeholder:text-muted-foreground/70 sm:text-sm",
                  missing && "border-danger",
                )}
              />
              <p id="new-episode-idea-hint" className="text-xs text-muted-foreground">
                {missing ? (
                  <span className="font-semibold text-danger">Write the idea first.</span>
                ) : (
                  "One or two sentences are enough."
                )}
              </p>
            </div>

            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 font-semibold">Length</legend>
              <div className="grid grid-cols-2 gap-2">
                {LENGTHS.map((seconds) => (
                  <label
                    key={seconds}
                    className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg border bg-raised px-3.5 has-checked:border-info"
                  >
                    <input
                      type="radio"
                      name="length"
                      value={seconds}
                      checked={length === seconds}
                      onChange={() => setLength(seconds)}
                      className="size-4 accent-info"
                    />
                    {seconds} seconds
                  </label>
                ))}
              </div>
            </fieldset>

            {failure && (
              <p role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
                {failure}
              </p>
            )}

            <div className="mt-auto flex gap-3 pt-1 sm:justify-end">
              <Link href={BOARD} className={quietAction}>
                Cancel
              </Link>
              <button type="submit" disabled={starting} className={cn(primaryAction, "grow sm:grow-0")}>
                {starting ? "Starting…" : "Start"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
