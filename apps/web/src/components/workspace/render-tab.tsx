"use client";

import { useState } from "react";

import { type EpisodeDetail, type RenderOut, postEpisodeRerun } from "@/api/client";
import { failureOf, unwrap } from "@/lib/api-error";
import { displayTitle, stoppedOf, workingOn } from "@/lib/episodes";
import { quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { makingOf, renderCaption } from "@/lib/workspace";

const card = "flex max-w-xl flex-col gap-3 rounded-lg border bg-card p-5 sm:p-6";

/**
 * The video itself: always 9 by 16, never cropped, at most 70 percent of the screen high,
 * and loaded only when it is played (design doc section 11.5, "Video player"). The full
 * player with scene marks arrives with the Videos screen.
 */
export function DraftVideo({ render, title, className }: { render: RenderOut; title: string; className?: string }) {
  if (!render.video_url) {
    return null;
  }
  return (
    <video
      src={render.video_url}
      controls
      preload="none"
      playsInline
      aria-label={`Draft video of ${title}`}
      className={cn("aspect-9/16 max-h-[70dvh] w-auto max-w-full rounded-[0.875rem] border bg-black", className)}
    />
  );
}

/**
 * The reason a step stopped, with a way to run it again (design doc section 4.4: a failed
 * job shows an actionable message on the episode page). Nothing is shown while the step
 * works, waits for the owner or is done.
 */
export function StepFailed({ episode, reload }: { episode: EpisodeDetail; reload: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const stopped = stoppedOf(episode);
  if (!stopped) {
    return null;
  }

  async function again() {
    setBusy(true);
    setFailure(null);
    try {
      unwrap(
        await postEpisodeRerun({ path: { episode_id: episode.id }, body: { state: episode.state } }),
        "The step could not be started again. Try again.",
      );
      await reload();
    } catch (error) {
      setFailure(failureOf(error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      role="alert"
      data-testid="step-failed"
      className="flex flex-col items-start gap-3 rounded-lg border border-danger/50 bg-chip-failed p-4 sm:p-5"
    >
      <h2 className="text-lg font-semibold">{workingOn(episode.state)} stopped</h2>
      {stopped.reasons.map((reason) => (
        <p key={reason} className="wrap-anywhere">
          {reason}
        </p>
      ))}
      <p className="text-[0.8125rem] text-muted-foreground">
        Do what it asks, then run the step again. Nothing that was already made is lost.
      </p>
      <button type="button" onClick={() => void again()} disabled={busy} className={quietAction}>
        Run this step again
      </button>
      {failure && <p className="font-semibold text-danger">{failure}</p>}
    </section>
  );
}

/** The Render tab: nothing yet, how far the making is, or the draft video. */
export function RenderTab({ episode, render }: { episode: EpisodeDetail; render: RenderOut | null }) {
  const making = makingOf(episode);

  if (making && !stoppedOf(episode)) {
    return (
      <section data-testid="render-making" className={card}>
        <h2 className="text-lg font-semibold">{making.heading}</h2>
        <p aria-live="polite" className="text-muted-foreground">
          {making.text}
        </p>
        {making.done !== null && making.total !== null && (
          <div
            role="progressbar"
            aria-label={making.heading}
            aria-valuemin={0}
            aria-valuemax={making.total}
            aria-valuenow={making.done}
            className="h-1.5 overflow-hidden rounded-full bg-border"
          >
            <div
              style={{ width: `${(making.done / making.total) * 100}%` }}
              className="h-full rounded-full bg-info"
            />
          </div>
        )}
        <p className="text-[0.8125rem] text-muted-foreground">
          The voice is recorded scene by scene, then every scene is drawn and the scenes are joined. The
          video appears here by itself.
        </p>
      </section>
    );
  }

  if (!render?.video_url) {
    return (
      <section data-testid="render-empty" className={card}>
        <h2 className="text-lg font-semibold">No video yet</h2>
        <p className="text-muted-foreground">
          {stoppedOf(episode)
            ? "The video appears here once the step that stopped has run again."
            : "The video appears here after the plan and the pictures are approved."}
        </p>
      </section>
    );
  }

  return (
    <section data-testid="render-video" className="flex flex-col items-start gap-3">
      <DraftVideo render={render} title={displayTitle(episode)} />
      <p className="text-[0.8125rem] text-muted-foreground">{renderCaption(render)}</p>
      {render.contact_sheet_url && (
        <a href={render.contact_sheet_url} target="_blank" rel="noreferrer" className={quietAction}>
          Open the contact sheet
        </a>
      )}
      <p className="max-w-xl text-[0.8125rem] text-muted-foreground">
        Quality checks, the review and the export are not built yet. This draft is where an episode
        ends for now.
      </p>
    </section>
  );
}
