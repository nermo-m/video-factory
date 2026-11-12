"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useId, useState } from "react";

import { type BudgetUpdate, type ProviderOut, type SettingsResponse, getSettings, putSettings } from "@/api/client";
import { Banner } from "@/components/page";
import { type ApiFailure, failureOf, unwrap } from "@/lib/api-error";
import {
  MODE_NOTES,
  budgetUnits,
  lastChecked,
  newestCheck,
  reasonOf,
  returned,
  runsOn,
  sourceOf,
  usageRows,
  usedFor,
} from "@/lib/providers";
import { primaryAction, quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";

import { ModelPicker } from "./model-picker";
import { CheckButton, StateChip, UsageBar } from "./provider-parts";
import { useProviders } from "./providers-provider";

const alertLook = "rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3";

/** Runs "Check limits now" and keeps what it found to say. */
export function useCheck() {
  const { state, check } = useProviders();
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<{ text: string; failed: boolean } | null>(null);

  async function run() {
    const before = state.kind === "ready" ? state.providers : [];
    setChecking(true);
    setResult(null);
    try {
      const back = returned(before, await check());
      setResult(
        back.length > 0
          ? {
              text: back
                .map((title) => `${title} is ready again. Its waiting jobs resume.`)
                .join(" "),
              failed: false,
            }
          : null,
      );
    } catch (error) {
      setResult({ text: failureOf(error).message, failed: true });
    } finally {
      setChecking(false);
    }
  }

  return { checking, result, run: () => void run() };
}

export function CheckResult({ result }: { result: { text: string; failed: boolean } | null }) {
  return (
    <p
      data-testid="check-result"
      aria-live="polite"
      className={cn(
        result && "rounded-lg border px-3.5 py-3",
        result?.failed ? "border-danger/50 bg-chip-failed" : "border-success/50 bg-chip-finished",
      )}
    >
      {result?.text}
    </p>
  );
}

const BUDGET_FIELDS = [
  ["calls_5h", "Calls per 5 hours", "calls"],
  ["calls_7d", "Calls per 7 days", "calls"],
  ["images_5h", "Images per 5 hours", "images"],
  ["images_7d", "Images per 7 days", "images"],
  ["usd_5h", "US dollars per 5 hours", "usd"],
  ["usd_7d", "US dollars per 7 days", "usd"],
] as const;

/** Money as the API takes it: up to six digits and up to four decimals. */
const AMOUNT = "[0-9]{1,6}(\\.[0-9]{1,4})?";

function BudgetForm({ provider }: { provider: ProviderOut }) {
  const id = useId();
  const { setBudget } = useProviders();
  const shown = new Set(budgetUnits(provider));
  const [draft, setDraft] = useState(() => ({
    calls_5h: String(provider.budget.calls_5h),
    calls_7d: String(provider.budget.calls_7d),
    images_5h: String(provider.budget.images_5h),
    images_7d: String(provider.budget.images_7d),
    usd_5h: provider.budget.usd_5h,
    usd_7d: provider.budget.usd_7d,
  }));
  const paid = provider.billing === "api";
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [saved, setSaved] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setFailure(null);
    setSaved(false);
    // A paid provider is budgeted in money, which travels as text exactly as it was typed.
    // A plan is budgeted in calls and images. What is left out keeps its value.
    const body: BudgetUpdate = paid
      ? { usd_5h: draft.usd_5h, usd_7d: draft.usd_7d }
      : {
          calls_5h: Number(draft.calls_5h),
          calls_7d: Number(draft.calls_7d),
          images_5h: Number(draft.images_5h),
          images_7d: Number(draft.images_7d),
        };
    try {
      await setBudget(provider.id, body);
      setSaved(true);
    } catch (error) {
      setFailure(failureOf(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(event) => void save(event)} className="flex flex-col gap-3 border-t pt-3">
      <p className="text-xs font-semibold text-muted-foreground">
        Your budget. The app warns at 80 percent and pauses at 100.
      </p>
      <div className="grid grid-cols-2 gap-3">
        {BUDGET_FIELDS.filter(([, , unit]) => shown.has(unit)).map(([key, label, unit]) => (
          <div key={key} className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-${key}`} className="text-xs font-semibold text-muted-foreground">
              {label}
            </label>
            <input
              id={`${id}-${key}`}
              {...(unit === "usd"
                ? { type: "text", inputMode: "decimal", pattern: AMOUNT, title: "An amount such as 2.50" }
                : { type: "number", inputMode: "numeric", min: 0, step: 1 })}
              required
              value={draft[key]}
              onChange={(event) => {
                setDraft({ ...draft, [key]: event.target.value });
                setSaved(false);
              }}
              className="h-11 w-full rounded-lg border bg-raised px-3 text-base sm:text-sm"
            />
          </div>
        ))}
      </div>
      {failure && (
        <div role="alert" className={alertLook}>
          <p>{failure.message}</p>
          {failure.problems.map((problem) => (
            <p key={problem} className="font-mono text-xs">
              {problem}
            </p>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={saving} className={quietAction}>
          {saving ? "Saving…" : "Save budget"}
        </button>
        {saved && <span className="text-xs font-semibold text-success">Saved.</span>}
      </div>
    </form>
  );
}

function ProviderCard({ provider }: { provider: ProviderOut }) {
  const id = useId();
  const reason = reasonOf(provider);
  return (
    <section
      aria-labelledby={id}
      className={cn(
        "flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-4 sm:p-5",
        (provider.state === "limited" || provider.state === "paused_by_budget") && "border-danger",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2.5">
        <div className="flex flex-col gap-1">
          <h2 id={id} className="text-lg font-semibold">
            {provider.title}
          </h2>
          <p className="text-xs text-muted-foreground">{runsOn(provider)}</p>
        </div>
        <StateChip provider={provider} />
      </div>
      <p className="text-[0.8125rem] text-muted-foreground">Used for: {usedFor(provider)}</p>
      {usageRows(provider).map((row) => (
        <UsageBar key={row.key} row={row} />
      ))}
      {reason && <p className="text-[0.8125rem]">{reason}</p>}
      {provider.last_error && provider.state !== "ok" && (
        <p className="text-[0.8125rem] text-muted-foreground wrap-anywhere">It said: {provider.last_error}</p>
      )}
      <div className="flex flex-wrap justify-between gap-2.5 border-t pt-3 text-xs text-muted-foreground">
        <span>{sourceOf(provider)}</span>
        <span>{lastChecked(provider.last_checked_at)}</span>
      </div>
      {provider.billing === "demo" ? (
        <p className="text-xs text-muted-foreground">Demo recordings cost nothing, so there is no budget to set.</p>
      ) : (
        <BudgetForm provider={provider} />
      )}
    </section>
  );
}

/** The "Use paid APIs" switch. Turning it on asks first, because paid APIs bill per use. */
function PaidApis() {
  const id = useId();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getSettings().then((answer) => {
      if (cancelled) {
        return;
      }
      try {
        setSettings(unwrap(answer, "The settings could not be loaded. Reload this page."));
      } catch (error) {
        setFailure(failureOf(error).message);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function set(on: boolean) {
    setBusy(true);
    setFailure(null);
    setConfirming(false);
    try {
      setSettings(
        unwrap(await putSettings({ body: { use_paid_apis: on } }), "The switch could not be changed. Try again."),
      );
    } catch (error) {
      setFailure(failureOf(error).message);
    } finally {
      setBusy(false);
    }
  }

  const on = settings?.use_paid_apis ?? false;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-xl border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex min-w-0 grow basis-80 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 id={id} className="text-lg font-semibold">
              Paid APIs
            </h2>
            <span className="inline-flex h-6.5 items-center rounded-full bg-raised px-2.5 text-xs font-semibold text-muted-foreground">
              {settings?.paid_apis_active ? "In use" : on ? "Switched on, not in use" : "Off"}
            </span>
          </div>
          <p className="text-[0.8125rem] text-muted-foreground">
            Anthropic API and OpenAI API. Never used unless you turn this on. The app does not switch to
            them by itself, even when a plan is limited.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label="Use paid APIs"
          disabled={busy || settings === null}
          onClick={() => (on ? void set(false) : setConfirming(true))}
          className={cn("flex h-11 w-16 shrink-0 items-center rounded-full border px-1", on ? "justify-end bg-info" : "bg-raised")}
        >
          <span className={cn("size-8 rounded-full", on ? "bg-background" : "bg-muted-foreground")} />
        </button>
      </div>
      {settings?.paid_apis_message && <p className="text-[0.8125rem] wrap-anywhere">{settings.paid_apis_message}</p>}
      {confirming && (
        <div className="flex flex-col gap-3 rounded-lg border border-warning/60 bg-chip-out-of-date p-3.5">
          <p>
            Paid APIs bill per use, to the keys in your <code>.env</code> file. They are used only while{" "}
            <code>PROVIDER_MODE</code> is <code>api</code> as well.
          </p>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => void set(true)} className={quietAction}>
              Turn on
            </button>
            <button type="button" onClick={() => setConfirming(false)} className={quietAction}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {failure && (
        <p role="alert" className={alertLook}>
          {failure}
        </p>
      )}
    </section>
  );
}

function Loading() {
  return (
    <div data-testid="usage-loading" aria-busy="true" className="flex flex-col gap-4">
      <p className="text-muted-foreground">Loading the providers…</p>
      <div aria-hidden="true" className="h-48 animate-pulse rounded-xl border bg-card" />
    </div>
  );
}

function LoadFailed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section
      role="alert"
      data-testid="usage-error"
      className="flex max-w-xl flex-col items-start gap-3 rounded-lg border border-danger/50 bg-chip-failed p-5 sm:p-6"
    >
      <h2 className="text-lg font-semibold">The providers could not be loaded</h2>
      <p>{message}</p>
      <button type="button" onClick={onRetry} className={quietAction}>
        Try again
      </button>
    </section>
  );
}

function ModeNote() {
  const [mode, setMode] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void getSettings().then((answer) => {
      if (!cancelled && answer.data) {
        setMode(answer.data.provider_mode);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const note = mode ? MODE_NOTES[mode] : undefined;
  if (!note) {
    return null;
  }
  return (
    <Banner>
      <span className="font-semibold">{note.title}</span> {note.text}
    </Banner>
  );
}

/** Usage and limits (design doc section 11.5): every provider of the mode, with budgets. */
export function UsagePage() {
  const { state, retry } = useProviders();
  const { checking, result, run } = useCheck();

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="flex grow basis-80 flex-col gap-1">
          <nav aria-label="Breadcrumb" className="text-[0.8125rem] text-muted-foreground">
            <Link href="/settings" className="inline-flex min-h-11 min-w-11 items-center hover:text-foreground">
              Settings
            </Link>{" "}
            / Usage and limits
          </nav>
          <h1 className="text-[1.625rem] font-bold sm:text-[1.75rem]">Usage and limits</h1>
        </div>
        {state.kind === "ready" && (
          <>
            <span className="text-[0.8125rem] text-muted-foreground">
              Checks itself every 10 minutes. {lastChecked(newestCheck(state.providers))}.
            </span>
            <CheckButton checking={checking} onCheck={run} className={primaryAction} />
          </>
        )}
      </div>
      <ModeNote />
      <CheckResult result={result} />

      {state.kind === "loading" && <Loading />}
      {state.kind === "error" && <LoadFailed message={state.message} onRetry={retry} />}
      {state.kind === "ready" && (
        <div className="grid items-start gap-5 lg:grid-cols-2">
          {state.providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} />
          ))}
        </div>
      )}
      <PaidApis />
    </div>
  );
}

/** Settings: the mode, the models in use, and the way to Usage and limits. */
export function SettingsPage() {
  const { state, retry } = useProviders();
  const { checking, result, run } = useCheck();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[1.625rem] font-bold sm:text-[1.75rem]">Settings</h1>
      <ModeNote />
      {state.kind === "loading" && <Loading />}
      {state.kind === "error" && <LoadFailed message={state.message} onRetry={retry} />}
      {state.kind === "ready" && (
        <>
          <ModelPicker title="Models in use" providers={state.providers} checking={checking} onCheck={run} />
          <CheckResult result={result} />
        </>
      )}
      <section className="flex max-w-xl flex-col items-start gap-3 rounded-lg border bg-card p-5 sm:p-6">
        <h2 className="text-lg font-semibold">Usage and limits</h2>
        <p className="text-muted-foreground">
          How much each provider was used in the last 5 hours and 7 days, your budgets, and the switch
          for paid APIs.
        </p>
        <Link href="/settings/usage" className={quietAction}>
          Usage and limits
        </Link>
      </section>
      <section className="flex max-w-xl flex-col gap-3 rounded-lg border bg-card p-5 sm:p-6">
        <h2 className="text-lg font-semibold">Not built yet</h2>
        <p className="text-muted-foreground">
          The channel template, the export folder and a model per role will be set here. The mode itself
          is set with <code>PROVIDER_MODE</code> in the <code>.env</code> file.
        </p>
      </section>
    </div>
  );
}
