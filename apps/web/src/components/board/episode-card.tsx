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

/**
 * One episode on the Board, as in the mockups: title, the progress strip of the pipeline,
 * and one line that says what it is doing or what it needs. A card that waits for the
 * owner has the accent border. Cards are not draggable: only the pipeline moves them.
 */
export function EpisodeCard({ episode }: { episode: EpisodeOut }) {
  const progress = progressOf(episode);
  const status = statusOf(episode);

  return (
    <article
      data-episode-id={episode.id}
      className={cn(
        "flex min-w-0 flex-col gap-2.5 rounded-lg border bg-card p-3.5",
        status.tone === "waiting" && "border-primary",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="line-clamp-2 min-w-0 font-sans text-sm leading-snug font-semibold wrap-anywhere">
          {displayTitle(episode)}
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
    </article>
  );
}
