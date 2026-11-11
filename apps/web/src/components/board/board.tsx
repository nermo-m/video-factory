"use client";

import { Banner, EmptyState, PageHeader } from "@/components/page";
import { type ApiState, useApiState } from "@/components/shell/status-strip";

export function BoardBanner({ state }: { state: ApiState }) {
  if (state.kind === "unreachable") {
    return (
      <Banner>
        The API is not answering. Check that the stack is running with <code>docker compose ps</code>,
        then reload this page.
      </Banner>
    );
  }
  if (state.kind !== "ready") {
    return null;
  }
  if (state.health.status !== "ok") {
    const failed = [state.health.checks.database, state.health.checks.storage]
      .map((check) => check.message)
      .filter(Boolean)
      .join(" ");
    return <Banner>The studio cannot work right now. {failed}</Banner>;
  }
  if (state.health.demo_mode) {
    return (
      <Banner>
        Demo mode is on. Models, images and clips are simulated with bundled samples, and nothing is
        sent to a paid service.
      </Banner>
    );
  }
  if (state.health.checks.comfyui.status === "offline") {
    return (
      <Banner>
        ComfyUI is not running, so clips cannot be generated. Start ComfyUI on this PC. Everything
        that does not need the GPU stays usable.
      </Banner>
    );
  }
  return null;
}

/**
 * The Board with no episodes yet. The columns from the mockups (Needs you, Planning,
 * Producing, Finished) appear with the first episode.
 */
export function Board() {
  const state = useApiState();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Board" note="0 episodes" />
      <BoardBanner state={state} />
      <EmptyState title="No episodes yet">
        An episode starts as one idea and ends as a finished vertical video. Each one appears here
        with its current step, and anything waiting for you comes first. Start with New episode.
      </EmptyState>
    </div>
  );
}
