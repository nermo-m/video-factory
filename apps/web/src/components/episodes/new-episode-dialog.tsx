"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { type FormEvent, useRef, useState } from "react";

import { postEpisode } from "@/api/client";
import { API_NOT_ANSWERING, failureMessage } from "@/lib/api-error";
import { primaryAction, quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { writerText } from "@/lib/writer";

import { useEpisodes } from "./episodes-provider";
import { WriterField } from "./writer-field";

const BOARD = "/";
/** The longest prompt the API takes. */
const IDEA_MAX = 20000;

/** What can be switched on or off for one video, with the words the form uses. */
const SWITCHES = [
  ["research", "Check facts with sources", "Looks facts up on the web before the plan is written."],
  ["captions", "Captions", "Shows the spoken words on screen."],
  ["music", "Music", "Plays a soft music bed under the video."],
  [
    "animate",
    "Animate the pictures",
    "Every picture becomes a moving clip, made on your graphics card. About 6 minutes for each 5 seconds.",
  ],
] as const;
type Switch = (typeof SWITCHES)[number][0];

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
 * New episode (Director mode): one large text area for the whole prompt, who writes
 * the plan, the options that are a choice of this video, and Start. Nothing is forced: the studio follows what
 * is written. A full-screen sheet on a phone, a centred 560 px dialog from tablet
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
  const [options, setOptions] = useState<Record<Switch, boolean>>({
    research: false,
    captions: true,
    music: true,
    animate: true,
  });
  const [writer, setWriter] = useState("");
  const [model, setModel] = useState("");
  const [badModel, setBadModel] = useState(false);
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
    const chosen = writerText(writer, model);
    if (chosen === null) {
      setBadModel(true);
      document.getElementById("new-episode-writer-model")?.focus();
      return;
    }
    setStarting(true);
    setFailure(null);
    let created: string;
    try {
      const result = await postEpisode({
        // No writer is sent when the choice is left to the studio.
        body: { idea: text, options, ...(chosen ? { writer: chosen } : {}), start: true },
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
                Write your video
              </label>
              <textarea
                id="new-episode-idea"
                ref={field}
                rows={9}
                maxLength={IDEA_MAX}
                value={idea}
                onChange={(event) => {
                  setIdea(event.target.value);
                  setMissing(false);
                }}
                aria-invalid={missing || undefined}
                aria-describedby="new-episode-idea-hint"
                placeholder="Scene 1. Dawn. A keeper climbs a steep green hill toward a lighthouse. VO: The keeper climbed the same hill every morning."
                className={cn(
                  "min-h-52 resize-y rounded-lg border bg-raised p-3 text-base placeholder:text-muted-foreground/70 sm:text-sm",
                  missing && "border-danger",
                )}
              />
              <p id="new-episode-idea-hint" className="text-xs text-muted-foreground">
                {missing ? (
                  <span className="font-semibold text-danger">Write your video first.</span>
                ) : (
                  "Write it the way you want it: story, characters, look, scenes, lines, music, length. The studio follows what you write and lists anything it had to add."
                )}
              </p>
            </div>

            <WriterField
              id="new-episode-writer"
              choice={writer}
              typed={model}
              invalid={badModel}
              onChoice={(choice) => {
                setWriter(choice);
                setBadModel(false);
              }}
              onTyped={(typed) => {
                setModel(typed);
                setBadModel(false);
              }}
            />

            <details className="rounded-lg border">
              <summary className="flex min-h-11 cursor-pointer items-center px-3.5 font-semibold">
                Options
              </summary>
              <fieldset className="flex flex-col gap-1 px-3.5 pb-3">
                <legend className="sr-only">Options for this video</legend>
                {SWITCHES.map(([name, label, hint]) => (
                  <label key={name} className="flex min-h-11 cursor-pointer items-center gap-3 py-1.5">
                    <input
                      type="checkbox"
                      checked={options[name]}
                      onChange={(event) => setOptions({ ...options, [name]: event.target.checked })}
                      aria-describedby={`new-episode-${name}-hint`}
                      className="size-4 shrink-0 accent-info"
                    />
                    <span className="flex flex-col">
                      {label}
                      <span id={`new-episode-${name}-hint`} className="text-xs text-muted-foreground">
                        {hint}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
            </details>

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
