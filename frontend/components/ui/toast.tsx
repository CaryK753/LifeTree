"use client";

import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { cva, type VariantProps } from "class-variance-authority";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const ToastProviderContext = ToastPrimitive.Provider;

/**
 * Toast variants — themed for both light and dark mode.
 *
 * Each variant uses dark text on a tinted background in light mode, and
 * light text on a tinted background in dark mode (via `dark:` prefixes).
 * This keeps contrast readable in both themes — the original `text-emerald-100`
 * etc. was near-invisible on the pale light-mode tinted backgrounds.
 */
export const toastVariants = cva(
  "group pointer-events-auto relative flex w-full items-start justify-between gap-3 rounded-lg border p-4 pr-8 shadow-lg backdrop-blur-md transition-all " +
    // Open: slide down from top + fade in (the toast "drops in" from the
    // top edge of the viewport, where the Viewport is anchored).
    "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-4 " +
    // Closed: slide up toward top + fade out (mirror of the open
    // animation — feels like the toast is being "pulled back up").
    "data-[state=closed]:animate-out data-[state=closed]:fade-out-80 data-[state=closed]:slide-out-to-top-4",
  {
    variants: {
      variant: {
        default:
          "border-black/10 dark:border-white/10 bg-surface/95 text-zinc-800 dark:text-zinc-100",
        success:
          "border-emerald-500/30 bg-emerald-50/95 dark:bg-emerald-500/15 text-emerald-900 dark:text-emerald-100",
        error:
          "border-red-500/30 bg-red-50/95 dark:bg-red-500/15 text-red-900 dark:text-red-100",
        warning:
          "border-amber-500/30 bg-amber-50/95 dark:bg-amber-500/15 text-amber-900 dark:text-amber-100",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

type ToastVariant = "default" | "success" | "error" | "warning";
interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant?: ToastVariant;
}

type ToastFn = (t: {
  title: string;
  description?: string;
  variant?: ToastVariant;
}) => void;

const ToastCtx = React.createContext<ToastFn | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<ToastItem[]>([]);

  const toast = React.useCallback<ToastFn>((t) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { id, ...t }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id));
    }, 4500);
  }, []);

  return (
    <ToastCtx.Provider value={toast}>
      <ToastProviderContext swipeDirection="up" duration={4500}>
        {children}
        {toasts.map((t) => (
          <ToastPrimitive.Root
            key={t.id}
            className={cn(toastVariants({ variant: t.variant }))}
          >
            <div className="flex-1 select-text">
              <ToastPrimitive.Title className="text-sm font-semibold select-text">
                {t.title}
              </ToastPrimitive.Title>
              {t.description && (
                <ToastPrimitive.Description className="mt-1 text-xs opacity-90 select-text whitespace-pre-wrap break-words">
                  {t.description}
                </ToastPrimitive.Description>
              )}
            </div>
            <ToastPrimitive.Close className="absolute right-2 top-2 rounded-md p-1 opacity-60 hover:opacity-100">
              <X className="h-3.5 w-3.5" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        {/*
          Viewport positioned at top-right. Most apps put toasts at bottom-right,
          but on smaller screens the composer / input area lives at the bottom —
          toasts there would overlap and get dismissed by stray clicks. Top-right
          keeps them visible and out of the way of typing.

          In PWA mode (viewport-fit: cover) the top-right corner may sit
          under the status bar / notch on iOS. The ``--toast-top`` CSS var
          is overridden in globals.css under ``html.pwa`` to respect
          safe-area-inset-top.
        */}
        <ToastPrimitive.Viewport
          className="fixed right-4 z-[100] flex max-h-screen w-full flex-col gap-2 p-4 sm:w-96"
          style={{ top: "var(--toast-top, 1rem)" }}
        />
      </ToastProviderContext>
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastFn {
  const ctx = React.useContext(ToastCtx);
  return React.useCallback<ToastFn>(
    (t) => {
      if (ctx) ctx(t);
    },
    [ctx]
  );
}
