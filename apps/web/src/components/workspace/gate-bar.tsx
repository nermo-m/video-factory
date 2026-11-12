"use client";

import { type FormEvent, useEffect, useId, useRef, useState } from "react";

import { type EpisodeDetail, postEpisodeApprove, postEpisodeReject } from "@/api/client";
import { failureOf, unwrap } from "@/lib/api-error";
import { primaryAction, quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";

const WAITING: Record<string, string> = {
  review: "The video waits for your review. The screen for that is not built yet.",
};

/**
 * The gate bar (design doc sections 11.2 and 11.5): shown while the episode waits for the
 * owner. At the plan gate it offers Approve plan, the one accent action of the screen,
 * and Request changes, which needs a comment. On a phone it stays above the bottom bar.
 */
export function GateBar({ episode, reload }: { episode: EpisodeDetail; reload: () => Promise<void> }) {
  const id = useId();
  const path = { episode_id: episode.id };
  const [asking, setAsking] = useState(false);
  const [comment, setComment] = useState("");
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (asking) {
      field.current?.focus();
    }
  }, [asking]);

  if (!episode.awaiting_approval) {
    return null;
  }

  async function act(request: () => Promise<unknown>) {
    setBusy(true);
    setFailure(null);
    try {
      await request();
      await reload();
    } catch (error) {
      setFailure(failureOf(error).message);
    } finally {
      setBusy(false);
    }
  }

  function approve() {
    return act(async () => unwrap(await postEpisodeApprove({ path }), "The plan could not be approved. Try again."));
  }

  function sendBack(event: FormEvent) {
    event.preventDefault();
    const text = comment.trim();
    if (!text) {
      setMissing(true);
      field.current?.focus();
      return;
    }
    void act(async () =>
      unwrap(await postEpisodeReject({ path, body: { comment: text } }), "The plan could not be sent back. Try again."),
    );
  }

  const frame =
    "sticky bottom-19 z-10 flex flex-col gap-3 rounded-lg border border-primary bg-card px-4 py-3.5 shadow-[0_-6px_18px_rgb(0_0_0/0.35)] sm:static sm:shadow-none";

  if (episode.gate === "assets") {
    // The Assets tab, where each picture is looked at, arrives with the asset library.
    // Until then a plan uses library pictures only, so there is nothing new to compare.
    return (
      <div data-testid="gate-bar" className={frame}>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <p className="sm:min-w-56 sm:grow">
            The pictures are ready. This plan uses pictures from the library, so nothing new was
            made. Approving starts the voice and the render.
          </p>
          <button
            type="button"
            onClick={() =>
              void act(async () =>
                unwrap(await postEpisodeApprove({ path }), "The pictures could not be approved. Try again."),
              )
            }
            disabled={busy}
            className={primaryAction}
          >
            Approve pictures
          </button>
        </div>
        {failure && (
          <p role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
            {failure}
          </p>
        )}
      </div>
    );
  }
  if (episode.gate !== "plan") {
    return (
      <div data-testid="gate-bar" className={frame}>
        <p>{WAITING[episode.gate ?? ""] ?? "This episode waits for your approval."}</p>
      </div>
    );
  }

  return (
    <div data-testid="gate-bar" className={frame}>
      {asking ? (
        <form onSubmit={sendBack} className="flex flex-col gap-3">
          <label htmlFor={`${id}-reason`} className="font-semibold">
            What should be different?
          </label>
          <textarea
            id={`${id}-reason`}
            ref={field}
            rows={2}
            maxLength={4000}
            value={comment}
            onChange={(event) => {
              setComment(event.target.value);
              setMissing(false);
            }}
            aria-invalid={missing || undefined}
            className={cn(
              "w-full resize-y rounded-lg border bg-raised px-3.5 py-2.5 text-base sm:text-sm",
              missing && "border-danger",
            )}
          />
          <p className="text-xs text-muted-foreground">
            {missing ? (
              <span className="font-semibold text-danger">Say what should be different first.</span>
            ) : (
              "The plan is written again with your comment and comes back here."
            )}
          </p>
          <div className="grid grid-cols-2 gap-3 sm:flex sm:justify-end">
            <button type="button" onClick={() => setAsking(false)} className={quietAction}>
              Cancel
            </button>
            <button type="submit" disabled={busy} className={quietAction}>
              Send back
            </button>
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <p className="sm:min-w-56 sm:grow">The plan is ready. Nothing is generated until you approve.</p>
          <div className="grid grid-cols-2 gap-3 sm:flex">
            <button type="button" onClick={() => setAsking(true)} disabled={busy} className={quietAction}>
              Request changes
            </button>
            <button type="button" onClick={() => void approve()} disabled={busy} className={primaryAction}>
              Approve plan
            </button>
          </div>
        </div>
      )}
      {failure && (
        <p role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
          {failure}
        </p>
      )}
    </div>
  );
}
