// Button looks shared by the screens. They keep the global focus outline (UX-04) and are
// 44 px tall, the smallest comfortable touch target.

/** The one next action of a screen, in the accent colour. */
export const primaryAction =
  "inline-flex h-11 items-center justify-center rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:cursor-default disabled:opacity-60";

/** Everything else. */
export const quietAction =
  "inline-flex h-11 items-center justify-center rounded-lg border bg-transparent px-4 text-sm font-medium text-foreground hover:bg-raised disabled:cursor-default disabled:opacity-60";
