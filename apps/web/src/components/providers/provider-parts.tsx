import type { ProviderOut } from "@/api/client";
import { type ChipTone, type UsageRow, barTone, chipOf } from "@/lib/providers";
import { quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";

const CHIP_LOOK: Record<ChipTone, string> = {
  ready: "bg-chip-finished text-success",
  near: "bg-chip-out-of-date text-warning",
  paused: "bg-chip-failed text-danger",
  limited: "bg-chip-failed text-danger",
};

const ICON = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 3,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  className: "size-3 shrink-0",
};

function ChipIcon({ tone }: { tone: ChipTone }) {
  if (tone === "ready") {
    return (
      <svg {...ICON}>
        <path d="M5 12l5 5 9-10" />
      </svg>
    );
  }
  if (tone === "near") {
    return (
      <svg {...ICON}>
        <path d="M12 6v7M12 18h.01" />
      </svg>
    );
  }
  return (
    <svg {...ICON}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

/** Ready, Near budget, Paused, or Limited until 18:40. An icon and words, never colour alone. */
export function StateChip({ provider }: { provider: ProviderOut }) {
  const chip = chipOf(provider);
  return (
    <span
      data-testid="provider-state"
      className={cn(
        "inline-flex h-6.5 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold whitespace-nowrap",
        CHIP_LOOK[chip.tone],
      )}
    >
      <ChipIcon tone={chip.tone} />
      {chip.label}
    </span>
  );
}

const BAR_LOOK = { ok: "bg-info", near: "bg-warning", full: "bg-danger" };

/** One usage line: the window, the count against the budget, and a thin bar. */
export function UsageBar({ row, short = false }: { row: UsageRow; short?: boolean }) {
  return (
    <div data-testid={`usage-${row.key}`} className="flex flex-col gap-1.5">
      <div className="flex justify-between gap-3 text-xs text-muted-foreground">
        <span>{row.window}</span>
        <span className="font-mono">{short ? row.shortText : row.text}</span>
      </div>
      {row.percent !== null && (
        <div
          role="progressbar"
          aria-label={`${row.window}, ${row.unit === "usd" ? "cost" : row.unit}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={row.percent}
          className="h-1.5 overflow-hidden rounded-full bg-border"
        >
          <div style={{ width: `${row.percent}%` }} className={cn("h-full rounded-full", BAR_LOOK[barTone(row.percent)])} />
        </div>
      )}
    </div>
  );
}

function RefreshIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg {...ICON} strokeWidth={2.5} className={cn("size-4 shrink-0", spinning && "animate-spin")}>
      <path d="M4 12a8 8 0 0 1 14-5l2 2M20 4v5h-5M20 12a8 8 0 0 1-14 5l-2-2M4 20v-5h5" />
    </svg>
  );
}

/** "Check limits now" (FR-34): shows that it runs and cannot be pressed twice. */
export function CheckButton({
  checking,
  onCheck,
  className = quietAction,
}: {
  checking: boolean;
  onCheck: () => void;
  className?: string;
}) {
  return (
    <button type="button" onClick={onCheck} disabled={checking} className={cn(className, "gap-2")}>
      <RefreshIcon spinning={checking} />
      {checking ? "Checking…" : "Check limits now"}
    </button>
  );
}
