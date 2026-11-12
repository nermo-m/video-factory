"use client";

import Link from "next/link";
import { type KeyboardEvent, useId, useRef, useState } from "react";

import { type EpisodeDetail, postEpisodeAdvance } from "@/api/client";
import { failureOf, unwrap } from "@/lib/api-error";
import { displayTitle } from "@/lib/episodes";
import { primaryAction, quietAction } from "@/lib/styles";
import { useIsDesktop } from "@/lib/use-media";
import { cn } from "@/lib/utils";
import { STEP_WORDS, type Spec, type StepState, chipOf, pipelineOf } from "@/lib/workspace";

import { GateBar } from "./gate-bar";
import { PlanTab } from "./plan-tab";
import { type WorkspaceData, useWorkspace } from "./use-workspace";

function StepIcon({ state }: { state: StepState }) {
  const common = {
    viewBox: "0 0 24 24",
    fill: "none",
    strokeWidth: 3,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    className: "size-4 shrink-0",
  };
  if (state === "done") {
    return (
      <svg {...common} stroke="var(--success)">
        <path d="M5 12l5 5 9-10" />
      </svg>
    );
  }
  if (state === "waiting") {
    return (
      <svg {...common} stroke="currentColor">
        <path d="M12 6v7M12 18h.01" />
      </svg>
    );
  }
  if (state === "working") {
    return (
      <svg {...common} stroke="currentColor" className="size-4 shrink-0 animate-spin">
        <path d="M12 3a9 9 0 1 0 9 9" />
      </svg>
    );
  }
  return <span aria-hidden="true" className="size-4 shrink-0 rounded-full border-2" />;
}

/** The pipeline: a column beside the content on desktop, a row that scrolls above it below. */
function Pipeline({ episode }: { episode: EpisodeDetail }) {
  // As a row it scrolls sideways, so the keyboard must be able to reach and scroll it.
  const column = useIsDesktop();
  return (
    <ol
      aria-label="Pipeline"
      tabIndex={column ? undefined : 0}
      className="relative flex min-w-0 gap-1 overflow-x-auto pb-1 text-sm lg:flex-col lg:overflow-visible lg:pb-0"
    >
      {pipelineOf(episode).map((step) => (
        <li
          key={step.label}
          aria-current={step.state === "waiting" || step.state === "working" ? "step" : undefined}
          className={cn(
            "flex h-10 shrink-0 items-center gap-2.5 rounded-lg px-2.5 text-muted-foreground",
            step.state === "waiting" && "bg-chip-needs-you font-semibold text-primary",
            step.state === "working" && "bg-chip-working font-semibold text-info",
          )}
        >
          <StepIcon state={step.state} />
          {step.label}
          <span className="sr-only">, {STEP_WORDS[step.state]}</span>
        </li>
      ))}
    </ol>
  );
}

const TABS = ["Plan", "Assets", "Voice", "Render", "Export"] as const;
type Tab = (typeof TABS)[number];

const LATER: Record<Exclude<Tab, "Plan">, string> = {
  Assets: "The pictures and clips of this episode, with accept, regenerate and upload. They arrive with milestone M3.",
  Voice: "The narration of each scene, to play and to record again. It arrives with a later milestone.",
  Render: "The draft video, its contact sheet and its quality checks. They arrive with a later milestone.",
  Export: "Title, description, hashtags and the export pack. They arrive with milestone M4.",
};

