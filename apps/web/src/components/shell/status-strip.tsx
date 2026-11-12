"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { type HealthResponse, getHealth } from "@/api/client";
import { useEpisodes } from "@/components/episodes/episodes-provider";
import { useProviders } from "@/components/providers/providers-provider";
import { warningOf } from "@/lib/providers";
import { cn } from "@/lib/utils";

import { BellIcon, SpinnerIcon } from "./nav-items";

const POLL_MS = 10_000;

export type ApiState =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse }
  | { kind: "unreachable" };

/** Reads /health now and every few seconds. Polling pauses while the tab is hidden. */
export function useApiState(): ApiState {
  const [state, setState] = useState<ApiState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      if (document.hidden) {
        return;
      }
      try {
        // A 503 still carries the health report: the database or storage is down.
        const { data, error } = await getHealth();
        const health = data ?? (error && "checks" in error ? (error as HealthResponse) : undefined);
        if (!cancelled) {
          setState(health ? { kind: "ready", health } : { kind: "unreachable" });
        }
      } catch {
        if (!cancelled) {
          setState({ kind: "unreachable" });
        }
      }
    }

    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  return state;
}

interface GpuStatus {
  tone: "success" | "danger" | "muted";
  label: string;
}

function gpuStatus(state: ApiState): GpuStatus {
  if (state.kind === "loading") {
    return { tone: "muted", label: "Checking" };
  }
  if (state.kind === "unreachable" || state.health.status !== "ok") {
    return { tone: "danger", label: "API offline" };
  }
  switch (state.health.checks.comfyui.status) {
    case "ok":
      return { tone: "success", label: "GPU ready" };
    case "not_needed":
      return { tone: "muted", label: "GPU not needed" };
    default:
      return { tone: "danger", label: "GPU offline" };
  }
}

const DOT_TONE = { success: "bg-success", danger: "bg-danger", muted: "bg-muted-foreground" };

export interface StatusStripViewProps {
  state: ApiState;
  runningJobs: number;
  waitingForOwner: number;
  /** Set while a provider is near budget, paused or limited. */
  providerWarning?: { label: string; severe: boolean } | null;
}

function WarningIcon() {
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
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

/**
 * The slim strip at the top of every screen (design doc section 11.5): demo mode badge,
 * GPU status, running jobs (opens Jobs) and items waiting for the owner. On a phone it
 * shows icons and counts only. Status is never shown by colour alone.
 */
export function StatusStripView({
  state,
  runningJobs,
  waitingForOwner,
  providerWarning = null,
}: StatusStripViewProps) {
  const gpu = gpuStatus(state);
  const demoMode = state.kind === "ready" && state.health.demo_mode;
  const jobsLabel =
    runningJobs === 0
      ? "No jobs running"
      : `${runningJobs} ${runningJobs === 1 ? "job" : "jobs"} running`;
  const waitingLabel = waitingForOwner === 0 ? "Nothing waiting" : `${waitingForOwner} waiting for you`;

  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex h-13 items-center border-b bg-background text-xs text-muted-foreground sm:gap-4 sm:px-6",
        // With the warning there is one more item, so a phone gets tighter spacing.
        providerWarning ? "gap-1.5 px-3" : "gap-3 px-4",
      )}
    >
      <Link
        href="/"
        className="flex min-h-11 items-center font-heading text-base font-bold text-foreground min-[375px]:whitespace-nowrap"
      >
        Video Factory
      </Link>
      <div className="grow" />

      <div aria-live="polite" className="flex items-center gap-3 sm:gap-4">
        {demoMode && (
          <span
            data-testid="demo-badge"
            className="inline-flex h-6.5 items-center rounded-full bg-chip-working px-2.5 font-semibold text-info"
          >
            Demo<span className="sr-only sm:not-sr-only">&nbsp;mode</span>
          </span>
        )}
        <span data-testid="gpu-status" className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className={cn("size-2 rounded-full", DOT_TONE[gpu.tone])} />
          <span className="sr-only sm:not-sr-only">{gpu.label}</span>
        </span>
      </div>

      {providerWarning && (
        <Link
          href="/settings/usage"
          data-testid="provider-warning"
          className="inline-flex min-h-11 min-w-11 items-center justify-center"
        >
          <span
            className={cn(
              "inline-flex h-6.5 items-center gap-1.5 rounded-full px-2.5 font-semibold",
              providerWarning.severe ? "bg-chip-failed text-danger" : "bg-chip-out-of-date text-warning",
            )}
          >
            <WarningIcon />
            <span className="sr-only sm:not-sr-only">{providerWarning.label}</span>
          </span>
        </Link>
      )}

      <Link
        href="/jobs"
        data-testid="jobs-status"
        className={cn(
          "inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 hover:text-foreground",
          runningJobs > 0 && "text-info",
        )}
      >
        <span className={cn(runningJobs > 0 && "animate-spin")}>
          <SpinnerIcon />
        </span>
        <span aria-hidden="true" className="sm:hidden">
          {runningJobs}
        </span>
        <span className="sr-only sm:not-sr-only">{jobsLabel}</span>
      </Link>

      <Link
        href="/"
        data-testid="waiting-status"
        className="inline-flex min-h-11 min-w-11 items-center justify-center hover:text-foreground"
      >
        <span
          className={cn(
            "inline-flex h-6.5 items-center gap-1.5 rounded-full px-2.5",
            waitingForOwner > 0 && "bg-chip-needs-you font-semibold text-primary",
          )}
        >
          <BellIcon />
          <span aria-hidden="true" className="sm:hidden">
            {waitingForOwner}
          </span>
          <span className="sr-only sm:not-sr-only">{waitingLabel}</span>
        </span>
      </Link>
    </header>
  );
}

/**
 * The strip wired to the API. Waiting items are the loaded episodes that stand at a gate.
 * Running jobs stay at zero until the jobs endpoint exists.
 */
export function StatusStrip() {
  const state = useApiState();
  const episodes = useEpisodes().state;
  const waiting =
    episodes.kind === "ready"
      ? episodes.episodes.filter((episode) => episode.awaiting_approval).length
      : 0;
  const providers = useProviders().state;
  const warning = providers.kind === "ready" ? warningOf(providers.providers) : null;
  return (
    <StatusStripView state={state} runningJobs={0} waitingForOwner={waiting} providerWarning={warning} />
  );
}
