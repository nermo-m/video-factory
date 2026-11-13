"use client";

import { type FormEvent, useId, useState } from "react";

import { type AssetList, type AssetOut, type EpisodeDetail, postEpisodeAssetRegenerate } from "@/api/client";
import { failureOf, unwrap } from "@/lib/api-error";
import { primaryAction, quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { type Scene, pictureName, picturesSummary, shownIn } from "@/lib/workspace";

const card = "flex max-w-xl flex-col gap-3 rounded-lg border bg-card p-5 sm:p-6";

const ORIGIN: Record<AssetOut["origin"], string> = {
  generated: "Generated",
  library: "From the library",
  uploaded: "Your upload",
};

const RIGHTS: Record<string, { label: string; look: string }> = {
  cleared: { label: "Rights cleared", look: "text-success" },
  needs_review: { label: "Rights need your review", look: "text-warning" },
  blocked: { label: "Rights blocked", look: "text-danger" },
};

function Spinner() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={3}
      strokeLinecap="round"
      aria-hidden="true"
      className="size-4 shrink-0 animate-spin"
    >
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}

/** Make again: an optional note, then one new version of the picture (FR-06). */
function MakeAgain({
  episodeId,
  asset,
  reload,
}: {
  episodeId: string;
  asset: AssetOut;
  reload: () => Promise<void>;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function send(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    const text = note.trim();
    try {
      unwrap(
        await postEpisodeAssetRegenerate({
          path: { episode_id: episodeId, asset_id: asset.id },
          body: text ? { note: text } : {},
        }),
        "The picture could not be made again. Try again.",
      );
      setOpen(false);
      setNote("");
      await reload();
    } catch (error) {
      setFailure(failureOf(error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className={quietAction}>
        Make again
      </button>
    );
  }
  return (
    <form onSubmit={(event) => void send(event)} className="flex flex-col gap-2.5">
      <label htmlFor={`${id}-note`} className="text-xs font-semibold text-muted-foreground">
        What should be different? (optional)
      </label>
      <textarea
        id={`${id}-note`}
        rows={2}
        maxLength={500}
        value={note}
        onChange={(event) => setNote(event.target.value)}
        className="min-h-11 w-full resize-y rounded-lg border bg-raised px-3.5 py-2.5 text-base sm:text-sm"
      />
      <p className="text-xs text-muted-foreground">
        Uses one picture of your plan. The picture it replaces is kept as an earlier version.
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="submit" disabled={busy} className={primaryAction}>
          Make a new one
        </button>
        <button type="button" onClick={() => setOpen(false)} disabled={busy} className={quietAction}>
          Cancel
        </button>
      </div>
      {failure && (
        <p role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
          {failure}
        </p>
      )}
    </form>
  );
}

function Picture({
  episodeId,
  asset,
  scenes,
  reload,
}: {
  episodeId: string;
  asset: AssetOut;
  scenes: Scene[];
  reload: () => Promise<void>;
}) {
  const id = useId();
  const name = pictureName(asset.id);
  const rights = asset.rights_status ? RIGHTS[asset.rights_status] : undefined;
  const waiting =
    asset.origin === "uploaded"
      ? `Waits for your upload${asset.filename ? `: ${asset.filename}` : ""}`
      : asset.origin === "library"
        ? "Not in the library"
        : "Not made yet";

  return (
    <li
      aria-labelledby={id}
      className="flex min-w-0 flex-col gap-3 rounded-xl border bg-card p-3.5"
    >
      <div className="relative flex aspect-4/3 items-center justify-center overflow-hidden rounded-lg border bg-surface">
        {asset.image_url ? (
          // The file is served by this app's own API, so a plain image element is enough.
          <img src={asset.image_url} alt={name} loading="lazy" className="size-full object-cover" />
        ) : (
          <span className="px-4 text-center text-[0.8125rem] text-muted-foreground">
            {asset.generating ? "" : waiting}
          </span>
        )}
        {asset.generating && (
          <span
            role="status"
            className="absolute inset-x-2 bottom-2 inline-flex items-center justify-center gap-2 rounded-lg bg-chip-working px-3 py-2 text-xs font-semibold text-info"
          >
            <Spinner />
            Being made
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <h3 id={id} className="text-[0.9375rem] font-semibold wrap-anywhere">
          {name}
        </h3>
        <span className="rounded-md bg-raised px-1.5 py-0.5 text-[0.6875rem] font-semibold text-muted-foreground">
          {ORIGIN[asset.origin]}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{shownIn(asset.used_in, scenes)}</p>
      {asset.prompt && <p className="line-clamp-4 text-[0.8125rem] wrap-anywhere">{asset.prompt}</p>}
      {rights && <p className={cn("text-xs font-semibold", rights.look)}>{rights.label}</p>}
      {asset.origin === "generated" && !asset.generating && (
        <MakeAgain episodeId={episodeId} asset={asset} reload={reload} />
      )}
    </li>
  );
}

/**
 * The Assets tab (design doc section 11.2): every picture of the episode with where it
 * comes from, its prompt and the scenes that show it. A generated picture can be made
 * again. Upload, the rights flag and clips arrive with the rest of the asset library.
 */
export function AssetsTab({
  episode,
  assets,
  scenes,
  reload,
}: {
  episode: EpisodeDetail;
  assets: AssetList | null;
  scenes: Scene[];
  reload: () => Promise<void>;
}) {
  if (!assets || assets.assets.length === 0) {
    return (
      <section data-testid="assets-empty" className={card}>
        <h2 className="text-lg font-semibold">No pictures yet</h2>
        <p className="text-muted-foreground">
          {assets
            ? "This plan shows no pictures."
            : "The pictures appear here after the plan is approved."}
        </p>
      </section>
    );
  }
  return (
    <section data-testid="assets" className="flex flex-col gap-4">
      <p className="text-[0.8125rem] text-muted-foreground">{picturesSummary(assets.assets)}</p>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {assets.assets.map((asset) => (
          <Picture key={asset.id} episodeId={episode.id} asset={asset} scenes={scenes} reload={reload} />
        ))}
      </ul>
      <p className="max-w-xl text-[0.8125rem] text-muted-foreground">
        Uploading your own pictures and clearing rights are not built yet. A picture&apos;s rights
        are checked before a video can be exported.
      </p>
    </section>
  );
}
