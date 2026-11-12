import type { Provider, ProviderOut } from "@/api/client";
import { isAvailable, lastChecked, newestCheck, pickerRows, reasonOf, runsOn } from "@/lib/providers";
import { cn } from "@/lib/utils";

import { CheckButton, StateChip, UsageBar } from "./provider-parts";

function Option({ provider }: { provider: ProviderOut }) {
  const reason = reasonOf(provider);
  return (
    <>
      <span className="flex items-start justify-between gap-2">
        <span className="flex min-w-0 flex-col gap-0.5 text-left">
          <span className="flex flex-wrap items-center gap-2 text-[0.9375rem] font-semibold">
            {provider.title}
            {provider.billing === "api" && (
              <span className="rounded-md bg-raised px-1.5 py-0.5 text-[0.6875rem] font-semibold text-warning">Paid</span>
            )}
          </span>
          <span className="text-xs text-muted-foreground">{runsOn(provider)}</span>
        </span>
        <StateChip provider={provider} />
      </span>
      {pickerRows(provider).map((row) => (
        <UsageBar key={row.key} row={row} short />
      ))}
      {reason && <span className="text-left text-xs text-muted-foreground">{reason}</span>}
    </>
  );
}

export interface ModelPickerProps {
  /** What is being chosen, for example "Model for planning". */
  title: string;
  providers: ProviderOut[];
  /** The chosen provider. Without `onChange` the picker only shows what is in use. */
  value?: Provider;
  onChange?: (provider: Provider) => void;
  checking: boolean;
  onCheck: () => void;
}

/**
 * The model picker (design doc section 11.5, FR-33): one row per model with its state,
 * two usage bars and who counted. A limited or paused model stays visible with the reason
 * and the time it returns, and cannot be chosen. Paid models are marked.
 *
 * It lists the providers it is given. The API returns only those of the current mode, so
 * a paid model appears only in API mode.
 */
export function ModelPicker({ title, providers, value, onChange, checking, onCheck }: ModelPickerProps) {
  const frame = "flex w-full flex-col gap-2.5 rounded-xl border-2 bg-background p-3.5";
  return (
    <section data-testid="model-picker" className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">Numbers are counted by this app unless marked.</p>
      </div>
      <ul className="grid gap-3 lg:grid-cols-2">
        {providers.map((provider) => {
          const available = isAvailable(provider);
          const chosen = value === provider.id;
          return (
            <li key={provider.id} data-available={available} className="min-w-0">
              {onChange ? (
                <button
                  type="button"
                  aria-pressed={chosen}
                  disabled={!available}
                  onClick={() => onChange(provider.id)}
                  className={cn(frame, chosen && "border-primary", !available && "cursor-not-allowed")}
                >
                  <Option provider={provider} />
                </button>
              ) : (
                <div className={cn(frame, chosen && "border-primary")}>
                  <Option provider={provider} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        <CheckButton checking={checking} onCheck={onCheck} />
        <span className="text-xs text-muted-foreground">{lastChecked(newestCheck(providers))}</span>
      </div>
    </section>
  );
}
