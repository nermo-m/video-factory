import type { ReactNode } from "react";

/** Page title row: one title, an optional short note beside it. */
export function PageHeader({ title, note }: { title: string; note?: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-3">
      <h1 className="text-[1.625rem] font-bold sm:text-[1.75rem]">{title}</h1>
      {note && <p className="text-muted-foreground">{note}</p>}
    </div>
  );
}

/**
 * Empty state (design doc section 11.5): one sentence on what belongs here and, when
 * there is something to do, one action.
 */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="flex max-w-xl flex-col items-start gap-3 rounded-lg border bg-card p-5 sm:p-6">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-muted-foreground">{children}</p>
      {action}
    </section>
  );
}

/** A note shown above content, for example while demo mode is on. */
export function Banner({ children }: { children: ReactNode }) {
  return (
    <p
      role="status"
      className="rounded-lg border border-info/40 bg-chip-working px-4 py-3 text-foreground"
    >
      {children}
    </p>
  );
}
