"use client";

import { useId, useState, useSyncExternalStore } from "react";

import type { EpisodeOut } from "@/api/client";
import { type EpisodesState, useEpisodes } from "@/components/episodes/episodes-provider";
import { Banner, EmptyState, PageHeader } from "@/components/page";
import { type ApiState, useApiState } from "@/components/shell/status-strip";
import { type GroupId, episodeCount, groupOf } from "@/lib/episodes";
import { quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";

import { EpisodeCard } from "./episode-card";

export function BoardBanner({ state }: { state: ApiState }) {
  if (state.kind === "unreachable") {
    return (
      <Banner>
        The API is not answering. Check that the stack is running with <code>docker compose ps</code>,
        then reload this page.
      </Banner>
    );
  }
  if (state.kind !== "ready") {
    return null;
  }
  if (state.health.status !== "ok") {
    const failed = [state.health.checks.database, state.health.checks.storage]
      .map((check) => check.message)
      .filter(Boolean)
      .join(" ");
    return <Banner>The studio cannot work right now. {failed}</Banner>;
  }
  if (state.health.demo_mode) {
    return (
      <Banner>
        Demo mode is on. Models, images and clips are simulated with bundled samples, and nothing is
        sent to a paid service.
      </Banner>
    );
  }
  if (state.health.checks.comfyui.status === "offline") {
    return (
      <Banner>
        ComfyUI is not running, so clips cannot be generated. Start ComfyUI on this PC. Everything
        that does not need the GPU stays usable.
      </Banner>
    );
  }
  return null;
}

const PHONE = "(max-width: 639.98px)";

function watchPhone(onChange: () => void) {
  const query = window.matchMedia(PHONE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** True under 640 px. Only behaviour depends on it: the layout itself is decided in CSS. */
function useIsPhone(): boolean {
  return useSyncExternalStore(
    watchPhone,
    () => window.matchMedia(PHONE).matches,
    () => false,
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

/**
 * One status group. From tablet up it is a column with a plain heading. On a phone the
 * heading is a button that folds the group away (design doc section 11.5).
 */
function Group({
  id,
  label,
  episodes,
  openOnPhone,
  accent = false,
  className,
}: {
  id: GroupId | "in-progress";
  label: string;
  episodes: EpisodeOut[];
  openOnPhone: boolean;
  accent?: boolean;
  className?: string;
}) {
  const phone = useIsPhone();
  const [open, setOpen] = useState(openOnPhone);
  const listId = useId();
  const title = (
    <span>
      {label}{" "}
      <span className="ml-1 font-mono text-xs font-medium text-muted-foreground">{episodes.length}</span>
    </span>
  );

  return (
    <section data-testid={`group-${id}`} className={cn("min-w-0 flex-col gap-3", className)}>
      <h2
        className={cn(
          "font-sans text-[0.8125rem] font-semibold",
          accent ? "text-primary" : "text-muted-foreground",
        )}
      >
        {phone ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((current) => !current)}
            className={cn(
              "flex min-h-12 w-full items-center justify-between gap-3 rounded-lg text-left",
              !open && "border px-3.5",
            )}
          >
            {title}
            <ChevronIcon open={open} />
          </button>
        ) : (
          title
        )}
      </h2>
      <ul id={listId} className={cn("flex-col gap-3 sm:flex", open ? "flex" : "hidden")}>
        {episodes.length === 0 && (
          <li className="rounded-lg border border-dashed px-3.5 py-3 text-xs text-muted-foreground">
            {id === "needs-you" ? "Nothing is waiting for you." : "No episodes here."}
          </li>
        )}
        {episodes.map((episode) => (
          <li key={episode.id} className="min-w-0">
            <EpisodeCard episode={episode} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The groups of the mockups: Needs you, Planning, Producing and Finished.
 *
 * - 1024 px and up: four columns side by side.
 * - 640 to 1023 px: two columns, Needs you and everything else.
 * - under 640 px: one column. Needs you is first and open, Finished starts folded.
 *
 * Below 1024 px Planning and Producing are shown as one group, In progress.
 */
function Groups({ episodes }: { episodes: EpisodeOut[] }) {
  const by = (group: GroupId) => episodes.filter((episode) => groupOf(episode) === group);
  const planning = by("planning");
  const producing = by("producing");
  const inProgress = episodes.filter((episode) =>
    ["planning", "producing"].includes(groupOf(episode)),
  );

  return (
    <div data-testid="board-groups" className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Group id="needs-you" label="Needs you" episodes={by("needs-you")} openOnPhone accent className="flex" />
      <div className="flex min-w-0 flex-col gap-4 lg:contents">
        <Group
          id="in-progress"
          label="In progress"
          episodes={inProgress}
          openOnPhone
          className="flex lg:hidden"
        />
        <Group id="planning" label="Planning" episodes={planning} openOnPhone className="hidden lg:flex" />
        <Group id="producing" label="Producing" episodes={producing} openOnPhone className="hidden lg:flex" />
        <Group id="finished" label="Finished" episodes={by("finished")} openOnPhone={false} className="flex" />
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div data-testid="board-loading" aria-busy="true" className="flex flex-col gap-4">
      <p className="text-muted-foreground">Loading the episodes…</p>
      <div aria-hidden="true" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((column) => (
          <div
            key={column}
            className={cn("flex-col gap-3", column > 1 ? "hidden lg:flex" : column === 1 ? "hidden sm:flex" : "flex")}
          >
            <div className="h-4 w-24 animate-pulse rounded bg-raised" />
            <div className="h-22 animate-pulse rounded-lg border bg-card" />
            {column < 2 && <div className="h-22 animate-pulse rounded-lg border bg-card" />}
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadFailed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section
      role="alert"
      data-testid="board-error"
      className="flex max-w-xl flex-col items-start gap-3 rounded-lg border border-danger/50 bg-chip-failed p-5 sm:p-6"
    >
      <h2 className="text-lg font-semibold">The episodes could not be loaded</h2>
      <p>{message}</p>
      <button type="button" onClick={onRetry} className={quietAction}>
        Try again
      </button>
    </section>
  );
}

export interface BoardViewProps {
  api: ApiState;
  episodes: EpisodesState;
  onRetry: () => void;
  onShowMore: () => Promise<void>;
}

/** The Board for a given state, without any requests of its own. */
export function BoardView({ api, episodes, onRetry, onShowMore }: BoardViewProps) {
  const [loadingMore, setLoadingMore] = useState(false);

  async function showMore() {
    setLoadingMore(true);
    try {
      await onShowMore();
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Board"
        note={episodes.kind === "ready" ? episodeCount(episodes.total) : undefined}
      />
      <BoardBanner state={api} />

      {episodes.kind === "loading" && <Loading />}
      {episodes.kind === "error" && <LoadFailed message={episodes.message} onRetry={onRetry} />}
      {episodes.kind === "ready" && episodes.stale && (
        <p
          data-testid="board-stale"
          className="rounded-lg border border-warning/50 bg-chip-out-of-date px-4 py-3"
        >
          The Board could not be refreshed, so it may be out of date. It keeps trying.
        </p>
      )}
      {episodes.kind === "ready" && episodes.total === 0 && (
        <EmptyState title="No episodes yet">
          An episode starts as one idea and ends as a finished vertical video. Each one appears here
          with its current step, and anything waiting for you comes first. Start with New episode.
        </EmptyState>
      )}
      {episodes.kind === "ready" && episodes.total > 0 && <Groups episodes={episodes.episodes} />}
      {episodes.kind === "ready" && episodes.episodes.length < episodes.total && (
        <div className="flex flex-wrap items-center gap-4">
          <p className="text-muted-foreground">
            Showing {episodes.episodes.length} of {episodeCount(episodes.total)}
          </p>
          <button type="button" onClick={() => void showMore()} disabled={loadingMore} className={quietAction}>
            {loadingMore ? "Loading…" : "Show more"}
          </button>
        </div>
      )}
    </div>
  );
}

/** The Board, wired to the API. */
export function Board() {
  const api = useApiState();
  const { state, retry, showMore } = useEpisodes();
  return <BoardView api={api} episodes={state} onRetry={retry} onShowMore={showMore} />;
}
