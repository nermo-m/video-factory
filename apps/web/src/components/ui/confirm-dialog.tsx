"use client";

import { AlertDialog } from "radix-ui";

import { quietAction } from "@/lib/styles";
import { cn } from "@/lib/utils";

const dangerAction =
  "inline-flex h-11 items-center justify-center rounded-lg bg-danger px-5 text-sm font-semibold text-background hover:bg-danger/90 disabled:cursor-default disabled:opacity-60";

/**
 * Asks before something that cannot be undone. Focus starts on Cancel, so Enter or a
 * second tap never destroys anything by accident, and Escape cancels.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  busyLabel,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  busyLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <AlertDialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !busy) {
          onCancel();
        }
      }}
    >
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <AlertDialog.Content
          className={cn(
            "fixed top-1/2 left-1/2 z-50 flex w-110 max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2",
            "flex-col gap-4 rounded-xl border bg-surface p-5 shadow-[0_18px_48px_rgb(0_0_0/0.55)] sm:p-6",
          )}
        >
          <AlertDialog.Title asChild>
            <h2 className="text-lg font-bold wrap-anywhere">{title}</h2>
          </AlertDialog.Title>
          <AlertDialog.Description className="text-muted-foreground">{body}</AlertDialog.Description>
          <div className="flex flex-wrap justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <button type="button" disabled={busy} className={quietAction}>
                Cancel
              </button>
            </AlertDialog.Cancel>
            <button type="button" disabled={busy} onClick={onConfirm} className={dangerAction}>
              {busy ? busyLabel : confirmLabel}
            </button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