function PlanPending({ episode, reload }: { episode: EpisodeDetail; reload: () => Promise<void> }) {
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setFailure(null);
    try {
      unwrap(
        await postEpisodeAdvance({ path: { episode_id: episode.id } }),
        "Planning could not be started. Try again.",
      );
      await reload();
    } catch (error) {
      setFailure(failureOf(error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-testid="plan-pending" className="flex max-w-xl flex-col items-start gap-3 rounded-lg border bg-card p-5 sm:p-6">
      {episode.state === "idea" ? (
        <>
          <h2 className="text-lg font-semibold">Planning has not started</h2>
          <p className="text-muted-foreground">
            Planning writes the brief, checks sources, writes the script and directs the scenes. It
            stops for your approval before anything is produced.
          </p>
          <button type="button" onClick={() => void start()} disabled={busy} className={primaryAction}>
            Start planning
          </button>
          {failure && (
            <p role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
              {failure}
            </p>
          )}
        </>
      ) : (
        <>
          <h2 className="text-lg font-semibold">The plan is being written</h2>
          <p className="text-muted-foreground">
            Brief, research, script and direction run one after another, and the pipeline shows
            where it is. The plan appears here by itself when it is ready.
          </p>
        </>
      )}
    </section>
  );
}

function Tabs({ data, reload }: { data: WorkspaceData; reload: () => Promise<void> }) {
  const id = useId();
  const [tab, setTab] = useState<Tab>("Plan");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: KeyboardEvent, index: number) {
    const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    const target =
      event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : move === undefined ? null : (index + move + TABS.length) % TABS.length;
    if (target === null) {
      return;
    }
    event.preventDefault();
    setTab(TABS[target] ?? "Plan");
    buttons.current[target]?.focus();
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div
        role="tablist"
        aria-label="Episode"
        className="flex gap-1 overflow-x-auto rounded-xl bg-surface p-1 sm:rounded-none sm:border-b sm:bg-transparent sm:p-0"
      >
        {TABS.map((name, index) => (
          <button
            key={name}
            ref={(element) => {
              buttons.current[index] = element;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${name}`}
            aria-selected={tab === name}
            aria-controls={`${id}-panel-${name}`}
            tabIndex={tab === name ? 0 : -1}
            onClick={() => setTab(name)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "h-11 min-w-11 shrink-0 grow rounded-lg px-4 text-sm font-medium text-muted-foreground hover:text-foreground sm:grow-0 sm:rounded-none sm:border-b-2 sm:border-transparent",
              tab === name && "bg-raised font-semibold text-foreground sm:border-primary sm:bg-transparent",
            )}
          >
            {name}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`${id}-panel-${tab}`} aria-labelledby={`${id}-tab-${tab}`} className="flex min-w-0 flex-col gap-4">
        {tab !== "Plan" ? (
          <section className="flex max-w-xl flex-col gap-3 rounded-lg border bg-card p-5 sm:p-6">
            <h2 className="text-lg font-semibold">Not built yet</h2>
            <p className="text-muted-foreground">{LATER[tab]}</p>
          </section>
        ) : data.spec && data.plan ? (
          <PlanTab episodeId={data.episode.id} spec={data.spec} plan={data.plan} reload={reload} />
        ) : (
          <PlanPending episode={data.episode} reload={reload} />
        )}
        <GateBar episode={data.episode} reload={reload} />
      </div>
    </div>
  );
}

function BackIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-5.5">
      <path d="M15 5l-7 7 7 7" />
    </svg>
  );
}

function Ready({ data, reload }: { data: WorkspaceData; reload: () => Promise<void> }) {
  const { episode, spec } = data;
  const title = displayTitle(episode);
  const chip = chipOf(episode);
  const scenes = (spec?.spec as Spec | undefined)?.scenes?.length;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-2">
        <nav aria-label="Breadcrumb" className="hidden text-[0.8125rem] text-muted-foreground sm:block">
          <ol className="flex flex-wrap items-center gap-x-2">
            <li>
              <Link href="/" className="inline-flex min-h-11 min-w-11 items-center hover:text-foreground">
                Board
              </Link>
            </li>
            <li aria-hidden="true">/</li>
            <li className="line-clamp-1 max-w-[40ch] wrap-anywhere">{title}</li>
            <li aria-hidden="true">/</li>
            <li aria-current="page">Plan</li>
          </ol>
        </nav>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Link
            href="/"
            aria-label="Back to the Board"
            className="-ml-2.5 flex size-11 shrink-0 items-center justify-center rounded-lg hover:bg-raised sm:hidden"
          >
            <BackIcon />
          </Link>
          <h1 className="line-clamp-3 min-w-0 text-[1.375rem] font-bold wrap-anywhere sm:text-[1.75rem]">{title}</h1>
          <span
            data-testid="episode-status"
            className={cn(
              "inline-flex h-6.5 shrink-0 items-center rounded-full px-2.5 text-xs font-semibold",
              chip.waiting ? "bg-chip-needs-you text-primary" : episode.state === "done" ? "bg-chip-finished text-success" : "bg-chip-working text-info",
            )}
          >
            {chip.label}
          </span>
          <span className="text-[0.8125rem] text-muted-foreground">
            {episode.target_duration_s} seconds{scenes ? `, ${scenes} ${scenes === 1 ? "scene" : "scenes"}` : ""}
          </span>
        </div>
      </header>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[11.5rem_minmax(0,1fr)] lg:gap-6 2xl:grid-cols-[13.75rem_minmax(0,55rem)_20rem]">
        <Pipeline episode={episode} />
        <Tabs data={data} reload={reload} />
        <aside aria-label="Preview" className="hidden flex-col gap-3 2xl:flex">
          <h2 className="font-sans text-xs font-semibold tracking-[0.06em] text-muted-foreground uppercase">Preview</h2>
          <div className="flex aspect-9/16 items-center justify-center rounded-[0.875rem] border bg-surface p-6 text-center text-[0.8125rem] text-muted-foreground">
            The video appears here after the Render step.
          </div>
        </aside>
      </div>
    </div>
  );
}

/** The episode workspace at /episodes/{id} (design doc sections 11.2 and 11.5). */
export function Workspace({ episodeId }: { episodeId: string }) {
  const { state, reload, retry } = useWorkspace(episodeId);

  if (state.kind === "loading") {
    return (
      <div data-testid="workspace-loading" aria-busy="true" className="flex flex-col gap-4">
        <p className="text-muted-foreground">Loading the episode…</p>
        <div aria-hidden="true" className="flex flex-col gap-3">
          <div className="h-8 w-72 max-w-full animate-pulse rounded bg-raised" />
          <div className="h-28 animate-pulse rounded-lg border bg-card" />
          <div className="h-28 animate-pulse rounded-lg border bg-card" />
        </div>
      </div>
    );
  }
  if (state.kind === "missing") {
    return (
      <section className="flex max-w-xl flex-col items-start gap-3 rounded-lg border bg-card p-5 sm:p-6">
        <h1 className="text-lg font-semibold">This episode does not exist</h1>
        <p className="text-muted-foreground">The address may be mistyped. Every episode is on the Board.</p>
        <Link href="/" className={quietAction}>
          Back to the Board
        </Link>
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section
        role="alert"
        data-testid="workspace-error"
        className="flex max-w-xl flex-col items-start gap-3 rounded-lg border border-danger/50 bg-chip-failed p-5 sm:p-6"
      >
        <h1 className="text-lg font-semibold">The episode could not be loaded</h1>
        <p>{state.message}</p>
        <button type="button" onClick={retry} className={quietAction}>
          Try again
        </button>
      </section>
    );
  }
  return <Ready data={state} reload={reload} />;
}
