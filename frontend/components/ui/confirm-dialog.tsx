"use client";

/**
 * ConfirmDialog — a reusable replacement for the native ``window.confirm``.
 *
 * Built on top of the existing Radix Dialog primitives so it matches the
 * rest of the app's modal UX (overlay, animation, focus trap, ESC close).
 *
 * Usage:
 *   const [state, setState] = useState<{ open: boolean; onConfirm?: () => void }>({ open: false });
 *   <ConfirmDialog
 *     open={state.open}
 *     onOpenChange={(o) => setState((s) => ({ ...s, open: o }))}
 *     title={t("common.confirmDelete")}
 *     description={t("items.deleteConfirm", { name })}
 *     confirmLabel={t("common.delete")}
 *     cancelLabel={t("common.cancel")}
 *     variant="danger"
 *     onConfirm={() => { doDelete(); setState({ open: false }); }}
 *   />
 *
 * For imperative-style usage (closer to the old ``confirm()`` ergonomics),
 * use ``useConfirm`` which returns a ``confirm(options)`` promise.
 */

import { useCallback, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface ConfirmOptions {
  title?: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "danger";
}

interface ConfirmDialogProps extends ConfirmOptions {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  onConfirm,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  variant = "default",
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" hideClose>
        <DialogHeader>
          {title && <DialogTitle>{title}</DialogTitle>}
          {description && (
            <DialogDescription className="whitespace-pre-line">
              {description}
            </DialogDescription>
          )}
        </DialogHeader>
        <DialogFooter className="mt-2">
          <DialogClose
            className={cn(
              "inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium transition-colors",
              "border border-black/10 dark:border-white/10 text-zinc-600 dark:text-zinc-300",
              "hover:bg-black/5 dark:hover:bg-white/5"
            )}
          >
            {cancelLabel}
          </DialogClose>
          <button
            type="button"
            onClick={() => {
              onConfirm();
              onOpenChange(false);
            }}
            className={cn(
              "inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium transition-colors text-white",
              variant === "danger"
                ? "bg-red-600 hover:bg-red-500"
                : "bg-brand-600 hover:bg-brand-500"
            )}
          >
            {confirmLabel}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Imperative hook ----------

/**
 * ``useConfirm`` — promise-based confirm dialog.
 *
 * Replaces ``window.confirm`` with an async call that resolves to ``true``
 * / ``false``. Mount ``<ConfirmRoot />`` once anywhere in the tree (it
 * renders null when idle), then call ``confirm(options)`` from event
 * handlers.
 *
 *   const confirm = useConfirm();
 *   async function handleDelete() {
 *     if (!(await confirm({ title: "Delete?", variant: "danger" }))) return;
 *     doDelete();
 *   }
 */
interface ConfirmState extends ConfirmOptions {
  open: boolean;
  resolve?: (v: boolean) => void;
}

export function useConfirm() {
  const [state, setState] = useState<ConfirmState>({ open: false });
  const queueRef = useRef<((v: boolean) => void) | null>(null);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      queueRef.current = resolve;
      setState({ ...options, open: true });
    });
  }, []);

  const close = useCallback((result: boolean) => {
    setState((s) => ({ ...s, open: false }));
    queueRef.current?.(result);
    queueRef.current = null;
  }, []);

  const ConfirmRoot = (
    <ConfirmDialog
      open={state.open}
      onOpenChange={(o) => {
        if (!o) close(false);
      }}
      title={state.title}
      description={state.description}
      confirmLabel={state.confirmLabel}
      cancelLabel={state.cancelLabel}
      variant={state.variant}
      onConfirm={() => close(true)}
    />
  );

  return { confirm, ConfirmRoot };
}
