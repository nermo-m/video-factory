// How a provider's state and usage are worded (design doc section 11.5 "Model picker and
// usage", FR-33). No React and no requests here.
import type { ProviderOut } from "@/api/client";

export type ChipTone = "ready" | "near" | "paused" | "limited";

const DAY_MS = 24 * 60 * 60 * 1000;

/** Hours and minutes in the owner's own time zone. A time more than a day away names its day. */
export function clockTime(iso: string, now: number = Date.now()): string {
  const date = new Date(iso);
  const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" }).format(date);
  if (Math.abs(date.getTime() - now) < DAY_MS) {
    return time;
  }
  return `${new Intl.DateTimeFormat("en-GB", { weekday: "short" }).format(date)} ${time}`;
}

export function chipOf(provider: ProviderOut, now?: number): { tone: ChipTone; label: string } {
  switch (provider.state) {
    case "near_budget":
      return { tone: "near", label: "Near budget" };
    case "paused_by_budget":
      return { tone: "paused", label: "Paused" };
    case "limited":
      return {
        tone: "limited",
        label: provider.limited_until ? `Limited until ${clockTime(provider.limited_until, now)}` : "Limited",
      };
    default:
      return { tone: "ready", label: "Ready" };
  }
}

/** A limited or paused provider cannot take work right now. */
export function isAvailable(provider: ProviderOut): boolean {
  return provider.state === "ok" || provider.state === "near_budget";
}

/** Why a provider cannot be chosen, and when it returns. Null while it can be. */
export function reasonOf(provider: ProviderOut, now?: number): string | null {
  if (provider.state === "limited") {
    const who = provider.state_source === "tool" ? "Reported by the tool." : "Counted by this app.";
    return provider.limited_until ? `${who} Back at ${clockTime(provider.limited_until, now)}.` : who;
  }
  if (provider.state === "paused_by_budget") {
    return "Your budget is used up. It frees up as earlier use leaves the window, or raise the budget on the Usage page.";
  }
  return null;
}

/** Who says so: a limit a tool reported is the tool's word, every count is this app's. */
export function sourceOf(provider: ProviderOut): string {
  return provider.state === "limited" && provider.state_source === "tool"
    ? "Limit reported by the tool"
    : "Counted by this app";
}

const RUNS_ON: Record<string, string> = {
  demo: "Bundled recordings. Nothing is sent anywhere",
  claude_plan: "Through Claude Code on this PC",
  chatgpt_plan: "Through Codex on this PC",
  anthropic_api: "Anthropic API, paid per use",
  openai_api: "OpenAI API, paid per use",
};

const USED_FOR: Record<string, string> = {
  demo: "every step, with recorded answers",
  claude_plan: "planning and writing",
  chatgpt_plan: "second review and images",
  anthropic_api: "planning and writing",
  openai_api: "second review and images",
};

export const runsOn = (provider: ProviderOut) => RUNS_ON[provider.id] ?? provider.billing;
export const usedFor = (provider: ProviderOut) => USED_FOR[provider.id] ?? "";

export type Unit = "calls" | "images" | "usd";
export type WindowId = "5h" | "7d";

export interface UsageRow {
  key: `${WindowId}-${Unit}`;
  window: string;
  unit: Unit;
  used: number;
  /** Null when the owner set no budget for it. */
  budget: number | null;
  /** How full the bar is, 0 to 100. Null without a budget. */
  percent: number | null;
  text: string;
  shortText: string;
}

function amount(value: number, unit: Unit): string {
  if (unit === "usd") {
    return `${value.toFixed(2)} USD`;
  }
  return `${value} ${value === 1 ? unit.slice(0, -1) : unit}`;
}

/** A budget of zero allows nothing: the first use is already over it, as the API counts. */
function share(used: number, limit: number): number {
  if (limit > 0) {
    return Math.min(100, Math.round((used / limit) * 100));
  }
  return used > 0 ? 100 : 0;
}

function row(window: WindowId, unit: Unit, used: number, budget: number | null): UsageRow {
  const limit = budget;
  const figure = unit === "usd" ? used.toFixed(2) : String(used);
  return {
    key: `${window}-${unit}`,
    window: window === "5h" ? "Last 5 hours" : "Last 7 days",
    unit,
    used,
    budget: limit,
    percent: limit === null ? null : share(used, limit),
    text: limit === null ? amount(used, unit) : `${figure} of ${amount(limit, unit)}`,
    shortText: limit === null ? figure : `${figure} of ${unit === "usd" ? limit.toFixed(2) : limit}`,
  };
}

