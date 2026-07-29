"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

// ---------- Streaming thinking dots ----------

export function ThinkingDots({ label }: { label?: string }) {
  const t = useT();
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500">
      <span className="flex gap-0.5">
        <span className="h-1.5 w-1.5 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
        <span className="h-1.5 w-1.5 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
        <span className="h-1.5 w-1.5 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
      </span>
      <span>{label ?? t("chat.tool.thinking")}</span>
    </span>
  );
}

// ---------- Typewriter cursor ----------

/**
 * Streaming cursor shown at the tail of an in-flight assistant message.
 * Purely decorative — the parent toggles it via `visible`.
 */
export function StreamingCursor({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block w-1.5 h-3.5 ml-0.5 bg-brand-400 align-middle animate-pulse-soft rounded-sm",
        className
      )}
      aria-hidden
    />
  );
}

// ---------- Chat Minimap (conversation overview) ----------

/**
 * Floating pill-shaped conversation overview.
 *
 * Collapsed: a small vertical pill on the right edge of the chat thread,
 * showing a few horizontal lines that represent the conversation density.
 *
 * On hover: the pill expands into a panel listing all user messages and
 * their edit versions. Clicking any entry scrolls to that message.
 *
 * Hidden in PWA mode (screen too narrow for a floating sidebar).
 */
export function ChatMinimap({
  userMessages,
  onJumpTo,
}: {
  userMessages: Array<{
    index: number;
    id: string;
    content: string;
    versions?: Array<{ content: string; createdAt: number }>;
  }>;
  onJumpTo: (index: number) => void;
}) {
  const [hovered, setHovered] = useState(false);

  if (userMessages.length === 0) return null;

  // Collapsed pill: a few horizontal lines representing messages.
  // Show at most 5 lines, capped by the actual message count.
  const lineCount = Math.min(5, userMessages.length);

  return (
    <div
      className="absolute right-4 top-1/2 -translate-y-1/2 z-20"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Collapsed pill — always visible, expands on hover.
          Rounded rectangle (not full pill) per design spec. */}
      <div
        className={cn(
          "flex flex-col gap-1 p-2 rounded-lg",
          "bg-emerald-500/15 dark:bg-emerald-400/15 backdrop-blur-md",
          "border border-emerald-500/20 dark:border-emerald-400/20",
          "transition-all duration-300 cursor-pointer",
          hovered ? "opacity-0 pointer-events-none" : "opacity-100"
        )}
      >
        {Array.from({ length: lineCount }).map((_, i) => (
          <div
            key={i}
            className="w-4 h-0.5 rounded-full bg-emerald-600/70 dark:bg-emerald-300/80"
          />
        ))}
      </div>

      {/* Expanded panel — slides in on hover */}
      <div
        className={cn(
          "absolute right-0 top-1/2 -translate-y-1/2",
          "flex flex-col gap-1 p-2 max-h-[60vh] overflow-y-auto scrollbar-thin",
          "rounded-2xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl",
          "border border-black/10 dark:border-white/10 shadow-xl",
          "min-w-[200px] max-w-[280px]",
          "transition-all duration-300 origin-right",
          hovered
            ? "opacity-100 scale-100 pointer-events-auto"
            : "opacity-0 scale-75 pointer-events-none"
        )}
      >
        {userMessages.map((msg) => {
          const versionCount = (msg.versions?.length ?? 0) + 1;
          return (
            <div key={msg.id} className="space-y-0.5">
              {/* Current version */}
              <button
                onClick={() => {
                  onJumpTo(msg.index);
                  setHovered(false);
                }}
                className={cn(
                  "w-full text-left px-2.5 py-1.5 rounded-lg text-xs",
                  "hover:bg-brand-500/10 transition-colors",
                  "text-zinc-700 dark:text-zinc-200",
                  "border border-transparent hover:border-brand-500/20"
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span className="w-1 h-1 rounded-full bg-brand-500 shrink-0" />
                  <span className="truncate">{msg.content.slice(0, 60) || "…"}</span>
                </div>
                {versionCount > 1 && (
                  <span className="ml-2.5 text-[9px] text-zinc-400">
                    +{versionCount - 1} version{versionCount > 2 ? "s" : ""}
                  </span>
                )}
              </button>
              {/* Previous versions (edited messages) */}
              {msg.versions?.map((v, vi) => (
                <button
                  key={vi}
                  onClick={() => {
                    onJumpTo(msg.index);
                    setHovered(false);
                  }}
                  className={cn(
                    "w-full text-left px-2.5 py-1 ml-3 rounded-lg text-[11px]",
                    "hover:bg-zinc-500/10 transition-colors",
                    "text-zinc-400 dark:text-zinc-500",
                    "border-l border-zinc-300 dark:border-zinc-700"
                  )}
                >
                  <span className="truncate block">{v.content.slice(0, 50) || "…"}</span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
