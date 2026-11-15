import { CHANGE_GROUPS, type Change, changePlace } from "@/lib/director";
import type { Scene } from "@/lib/workspace";
import { cn } from "@/lib/utils";

const GROUP_LOOK: Record<string, string> = {
  added: "text-info",
  changed: "text-warning",
  not_possible: "text-danger",
};

/**
 * What the studio changed (Director mode): everything in the plan that is not the owner's
 * own words, so nothing is changed quietly. Three groups: what was filled in, what had to
 * be altered, and what was asked for and cannot be done yet. An empty list says so in
 * words: it is good news, not a missing panel.
 */
export function ChangesPanel({ changes, scenes }: { changes: Change[]; scenes: Scene[] }) {
  return (
    <section
      aria-labelledby="changes-heading"
      data-testid="changes-panel"
      className="flex min-w-0 flex-col gap-3 rounded-lg border bg-card px-4 py-4 sm:px-4.5"
    >
      <h2
        id="changes-heading"
        className="font-sans text-xs font-semibold tracking-[0.06em] text-muted-foreground uppercase"
      >
        What the studio changed
      </h2>
      {changes.length === 0 ? (
        <p className="text-[0.9375rem]">
          Nothing was changed. The plan is your prompt as you wrote it.
        </p>
      ) : (
        CHANGE_GROUPS.map(([kind, label]) => {
          const group = changes.filter((change) => change.kind === kind);
          if (group.length === 0) {
            return null;
          }
          return (
            <div key={kind} className="flex flex-col gap-2">
              <h3 className={cn("text-[0.8125rem] font-semibold", GROUP_LOOK[kind])}>
                {label} <span className="font-mono text-xs font-medium">{group.length}</span>
              </h3>
              <ul className="flex flex-col gap-2">
                {group.map((change, index) => (
                  <li key={index} className="rounded-md bg-raised px-3 py-2.5 wrap-anywhere">
                    <p className="text-[0.9375rem]">
                      <span className="mr-2 font-mono text-xs text-muted-foreground">
                        {changePlace(change, scenes)}
                      </span>
                      {change.what}
                    </p>
                    <p className="mt-1 text-[0.8125rem] text-muted-foreground">{change.why}</p>
                  </li>
                ))}
              </ul>
            </div>
          );
        })
      )}
    </section>
  );
}
