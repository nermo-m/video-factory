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

import { type EpisodeOut, deleteEpisode, getEpisodes } from "@/api/client";
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

/** A video the owner asked to delete, with the name it is called by on screen. */
export interface DeleteTarget {
  id: string;
  title: string;
}

/** What the last delete did, shown on the Board until the next one or until dismissed. */
export type DeleteNotice = { kind: "deleted"; text: string } | { kind: "failed"; text: string };

interface Episodes {
  state: EpisodesState;
  /**
   * Delete videos for good. Resolves with the ones that could not be deleted when every
   * one was tried. It never rejects.
   */
  remove: (targets: DeleteTarget[]) => Promise<DeleteTarget[]>;
  notice: DeleteNotice | null;
  dismissNotice: () => void;
  /** Load again now, for example after an episode was created. */
  refresh: () => Promise<void>;
  /** Start over after an error. */
  retry: () => void;
  /** Load one more page. */
  showMore: () => Promise<void>;
}

const EpisodesContext = createContext<Episodes | null>(null);

class LoadError extends Error {}

async function deleteOne(target: DeleteTarget): Promise<boolean> {
  try {
    const result = await deleteEpisode({ path: { episode_id: target.id } });
    return result.response?.status === 204;
  } catch {
    return false;
  }
}

function noticeOf(targets: DeleteTarget[], failed: DeleteTarget[]): DeleteNotice {
  if (failed.length === 0) {
    return { kind: "deleted", text: "Deleted." };
  }
  const [only] = failed;
  if (only && failed.length === 1) {
    return { kind: "failed", text: `${only.title} could not be deleted. Try again.` };
  }
  const gone = targets.length - failed.length;
  return {
    kind: "failed",
    text: `${failed.length} videos could not be deleted${gone ? `, ${gone} ${gone === 1 ? "was" : "were"}` : ""}. Try again.`,
  };
}

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
  const [notice, setNotice] = useState<DeleteNotice | null>(null);
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

  const remove = useCallback(
    async (targets: DeleteTarget[]) => {
      setNotice(null);
      const failed: DeleteTarget[] = [];
      // One after the other: a long list must not open dozens of requests at once.
      for (const target of targets) {
        if (!(await deleteOne(target))) {
          failed.push(target);
        }
      }
      await refresh();
      setNotice(noticeOf(targets, failed));
      return failed;
    },
    [refresh],
  );

  const value = useMemo<Episodes>(
    () => ({
      state,
      remove,
      notice,
      dismissNotice: () => setNotice(null),
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
    [state, refresh, remove, notice],
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
