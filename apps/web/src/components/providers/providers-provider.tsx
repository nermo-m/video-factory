"use client";

import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  type BudgetUpdate,
  type Provider,
  type ProviderOut,
  getProviders,
  postProvidersCheck,
  putProviderBudget,
} from "@/api/client";
import { failureOf, unwrap } from "@/lib/api-error";

const POLL_MS = 30_000;

export type ProvidersState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; providers: ProviderOut[] };

interface Providers {
  state: ProvidersState;
  retry: () => void;
  /** Ask every provider now. Answers with the fresh list, or throws an ApiFailure. */
  check: () => Promise<ProviderOut[]>;
  setBudget: (provider: Provider, budget: BudgetUpdate) => Promise<void>;
}

const ProvidersContext = createContext<Providers | null>(null);

/**
 * The providers of the current mode with their state and usage, for the Usage page, the
 * model picker and the warning in the status strip. Read again every half minute while
 * the tab is visible. A refresh that fails keeps what is shown.
 */
export function ProvidersProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ProvidersState>({ kind: "loading" });
  const newest = useRef(0);

  const show = useCallback((providers: ProviderOut[]) => {
    newest.current += 1;
    setState({ kind: "ready", providers });
  }, []);

  const refresh = useCallback(async () => {
    const request = (newest.current += 1);
    try {
      const data = unwrap(await getProviders(), "The providers could not be loaded. Try again.");
      if (request === newest.current) {
        setState({ kind: "ready", providers: data.providers });
      }
    } catch (error) {
      if (request === newest.current) {
        setState((current) =>
          current.kind === "ready" ? current : { kind: "error", message: failureOf(error).message },
        );
      }
    }
  }, []);

  useEffect(() => {
    function tick() {
      if (!document.hidden) {
        void refresh();
      }
    }
    tick();
    const timer = window.setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      newest.current += 1;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [refresh]);

  const value = useMemo<Providers>(
    () => ({
      state,
      retry: () => {
        setState({ kind: "loading" });
        void refresh();
      },
      check: async () => {
        const data = unwrap(await postProvidersCheck(), "The limits could not be checked. Try again.");
        show(data.providers);
        return data.providers;
      },
      setBudget: async (provider, budget) => {
        const data = unwrap(
          await putProviderBudget({ path: { provider }, body: budget }),
          "The budget could not be saved. Try again.",
        );
        show(data.providers);
      },
    }),
    [state, refresh, show],
  );

  return <ProvidersContext.Provider value={value}>{children}</ProvidersContext.Provider>;
}

export function useProviders(): Providers {
  const value = useContext(ProvidersContext);
  if (!value) {
    throw new Error("useProviders needs a ProvidersProvider above it.");
  }
  return value;
}
