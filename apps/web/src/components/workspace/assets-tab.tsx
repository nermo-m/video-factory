"use client";

import { type ChangeEvent, type DragEvent, type FormEvent, useId, useState } from "react";

import {
  type AssetList,
  type AssetOut,
  type EpisodeDetail,
  type MatchOut,
  postEpisodeAssetRegenerate,
  postEpisodeAssetUpload,
  postEpisodeAssetsMatch,
} from "@/api/client";
import { failureOf, unwrap } from "@/lib/api-error";
import { primaryAction, quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";
import {
  NOT_A_PICTURE,
  PICTURE_MAX_BYTES,
  PICTURE_TOO_LARGE,
  PICTURE_TYPES,
  type Scene,
  pictureName,
  picturesSummary,
  pictureType,
  shownIn,
} from "@/lib/workspace";

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

/** A file that is refused here, before anything is sent. */
class Refused extends Error {}

/** Send one file as the new version of one picture. Throws what the API says. */
async function sendPicture(episodeId: string, assetId: string, file: File) {
  const type = pictureType(file);
  if (!type) {
    throw new Refused(NOT_A_PICTURE);
  }
  if (file.size > PICTURE_MAX_BYTES) {
    throw new Refused(PICTURE_TOO_LARGE);
  }
  unwrap(
    await postEpisodeAssetUpload({
      path: { episode_id: episodeId, asset_id: assetId },
      body: file,
      headers: { "Content-Type": type },
    }),
    "The picture could not be stored. Try again.",
  );
}

const messageOf = (error: unknown) => (error instanceof Refused ? error.message : failureOf(error).message);

/**
 * Upload your own: one file from the file picker becomes the picture's new version
 * (design doc section 11.2, "upload replacement"). The earlier file is kept.
 */
function UploadOwn({
  episodeId,
  asset,
  reload,
}: {
  episodeId: string;
  asset: AssetOut;
  reload: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function chosen(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // The same file can be chosen again after a failure.
    event.target.value = "";
    if (!file) {
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      await sendPicture(episodeId, asset.id, file);
      await reload();
    } catch (error) {
      setFailure(messageOf(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <label
        className={cn(
          quietAction,
          "cursor-pointer has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-(--ring)",
          busy && "cursor-default opacity-60",
        )}
      >
        {busy ? "Storing…" : asset.resolved ? "Upload your own" : "Upload this picture"}
        <input
          type="file"
          accept={PICTURE_TYPES}
          disabled={busy}
          onChange={(event) => void chosen(event)}
          aria-label={`Upload your own picture for ${pictureName(asset.id)}`}
          className="sr-only"
        />
      </label>
      {failure && (
        <p role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
          {failure}
        </p>
      )}
    </>
  );
}

interface Chosen {
  files: File[];
  matches: MatchOut[];
}

/**
 * Several files at once, matched to the pictures by their names (FR-07). The matches are
 * shown before anything is stored (design doc section 11.2).
 */
function MatchFiles({ episodeId, reload }: { episodeId: string; reload: () => Promise<void> }) {
  const [chosen, setChosen] = useState<Chosen | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [failures, setFailures] = useState<string[]>([]);
  const [stored, setStored] = useState<number | null>(null);

  async function look(files: File[]) {
    if (files.length === 0) {
      return;
    }
    setBusy(true);
    setFailures([]);
    setStored(null);
    try {
      const found = unwrap(
        await postEpisodeAssetsMatch({
          path: { episode_id: episodeId },
          body: { filenames: files.map((file) => file.name) },
        }),
        "The files could not be matched. Try again.",
      );
      setChosen({ files, matches: found.matches });
    } catch (error) {
      setChosen(null);
      setFailures([failureOf(error).message]);
    } finally {
      setBusy(false);
    }
  }

  async function store() {
    if (!chosen) {
      return;
    }
    setBusy(true);
    const failed: string[] = [];
    let done = 0;
    // One at a time: each file is checked and stored on its own, and the list stays in order.
    for (const [index, match] of chosen.matches.entries()) {
      const file = chosen.files[index];
      if (!match.asset_id || !file) {
        continue;
      }
      try {
        await sendPicture(episodeId, match.asset_id, file);
        done += 1;
      } catch (error) {
        failed.push(`${match.filename}: ${messageOf(error)}`);
      }
    }
    setChosen(null);
    setFailures(failed);
    setStored(done);
    setBusy(false);
    await reload();
  }

  function picked(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = "";
    void look(files);
  }

  function dropped(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setOver(false);
    if (!busy) {
      void look([...event.dataTransfer.files]);
    }
  }

  const matched = chosen?.matches.filter((match) => match.asset_id).length ?? 0;

  return (
    <section
      data-testid="match-files"
      aria-label="Your own pictures"
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={dropped}
      className={cn(
        "flex max-w-3xl flex-col items-start gap-3 rounded-xl border border-dashed p-4 sm:p-5",
        over && "border-info bg-chip-working",
      )}
    >
      <h2 className="text-[0.9375rem] font-semibold">Your own pictures</h2>
      <p className="text-[0.8125rem] text-muted-foreground">
        Choose several files at once, or drop them here. A file goes to the picture it is named after,
        for example <span className="font-mono">harbour.jpg</span> to Harbour. You see the matches before
        anything is stored.
      </p>
      {!chosen && (
        <label
          className={cn(
            quietAction,
            "cursor-pointer has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-(--ring)",
            busy && "cursor-default opacity-60",
          )}
        >
          {busy ? "Looking…" : "Choose files"}
          <input
            type="file"
            multiple
            accept={PICTURE_TYPES}
            disabled={busy}
            onChange={picked}
            aria-label="Choose your own pictures"
            className="sr-only"
          />
        </label>
      )}
      {chosen && (
        <>
          <ul aria-label="Matches" className="flex w-full flex-col gap-1.5 text-[0.8125rem]">
            {chosen.matches.map((match, index) => (
              <li key={`${index}-${match.filename}`} className="flex flex-wrap gap-x-2 wrap-anywhere">
                <span className="font-mono">{match.filename}</span>
                {match.asset_id ? (
                  <span className="font-semibold text-success">goes to {pictureName(match.asset_id)}</span>
                ) : (
                  <span className="text-warning">is left out. {match.why}</span>
                )}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void store()}
              disabled={busy || matched === 0}
              className={primaryAction}
            >
              {busy ? "Storing…" : `Use ${matched} ${matched === 1 ? "picture" : "pictures"}`}
            </button>
            <button type="button" onClick={() => setChosen(null)} disabled={busy} className={quietAction}>
              Cancel
            </button>
          </div>
        </>
      )}
      {stored !== null && stored > 0 && (
        <p role="status" className="text-[0.8125rem] font-semibold text-success">
          {stored} {stored === 1 ? "picture" : "pictures"} stored.
        </p>
      )}
      {failures.length > 0 && (
        <div role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
          {failures.map((failure) => (
            <p key={failure} className="wrap-anywhere">
              {failure}
            </p>
          ))}
        </div>
      )}
    </section>
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
          {asset.uploaded ? ORIGIN.uploaded : ORIGIN[asset.origin]}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{shownIn(asset.used_in, scenes)}</p>
      {asset.prompt && <p className="line-clamp-4 text-[0.8125rem] wrap-anywhere">{asset.prompt}</p>}
      {rights && <p className={cn("text-xs font-semibold", rights.look)}>{rights.label}</p>}
      {asset.origin === "generated" && !asset.generating && (
        <MakeAgain episodeId={episodeId} asset={asset} reload={reload} />
      )}
      {asset.origin !== "library" && !asset.generating && (
        <UploadOwn episodeId={episodeId} asset={asset} reload={reload} />
      )}
    </li>
  );
}

/**
 * The Assets tab (design doc section 11.2): every picture of the episode with where it
 * comes from, its prompt and the scenes that show it. A generated picture can be made
 * again, and the owner's own file can take the place of any picture that is not from the
 * library, one at a time or several matched by file name (FR-07). The rights flag and
 * clips arrive with the rest of the asset library.
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
      {assets.assets.some((asset) => asset.origin !== "library") && (
        <MatchFiles episodeId={episode.id} reload={reload} />
      )}
      <p className="max-w-xl text-[0.8125rem] text-muted-foreground">
        A picture of yours is stored as a new version, and the one it replaces is kept. Clearing
        rights is not built yet. A picture&apos;s rights are checked before a video can be exported.
      </p>
    </section>
  );
}
