"use client";

import { type FormEvent, useEffect, useId, useState } from "react";

import {
  type PlanOut,
  type RevisionOut,
  type SpecOut,
  getEpisodeRevision,
  postEpisodeRevise,
  postEpisodeReviseApply,
  putEpisodeSpec,
} from "@/api/client";
import { type ApiFailure, ApiFailure as Failure, failureOf, unwrap } from "@/lib/api-error";
import { quietAction } from "@/lib/styles";
import { useIsDesktop } from "@/lib/use-media";
import { cn } from "@/lib/utils";
import { type Claim, type Scene, type Spec, changeLabel, changeText, safeLink } from "@/lib/workspace";

import { Problems, SceneCard } from "./scene-card";

const sectionTitle = "font-sans text-xs font-semibold tracking-[0.06em] text-muted-foreground uppercase";

function Brief({ brief }: { brief: PlanOut["brief"] }) {
  const id = useId();
  const text = (key: string) => (typeof brief?.[key] === "string" ? (brief[key] as string) : "");
  const rows = [
    ["Lesson", text("lesson")],
    ["Angle", text("angle")],
    ["Audience", text("audience")],
  ].filter(([, value]) => value);

  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:px-4.5">
      <h2 id={id} className={sectionTitle}>
        Brief
      </h2>
      {rows.length === 0 ? (
        <p className="text-muted-foreground">The brief of this episode is not available.</p>
      ) : (
        <dl className="flex flex-col gap-2.5">
          {rows.map(([label, value]) => (
            <div key={label} className="grid gap-1 sm:grid-cols-[6rem_minmax(0,1fr)]">
              <dt className="text-[0.8125rem] text-muted-foreground">{label}</dt>
              <dd className="wrap-anywhere">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

function Claims({ claims }: { claims: Claim[] }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:px-4.5">
      <h2 id={id} className={sectionTitle}>
        Claims
      </h2>
      {claims.length === 0 ? (
        <p className="text-muted-foreground">This plan states no facts that need a source.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {claims.map((claim, index) => {
            const link = safeLink(claim.source_url);
            const name = claim.source_name?.trim() || claim.source_url || "Source";
            return (
              <li key={claim.id ?? index} className="flex flex-col gap-0.5">
                <p className="wrap-anywhere">{claim.text}</p>
                <p className="text-[0.8125rem] text-muted-foreground">
                  {link ? (
                    <a
                      href={link}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex min-h-11 items-center text-info underline underline-offset-2 wrap-anywhere"
                    >
                      {name}
                    </a>
                  ) : (
                    <span className="wrap-anywhere">{name}</span>
                  )}
                  {claim.source_date && <span>, {claim.source_date}</span>}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** The estimated length against the target. Red, and in words, when it does not fit. */
function Duration({ plan }: { plan: PlanOut }) {
  if (plan.estimated_total_s === null) {
    return null;
  }
  const fits = plan.fits !== false;
  const verdict = fits
    ? ""
    : plan.estimated_total_s > plan.target_duration_s
      ? ", too long"
      : ", too short";
  return (
    <div data-testid="duration" data-fits={fits} className="flex flex-col gap-2">
      <div className="flex flex-wrap justify-between gap-x-4 text-xs text-muted-foreground">
        <span>Planned length</span>
        <span data-testid="duration-value" className={cn("font-semibold", fits ? "text-success" : "text-danger")}>
          about {plan.estimated_total_s} s of {plan.target_duration_s} s{verdict}
        </span>
      </div>
      <div aria-hidden="true" className="flex h-2 gap-[3px]">
        {plan.scenes.map((scene, index) => (
          <span
            key={scene.id}
            style={{ flexGrow: Math.max(scene.estimated_s, 0.5) }}
            className={cn("basis-0 rounded-full", fits ? "bg-info" : "bg-danger", index % 2 === 1 && "opacity-70")}
          />
        ))}
      </div>
      {!fits && (
        <p className="text-xs text-muted-foreground">
          A plan for {plan.target_duration_s} seconds should come to between {plan.shortest_s} and{" "}
          {plan.longest_s} seconds. This is an estimate from the word count. The voice decides the
          real length.
        </p>
      )}
    </div>
  );
}

function JsonPanel({ spec, onSave }: { spec: SpecOut; onSave: (spec: Spec) => Promise<void> }) {
  // Raw JSON can be edited from 1024 px up (design doc section 11.5). Below, it is read only.
  const wide = useIsDesktop();
  const [text, setText] = useState(() => JSON.stringify(spec.spec, null, 2));
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      setFailure(new Failure(`This is not valid JSON: ${error instanceof Error ? error.message : "it cannot be read"}`));
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      await onSave(parsed as Spec);
    } catch (error) {
      setFailure(failureOf(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form data-testid="json-panel" onSubmit={(event) => void save(event)} className="flex min-w-0 flex-col gap-3">
      <textarea
        aria-label="Spec as JSON"
        value={text}
        readOnly={!wide}
        spellCheck={false}
        rows={24}
        onChange={(event) => setText(event.target.value)}
        className="w-full resize-y rounded-lg border bg-raised p-3 font-mono text-xs leading-relaxed whitespace-pre"
      />
      {failure && <Problems failure={failure} />}
      {wide ? (
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={saving} className={cn(quietAction, "border-info")}>
            {saving ? "Checking…" : "Save JSON"}
          </button>
          <p className="text-xs text-muted-foreground">
            It is checked against the spec schema and the theme before it is stored as a new version.
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Editing the JSON needs a screen at least 1024 px wide. Reading it works here.
        </p>
      )}
    </form>
  );
}

const DONE = new Set(["succeeded", "failed", "cancelled"]);
const REVISION_POLL_MS = 1_500;

function Revise({ episodeId, onApplied }: { episodeId: string; onApplied: () => Promise<void> }) {
  const id = useId();
  const path = { episode_id: episodeId };
  const [comment, setComment] = useState("");
  const [missing, setMissing] = useState(false);
  const [asking, setAsking] = useState(false);
  const [revision, setRevision] = useState<RevisionOut | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [applying, setApplying] = useState(false);
  const [waited, setWaited] = useState(0);
  const waiting = revision !== null && !DONE.has(revision.status);
  const jobId = revision?.job_id;

  // Follow the proposal until the planner has answered.
  useEffect(() => {
    if (!waiting || !jobId) {
      return;
    }
    let cancelled = false;
    const started = Date.now();
    const timer = window.setInterval(() => {
      setWaited(Math.round((Date.now() - started) / 1000));
      void getEpisodeRevision({ path: { episode_id: episodeId, job_id: jobId } }).then((answer) => {
        if (!cancelled && answer.data) {
          setRevision(answer.data);
        }
      });
    }, REVISION_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [waiting, jobId, episodeId]);

  async function propose(event: FormEvent) {
    event.preventDefault();
    const text = comment.trim();
    if (!text) {
      setMissing(true);
      return;
    }
    setAsking(true);
    setFailure(null);
    setWaited(0);
    try {
      setRevision(
        unwrap(await postEpisodeRevise({ path, body: { comment: text } }), "The change could not be asked for. Try again."),
      );
    } catch (error) {
      setRevision(null);
      setFailure(failureOf(error));
    } finally {
      setAsking(false);
    }
  }

  async function apply() {
    if (!revision) {
      return;
    }
    setApplying(true);
    setFailure(null);
    try {
      unwrap(
        await postEpisodeReviseApply({ path, body: { job_id: revision.job_id } }),
        "The change could not be applied. Ask for it again.",
      );
      await onApplied();
      setRevision(null);
      setComment("");
    } catch (error) {
      setFailure(failureOf(error));
    } finally {
      setApplying(false);
    }
  }

  const ready = revision?.status === "succeeded";
  const problem =
    failure?.message ??
    (revision && DONE.has(revision.status) && !(ready && revision.can_apply)
      ? (revision.message ?? "The proposal could not be written. Ask again, in other words.")
      : null);

  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:px-4.5">
      <h2 id={id} className={sectionTitle}>
        Ask for a change
      </h2>
      <form onSubmit={(event) => void propose(event)} className="flex flex-col gap-3">
        <label htmlFor={`${id}-comment`} className="font-semibold">
          What should change?
        </label>
        <textarea
          id={`${id}-comment`}
          rows={2}
          maxLength={4000}
          value={comment}
          onChange={(event) => {
            setComment(event.target.value);
            setMissing(false);
          }}
          aria-invalid={missing || undefined}
          placeholder="Make the hook text bigger and slow the second scene."
          className={cn(
            "w-full resize-y rounded-lg border bg-raised px-3.5 py-2.5 text-base placeholder:text-muted-foreground/70 sm:text-sm",
            missing && "border-danger",
          )}
        />
        {missing && <p className="text-xs font-semibold text-danger">Say what should change first.</p>}
        <div>
          <button type="submit" disabled={asking || waiting} className={quietAction}>
            Propose changes
          </button>
        </div>
      </form>

      {(revision || failure) && (
        <div data-testid="proposal" className="flex flex-col gap-3 rounded-lg border border-info/60 bg-raised p-3.5">
          {waiting && (
            <p className="text-info">
              Writing the proposal… {waited > 0 && <span className="text-muted-foreground">{waited} s</span>}
            </p>
          )}
          {problem && (
            <p role="alert" className="rounded-lg border border-danger/50 bg-chip-failed px-3.5 py-3">
              {problem}
            </p>
          )}
          {ready && revision.can_apply && (
            <>
              <p className="font-semibold wrap-anywhere">{revision.summary}</p>
              <ul className="flex flex-col gap-2 text-[0.8125rem]">
                {(revision.changes ?? []).map((change) => {
                  const { verb, before, after } = changeText(change);
                  return (
                    <li key={`${change.op} ${change.path}`} className="flex flex-col gap-0.5">
                      <span className="text-muted-foreground">{changeLabel(change.path)}</span>
                      <span className="wrap-anywhere">
                        {verb && <span className="font-semibold">{verb}: </span>}
                        {before !== null && <del className={cn(after !== null && "text-muted-foreground")}>{before}</del>}
                        {before !== null && after !== null && <span aria-hidden="true"> → </span>}
                        {before !== null && after !== null && <span className="sr-only"> becomes </span>}
                        {after !== null && <ins className="font-semibold text-success no-underline">{after}</ins>}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
          {!waiting && (
            <div className="flex flex-wrap gap-3">
              {ready && revision.can_apply && (
                <button type="button" onClick={() => void apply()} disabled={applying} className={cn(quietAction, "border-info")}>
                  {applying ? "Applying…" : "Apply"}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setRevision(null);
                  setFailure(null);
                }}
                className={quietAction}
              >
                Discard
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

const AUTHORS: Record<string, string> = { model: "written by the planner", owner: "edited by you" };

/**
 * The Plan tab (design doc section 11.2): brief, claims with source links, the duration
 * bar, then the scenes in order. Raw JSON swaps the scene cards for the spec itself. A
 * comment in plain words becomes a proposal that shows what it would change before it is
 * applied. Every change is stored as a new version of the spec (FR-03).
 */
export function PlanTab({
  episodeId,
  spec,
  plan,
  reload,
}: {
  episodeId: string;
  spec: SpecOut;
  plan: PlanOut;
  reload: () => Promise<void>;
}) {
  const [json, setJson] = useState(false);
  const body = spec.spec as Spec;
  const scenes = body.scenes ?? [];
  const seconds = new Map(plan.scenes.map((scene) => [scene.id, scene.estimated_s]));

  async function store(next: Spec) {
    unwrap(
      await putEpisodeSpec({ path: { episode_id: episodeId }, body: next }),
      "The change could not be saved. Try again.",
    );
    await reload();
  }

  function saveScene(index: number) {
    return (scene: Scene) =>
      store({ ...body, scenes: scenes.map((old, position) => (position === index ? scene : old)) });
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[0.8125rem] text-muted-foreground">
          Version {spec.version}, {AUTHORS[spec.author] ?? spec.author}
        </p>
        <button
          type="button"
          aria-pressed={json}
          onClick={() => setJson((current) => !current)}
          className={cn(quietAction, json && "border-info bg-raised")}
        >
          Raw JSON
        </button>
      </div>

      <Brief brief={plan.brief} />
      <Claims claims={body.claims ?? []} />
      <Duration plan={plan} />

      {json ? (
        // A newer version starts the editor again with that version's text.
        <JsonPanel key={spec.version} spec={spec} onSave={store} />
      ) : (
        scenes.map((scene, index) => (
          <SceneCard
            key={scene.id}
            scene={scene}
            index={index}
            seconds={seconds.get(scene.id)}
            onSave={saveScene(index)}
          />
        ))
      )}

      <Revise episodeId={episodeId} onApplied={reload} />
    </div>
  );
}