const makesImages = (provider: ProviderOut) =>
  provider.usage.seven_days.images > 0 || provider.id === "chatgpt_plan" || provider.id === "openai_api";

/**
 * What the owner's budget of a provider is counted in, as the API pauses it: calls and
 * images on a plan, money on a paid API, nothing for the demo recordings.
 */
export function budgetUnits(provider: ProviderOut): Unit[] {
  if (provider.billing === "plan") {
    return makesImages(provider) ? ["calls", "images"] : ["calls"];
  }
  return provider.billing === "api" ? ["usd"] : [];
}

/**
 * The usage lines of a provider: calls always, images where the provider makes them,
 * money for a paid provider. A line has a budget only in a unit the provider is paused by.
 */
export function usageRows(provider: ProviderOut): UsageRow[] {
  const { five_hours: short, seven_days: long } = provider.usage;
  const budget = provider.budget;
  const plan = provider.billing === "plan";
  const rows = [
    row("5h", "calls", short.calls, plan ? budget.calls_5h : null),
    row("7d", "calls", long.calls, plan ? budget.calls_7d : null),
  ];
  if (makesImages(provider)) {
    rows.push(
      row("5h", "images", short.images, plan ? budget.images_5h : null),
      row("7d", "images", long.images, plan ? budget.images_7d : null),
    );
  }
  if (provider.billing === "api") {
    rows.push(
      row("5h", "usd", Number(short.cost_usd), Number(budget.usd_5h)),
      row("7d", "usd", Number(long.cost_usd), Number(budget.usd_7d)),
    );
  }
  return rows;
}

/** The two bars of the picker: the fuller unit of each window. */
export function pickerRows(provider: ProviderOut): UsageRow[] {
  const rows = usageRows(provider);
  return (["5h", "7d"] as const).map((window) => {
    const ofWindow = rows.filter((candidate) => candidate.key.startsWith(window));
    return ofWindow.reduce((fullest, candidate) =>
      (candidate.percent ?? -1) > (fullest.percent ?? -1) ? candidate : fullest,
    );
  });
}

export function barTone(percent: number | null): "ok" | "near" | "full" {
  if (percent === null || percent < 80) {
    return "ok";
  }
  return percent >= 100 ? "full" : "near";
}

export function lastChecked(iso: string | null, now: number = Date.now()): string {
  if (!iso) {
    return "Not checked yet";
  }
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) {
    return "Last checked just now";
  }
  if (minutes < 60) {
    return `Last checked ${minutes} min ago`;
  }
  return `Last checked at ${clockTime(iso, now)}`;
}

/** The newest check among the providers, for the one label beside "Check limits now". */
export function newestCheck(providers: ProviderOut[]): string | null {
  const times = providers.map((provider) => provider.last_checked_at).filter((time): time is string => Boolean(time));
  return times.sort().at(-1) ?? null;
}

const ATTENTION: Record<string, string> = {
  near_budget: "near budget",
  paused_by_budget: "paused",
  limited: "limited",
};

/** The status strip's warning: null while every provider is ready. */
export function warningOf(providers: ProviderOut[]): { label: string; severe: boolean } | null {
  const troubled = providers.filter((provider) => provider.state !== "ok");
  const first = troubled[0];
  if (!first) {
    return null;
  }
  return {
    label: troubled.length === 1 ? `${first.title} ${ATTENTION[first.state]}` : `${troubled.length} providers need attention`,
    severe: troubled.some((provider) => provider.state !== "near_budget"),
  };
}

/** Providers that were limited or paused before a check and are ready after it. */
export function returned(before: ProviderOut[], after: ProviderOut[]): string[] {
  return after
    .filter((now) => isAvailable(now) && before.some((then) => then.id === now.id && !isAvailable(then)))
    .map((provider) => provider.title);
}

export const MODE_NOTES: Record<string, { title: string; text: string }> = {
  demo: {
    title: "Demo mode.",
    text: "Models are simulated with bundled recordings. Nothing is sent and nothing is billed.",
  },
  subscription: {
    title: "Subscription mode.",
    text: "Models run on your own Claude and ChatGPT plans. Nothing is billed per use.",
  },
  api: {
    title: "API mode.",
    text: "Models run on paid APIs when the switch below is on. Every call is billed.",
  },
};
