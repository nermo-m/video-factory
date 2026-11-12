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

import { type EpisodeOut, getEpisodes } from "@/api/client";
import { API_NOT_ANSWERING, failureMessage } from "@/lib/api-error";

/** How many episodes one "Show more" adds. */
export const PAGE_SIZE = 50;
/** The most the API returns in one answer. */
const API_LIMIT = 200;
const POLL_MS = 5_000;

export type EpisodesState =
  | { kind: "loading" }
  /** Nothing could be loaded. Never shown as "no episodes". */
  | { kind: "error"; message: string }
  /** `stale` is true when the last refresh failed and the list may be old. */
  | { kind: "ready"; episodes: EpisodeOut[]; total: number; stale: boolean };

interface Episodes {
  state: EpisodesState;
  /** Load again now, for example after an episode was created. */
  refresh: () => Promise<void>;
  /** Start over after an error. */
  retry: () => void;
  /** Load one more page. */
  showMore: () => Promise<void>;
}

const EpisodesContext = createContext<Episodes | null>(null);

class LoadError extends Error {}

/** The newest `wanted` episodes, asked for in as few requests as the API allows. */
async function load(wanted: number): Promise<{ episodes: EpisodeOut[]; total: number }> {
  const episodes: EpisodeOut[] = [];
  for (;;) {
    const limit = Math.min(API_LIMIT, wanted - episodes.length);
    const result = await getEpisodes({ query: { limit, offset: episodes.length } });
    const data = result.data;
    if (!data) {
      throw new LoadError(failureMessage(result, "The API refused the request. Try again."));
    }
    episodes.push(...data.episodes);
    const done = data.episodes.length < limit || episodes.length >= Math.min(wanted, data.total);
    if (done) {
      return { episodes, total: data.total };
    }
  }
}

/**
 * Keeps the episode list for every screen: the Board shows it and the status strip counts
 * what waits for the owner. It is read again every few seconds, because episodes move by
 * themselves while the pipeline works. Reading pauses while the tab is hidden.
 */
export function EpisodesProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<EpisodesState>({ kind: "loading" });
  const wanted = useRef(PAGE_SIZE);
  // Answers can arrive out of order. Only the newest request may change what is shown.
  const newest = useRef(0);

  const refresh = useCallback(async () => {
    const request = (newest.current += 1);
    try {
      const result = await load(wanted.current);
      if (request === newest.current) {
        setState({ kind: "ready", ...result, stale: false });
      }
    } catch (error) {
      if (request !== newest.current) {
        return;
      }
      const message = error instanceof LoadError ? error.message : API_NOT_ANSWERING;
      setState((current) =>
        current.kind === "ready" ? { ...current, stale: true } : { kind: "error", message },
      );
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
      // Whatever is still on its way no longer counts.
      newest.current += 1;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [refresh]);

  const value = useMemo<Episodes>(
    () => ({
      state,
      refresh,
      retry: () => {
        setState({ kind: "loading" });
        void refresh();
      },
      showMore: () => {
        wanted.current += PAGE_SIZE;
        return refresh();
      },
    }),
    [state, refresh],
  );

  return <EpisodesContext.Provider value={value}>{children}</EpisodesContext.Provider>;
}

export function useEpisodes(): Episodes {
  const value = useContext(EpisodesContext);
  if (!value) {
    throw new Error("useEpisodes needs an EpisodesProvider above it.");
  }
  return value;
}
