import Link from "next/link";

import type { EpisodeOut } from "@/api/client";
import {
  type StatusTone,
  type StepTone,
  displayTitle,
  isOutOfDate,
  progressOf,
  statusOf,
} from "@/lib/episodes";
import { cn } from "@/lib/utils";

const STEP_COLOUR: Record<StepTone, string> = {
  done: "bg-success",
  working: "bg-info",
  waiting: "bg-primary",
  todo: "bg-border",
};

const STATUS_COLOUR: Record<StatusTone, string> = {
  waiting: "font-semibold text-primary",
  working: "text-info",
  finished: "font-semibold text-success",
  idle: "text-muted-foreground",
};

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={3}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="size-3 shrink-0"
    >
      <path d="M5 12l5 5 9-10" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="size-4 shrink-0"
    >
      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M9 7V4h6v3" />
    </svg>
  );
}

export interface EpisodeCardProps {
  episode: EpisodeOut;
  /** Asks to delete this video. Without it the card has no Delete button. */
  onDelete?: () => void;
  /** While the owner is selecting, the card is a choice and no longer a link. */
  selecting?: boolean;
  selected?: boolean;
  onToggle?: () => void;
}

/**
 * One episode on the Board, as in the mockups: title, the progress strip of the pipeline,
 * and one line that says what it is doing or what it needs. A card that waits for the
 * owner has the accent border. The card opens the episode's workspace. Cards are not
 * draggable: only the pipeline moves them. Delete sits beside the link, not inside it.
 */
export function EpisodeCard({
  episode,
  onDelete,
  selecting = false,
  selected = false,
  onToggle,
}: EpisodeCardProps) {
  const progress = progressOf(episode);
  const status = statusOf(episode);
  const title = displayTitle(episode);
  const look = cn(
    "flex min-w-0 flex-col gap-2.5 rounded-lg border bg-card p-3.5 hover:bg-raised",
    status.tone === "waiting" && "border-primary",
    selecting && selected && "border-primary bg-raised",
  );
  const body = (
    <>
      <div className={cn("flex items-start justify-between gap-2", (onDelete || selecting) && "pr-8")}>
        <h3 className="line-clamp-2 min-w-0 font-sans text-sm leading-snug font-semibold wrap-anywhere">
          {title}
        </h3>
        {isOutOfDate(episode) && (
          <span className="shrink-0 rounded-full bg-chip-out-of-date px-2 py-0.5 text-[0.6875rem] font-semibold text-warning">
            Out of date
          </span>
        )}
      </div>
      <div role="img" aria-label={progress.label} className="flex gap-1">
        {progress.tones.map((tone, index) => (
          <span key={index} className={cn("h-1 grow rounded-full", STEP_COLOUR[tone])} />
        ))}
      </div>
      <p className={cn("flex items-center gap-1.5 text-xs", STATUS_COLOUR[status.tone])}>
        {status.tone === "finished" && <CheckIcon />}
        {status.label}
      </p>
    </>
  );

  return (
    <article data-episode-id={episode.id} className="relative min-w-0">
      {selecting ? (
        <label className={cn(look, "cursor-pointer")}>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={title}
            className="absolute top-3.5 right-3.5 size-5 accent-primary"
          />
          {body}
        </label>
      ) : (
        <>
          <Link href={`/episodes/${episode.id}`} className={look}>
            {body}
          </Link>
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              aria-label={`Delete "${title}"`}
              title="Delete"
              className="absolute top-0 right-0 flex size-11 items-center justify-center rounded-lg text-muted-foreground hover:text-danger"
            >
              <TrashIcon />
            </button>
          )}
        </>
      )}
    </article>
  );
}
