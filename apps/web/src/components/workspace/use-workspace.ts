"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AssetList,
  type EpisodeDetail,
  type PlanOut,
  type RenderOut,
  type SpecOut,
  getEpisode,
  getEpisodeAssets,
  getEpisodePlan,
  getEpisodeRenders,
  getEpisodeSpec,
} from "@/api/client";
import { ApiFailure, failureOf, unwrap } from "@/lib/api-error";

const POLL_MS = 3_000;
const PLANNING: readonly string[] = ["idea", "brief", "research", "script", "direction"];

export interface WorkspaceData {
  episode: EpisodeDetail;
  /** Null until the plan has written the spec. */
  spec: SpecOut | null;
  plan: PlanOut | null;
  /** The newest video. Null until the episode has one. */
  render: RenderOut | null;
  /** The episode's pictures. Null until the plan is approved. */
  assets: AssetList | null;
}

export type WorkspaceState =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "error"; message: string }
  | ({ kind: "ready" } & WorkspaceData);

async function load(episodeId: string): Promise<WorkspaceData> {
  const path = { episode_id: episodeId };
  const episode = unwrap(await getEpisode({ path }), "The episode could not be loaded. Try again.");
  const [specAnswer, planAnswer] = await Promise.all([getEpisodeSpec({ path }), getEpisodePlan({ path })]);
  // An episode whose plan is still being written has no spec yet. That is not a failure.
  const spec =
    specAnswer.response?.status === 404
      ? null
      : unwrap(specAnswer, "The plan could not be loaded. Try again.");
  const plan = unwrap(planAnswer, "The plan could not be loaded. Try again.");
  // Before the plan is approved there cannot be a video, so nothing is asked.
  const renders = PLANNING.includes(episode.state)
    ? null
    : unwrap(
        await getEpisodeRenders({ path, query: { limit: 1 } }),
        "The video could not be loaded. Try again.",
      );
  const assets =
    PLANNING.includes(episode.state) || spec === null
      ? null
      : unwrap(await getEpisodeAssets({ path }), "The pictures could not be loaded. Try again.");
  return { episode, spec, plan, render: renders?.renders[0] ?? null, assets };
}

/**
 * One episode with its spec and plan, read again every few seconds while the tab is
 * visible, because the pipeline moves the episode by itself. A refresh that fails keeps
 * what is on screen: the next one tries again.
 */
export function useWorkspace(episodeId: string) {
  const [state, setState] = useState<WorkspaceState>({ kind: "loading" });
  // Answers can arrive out of order. Only the newest request may change what is shown.
  const newest = useRef(0);

  const reload = useCallback(async () => {
    const request = (newest.current += 1);
    try {
      const data = await load(episodeId);
      if (request === newest.current) {
        setState({ kind: "ready", ...data });
      }
    } catch (error) {
      if (request !== newest.current) {
        return;
      }
      const failure = failureOf(error);
      setState((current) => {
        if (failure instanceof ApiFailure && failure.status === 404) {
          return { kind: "missing" };
        }
        return current.kind === "ready" ? current : { kind: "error", message: failure.message };
      });
    }
  }, [episodeId]);

  useEffect(() => {
    function tick() {
      if (!document.hidden) {
        void reload();
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
  }, [reload]);

  const retry = useCallback(() => {
    setState({ kind: "loading" });
    void reload();
  }, [reload]);

  return { state, reload, retry };
}
