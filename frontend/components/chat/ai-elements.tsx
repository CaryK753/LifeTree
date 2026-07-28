"use client";

import { useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Loader2,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/chat/markdown";
import { useT } from "@/lib/i18n/provider";
import type { ToolCall } from "@/lib/chat-store";

/**
 * Vercel AI SDK-style elements, adapted to our existing design tokens.
 *
 * These components are intentionally framework-agnostic and reusable:
 *   - <ToolInvocation> — single tool call with args/result
 *   - <ToolInvocations> — vertical list of tool calls
 *
 * Each component is a controlled component — the parent owns the state.
 * Streaming-friendly: pass `isRunning={true}` while a tool is in flight.
 */

// ---------- Tool invocation ----------

function isPrimitive(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function formatValue(value: unknown, maxLen = 200): string {
  if (isPrimitive(value)) {
    const s = value === null ? "null" : value === undefined ? "undefined" : String(value);
    return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
  }
  try {
    const s = JSON.stringify(value, null, 2);
    return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
  } catch {
    return String(value);
  }
}

export function ToolInvocation({ tool }: { tool: ToolCall }) {
  const t = useT();
  const [open, setOpen] = useState(false);

  const running = !tool.endedAt && tool.result === null && !tool.error;
  const failed = !!tool.error;
  const done = !!tool.endedAt && !failed;

  // Conversational Graph Building sync card labels
  const syncCards: Record<string, { label: string; icon: string; color: string }> = {
    update_user_profile: {
      label: "💡 画像与进度已同步更新",
      icon: "UserCheck",
      color: "border-brand-500/30 bg-brand-500/[0.08] text-brand-300",
    },
    create_scenario_branch: {
      label: "🌿 平行推演分支已创建",
      icon: "GitBranch",
      color: "border-emerald-500/30 bg-emerald-500/[0.08] text-emerald-300",
    },
    create_goal: {
      label: "🎯 决策目标实体已建立",
      icon: "Target",
      color: "border-amber-500/30 bg-amber-500/[0.08] text-amber-300",
    },
    create_pathway: {
      label: "🛣️ 实施路径实体已关联",
      icon: "Route",
      color: "border-sky-500/30 bg-sky-500/[0.08] text-sky-300",
    },
    update_requirement_status: {
      label: "✅ 达标节点已点亮",
      icon: "CheckCircle",
      color: "border-teal-500/30 bg-teal-500/[0.08] text-teal-300",
    },
    add_user_source: {
      label: "📎 信源已记录并排队验真",
      icon: "Paperclip",
      color: "border-indigo-500/30 bg-indigo-500/[0.08] text-indigo-300",
    },
  };

  const syncMeta = syncCards[tool.name];

  return (
    <div
      className={cn(
        "rounded-md border my-1.5 text-xs overflow-hidden transition-all",
        syncMeta ? syncMeta.color : "border-white/10 bg-white/[0.02]"
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 hover:bg-white/[0.03] transition-colors text-left"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 text-zinc-500 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-zinc-500 shrink-0" />
        )}
        {running ? (
          <Loader2 className="h-3 w-3 text-brand-300 animate-spin shrink-0" />
        ) : failed ? (
          <XCircle className="h-3 w-3 text-red-400 shrink-0" />
        ) : done ? (
          <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />
        ) : (
          <Wrench className="h-3 w-3 text-zinc-400 shrink-0" />
        )}
        <span className="font-mono truncate font-medium">
          {syncMeta ? syncMeta.label : tool.name}
        </span>
        <span className="text-[10px] text-zinc-400 shrink-0 ml-auto">
          {running
            ? t("chat.tool.running")
            : failed
            ? t("chat.tool.failed")
            : done
            ? t("chat.tool.done")
            : t("chat.tool.called")}
        </span>
      </button>
      {open && (
        <div className="border-t border-white/5 px-2.5 py-2 space-y-1.5 bg-black/20">
          {Object.keys(tool.args).length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-0.5">
                {t("chat.tool.args")}
              </div>
              <pre className="text-[11px] text-zinc-300 font-mono whitespace-pre-wrap break-words">
                {formatValue(tool.args, 600)}
              </pre>
            </div>
          )}
          {tool.result !== null && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-0.5">
                {t("chat.tool.result")}
              </div>
              <pre className="text-[11px] text-zinc-300 font-mono whitespace-pre-wrap break-words">
                {formatValue(tool.result, 800)}
              </pre>
            </div>
          )}
          {tool.error && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-red-400 mb-0.5">
                {t("chat.tool.failed")}
              </div>
              <pre className="text-[11px] text-red-300 font-mono whitespace-pre-wrap break-words">
                {tool.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolInvocations({ tools }: { tools: ToolCall[] }) {
  if (!tools || tools.length === 0) return null;
  return (
    <div className="my-1.5">
      {tools.map((tool) => (
        <ToolInvocation key={tool.id} tool={tool} />
      ))}
    </div>
  );
}

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

// ---------- Container ----------

export function ResponseContainer({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 animate-fade-in">{children}</div>
  );
}

// ---------- Markdown passthrough ----------

export function ResponseMarkdown({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  if (!content) return null;
  return <Markdown content={content} streaming={streaming} />;
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

// ---------- Thread (message list) ----------

/**
 * Vertical list of chat messages. Mirrors Vercel AI SDK's <Thread> element:
 * a scrollable container that lays out children with consistent spacing.
 *
 * Pass any renderable children — typically a list of <Message> components.
 */
export function Thread({
  children,
  className,
  autoScrollRef,
}: {
  children: ReactNode;
  className?: string;
  autoScrollRef?: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      ref={autoScrollRef}
      className={cn(
        "flex-1 overflow-y-auto px-4 sm:px-5 py-4 space-y-4",
        className
      )}
    >
      {children}
    </div>
  );
}

// ---------- Message (single row) ----------

/**
 * Single chat message row. Mirrors Vercel AI SDK's <Message> element.
 * Renders an avatar + content bubble; alignment flips for user vs. assistant.
 *
 * The `role` prop drives layout; the children are the bubble body so callers
 * can compose <ResponseContainer>, <ResponseMarkdown>, <ToolInvocations>
 * in any combination they need.
 */
export function Message({
  role,
  avatar,
  children,
  className,
}: {
  role: "user" | "assistant" | "system";
  avatar?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const t = useT();
  const isUser = role === "user";
  return (
    <div
      className={cn(
        "flex gap-3 animate-fade-in",
        isUser ? "flex-row-reverse" : "flex-row",
        className
      )}
    >
      <div
        className={cn(
          "h-7 w-7 rounded-full shrink-0 flex items-center justify-center text-[10px] font-medium",
          isUser
            ? "bg-brand-500/20 text-brand-200 border border-brand-500/30"
            : "bg-white dark:bg-zinc-800 border border-black/10 dark:border-white/10 shadow-sm"
        )}
      >
        {avatar ?? (isUser ? t("chat.me") : null)}
      </div>
      <div
        className={cn(
          "flex flex-col gap-1.5 max-w-[80%] sm:max-w-[75%]",
          isUser ? "items-end" : "items-start"
        )}
      >
        {children}
      </div>
    </div>
  );
}

// ---------- Composer (input area) ----------

/**
 * Composer / prompt input. Mirrors Vercel AI SDK's <Composer> element.
 *
 * The parent owns the input value and send handler; this component is a
 * controlled, presentational shell with an optional leading button slot
 * (e.g. paperclip for attachments) and a trailing send button.
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  disabled,
  placeholder,
  leading,
  trailing,
  textareaRef,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  placeholder?: string;
  leading?: ReactNode;
  trailing?: ReactNode;
  textareaRef?: React.RefObject<HTMLTextAreaElement | null>;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-end gap-2 rounded-xl bg-white/[0.02] border border-white/5",
        className
      )}
    >
      {leading}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSubmit();
          }
        }}
        rows={1}
        placeholder={placeholder}
        className="flex-1 resize-none bg-transparent px-2 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none max-h-40"
      />
      {trailing}
    </div>
  );
}
