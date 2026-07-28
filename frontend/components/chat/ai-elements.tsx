"use client";

import { useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Loader2,
  Wrench,
  UserCheck,
  GitBranch,
  Target,
  Route,
  CheckCircle,
  Paperclip,
  Brain,
  Network,
  ShieldAlert,
  Search,
  Globe,
  ListChecks,
  History,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/chat/markdown";
import { useT } from "@/lib/i18n/provider";
import type { ToolCall } from "@/lib/chat-store";

/**
 * Tool invocation card — renders a single tool call with its args/result.
 *
 * Icon strategy: each tool maps to a lucide icon (no emojis). The icon
 * serves double duty: it identifies the tool type at a glance and, for
 * sync cards, replaces the previous emoji prefix on the label.
 *
 * Failure detection: a tool is considered failed if either:
 *   - `tool.error` is set (streaming protocol explicitly signaled failure), or
 *   - `tool.result` is a dict containing an `error` key (backend convention:
 *     tools return `{"error": "..."}` on failure rather than raising).
 * When failed, the card shows a red X icon + "failed" status. The error
 * detail is shown in the expanded section, and the result (if any) is
 * hidden — the user sees the failure, not the raw payload.
 */

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

/** Detect failure from result shape: backend tools return {"error": ...}. */
function resultIsError(result: unknown): boolean {
  if (result && typeof result === "object" && "error" in result) {
    const v = (result as Record<string, unknown>).error;
    return typeof v === "string" && v.length > 0;
  }
  return false;
}

interface ToolMeta {
  icon: LucideIcon;
  /** i18n key for the label. If absent, tool.name is shown as-is. */
  labelKey?: string;
  color?: string;
}

const TOOL_META: Record<string, ToolMeta> = {
  update_user_profile: {
    icon: UserCheck,
    labelKey: "chat.tool.label.update_user_profile",
    color: "border-brand-500/30 bg-brand-500/[0.08] text-brand-300",
  },
  create_scenario_branch: {
    icon: GitBranch,
    labelKey: "chat.tool.label.create_scenario_branch",
    color: "border-emerald-500/30 bg-emerald-500/[0.08] text-emerald-300",
  },
  create_goal: {
    icon: Target,
    labelKey: "chat.tool.label.create_goal",
    color: "border-amber-500/30 bg-amber-500/[0.08] text-amber-300",
  },
  create_pathway: {
    icon: Route,
    labelKey: "chat.tool.label.create_pathway",
    color: "border-sky-500/30 bg-sky-500/[0.08] text-sky-300",
  },
  update_requirement_status: {
    icon: CheckCircle,
    labelKey: "chat.tool.label.update_requirement_status",
    color: "border-teal-500/30 bg-teal-500/[0.08] text-teal-300",
  },
  add_user_source: {
    icon: Paperclip,
    labelKey: "chat.tool.label.add_user_source",
    color: "border-indigo-500/30 bg-indigo-500/[0.08] text-indigo-300",
  },
  create_requirement: {
    icon: ListChecks,
    labelKey: "chat.tool.label.create_requirement",
    color: "border-sky-500/30 bg-sky-500/[0.08] text-sky-300",
  },
  create_risk_factor: {
    icon: ShieldAlert,
    labelKey: "chat.tool.label.create_risk_factor",
    color: "border-red-500/30 bg-red-500/[0.08] text-red-300",
  },
  remember: {
    icon: Brain,
    labelKey: "chat.tool.label.remember",
    color: "border-violet-500/30 bg-violet-500/[0.08] text-violet-300",
  },
  forget: {
    icon: Brain,
    labelKey: "chat.tool.label.forget",
    color: "border-violet-500/30 bg-violet-500/[0.08] text-violet-300",
  },
  list_memories: {
    icon: Brain,
    labelKey: "chat.tool.label.list_memories",
    color: "border-violet-500/30 bg-violet-500/[0.08] text-violet-300",
  },
  run_scenario_reasoning: {
    icon: Brain,
    labelKey: "chat.tool.label.run_scenario_reasoning",
    color: "border-purple-500/30 bg-purple-500/[0.08] text-purple-300",
  },
  list_pathways: {
    icon: Route,
    labelKey: "chat.tool.label.list_pathways",
  },
  list_requirements: {
    icon: ListChecks,
    labelKey: "chat.tool.label.list_requirements",
  },
  list_risk_factors: {
    icon: ShieldAlert,
    labelKey: "chat.tool.label.list_risk_factors",
  },
  list_recent_events: {
    icon: History,
    labelKey: "chat.tool.label.list_recent_events",
  },
  get_scenario_summary: {
    icon: Network,
    labelKey: "chat.tool.label.get_scenario_summary",
  },
  web_search: {
    icon: Search,
    labelKey: "chat.tool.label.web_search",
  },
  web_fetch: {
    icon: Globe,
    labelKey: "chat.tool.label.web_fetch",
  },
};

const DEFAULT_META: ToolMeta = { icon: Wrench };

export function ToolInvocation({ tool }: { tool: ToolCall }) {
  const t = useT();
  const [open, setOpen] = useState(false);

  const resultHasError = resultIsError(tool.result);
  const failed = !!tool.error || resultHasError;
  const running = !tool.endedAt && tool.result === null && !tool.error;
  const done = !!tool.endedAt && !failed;

  const meta = TOOL_META[tool.name] ?? DEFAULT_META;
  const ToolIcon = meta.icon;
  const label = meta.labelKey ? t(meta.labelKey) : tool.name;

  return (
    <div
      className={cn(
        "rounded-md border my-1.5 text-xs overflow-hidden transition-all",
        meta.color ?? "border-white/10 bg-white/[0.02]"
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
        <ToolIcon className="h-3.5 w-3.5 shrink-0 opacity-80" />
        {running ? (
          <Loader2 className="h-3 w-3 text-brand-300 animate-spin shrink-0" />
        ) : failed ? (
          <XCircle className="h-3 w-3 text-red-400 shrink-0" />
        ) : done ? (
          <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />
        ) : null}
        <span className="font-mono truncate font-medium">
          {label}
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
          {/* Show result only when it's not an error payload (errors
              are displayed in the dedicated error block below). */}
          {tool.result !== null && !resultHasError && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-0.5">
                {t("chat.tool.result")}
              </div>
              <pre className="text-[11px] text-zinc-300 font-mono whitespace-pre-wrap break-words">
                {formatValue(tool.result, 800)}
              </pre>
            </div>
          )}
          {failed && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-red-400 mb-0.5">
                {t("chat.tool.failed")}
              </div>
              <pre className="text-[11px] text-red-300 font-mono whitespace-pre-wrap break-words">
                {tool.error ||
                  (tool.result &&
                  typeof tool.result === "object" &&
                  "error" in tool.result
                    ? String(
                        (tool.result as Record<string, unknown>).error
                      )
                    : t("chat.tool.failed"))}
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

// ---------- Reasoning / Chain of Thought ----------

/**
 * Collapsible panel that displays the model's chain-of-thought reasoning
 * (CoT). Models that support "thinking" mode (e.g. DeepSeek R1, Qwen3
 * thinking) emit reasoning tokens separately from the main content.
 *
 * - While streaming and no main content yet: auto-expanded so the user
 *   sees the model "thinking" in real time.
 * - Once main content starts arriving: auto-collapses to a summary bar.
 * - User can manually toggle at any time.
 */
export function ReasoningPanel({
  reasoning,
  streaming,
  hasContent,
}: {
  reasoning: string;
  streaming?: boolean;
  hasContent?: boolean;
}) {
  const t = useT();
  // Auto-collapse when main content starts arriving, auto-expand when
  // only reasoning is streaming (no content yet).
  const autoOpen = streaming && !hasContent;
  const [manualToggle, setManualToggle] = useState<boolean | null>(null);
  const open = manualToggle !== null ? manualToggle : autoOpen;

  if (!reasoning) return null;

  return (
    <div className="mb-2 rounded-lg border border-zinc-200/60 dark:border-zinc-700/50 bg-zinc-50/80 dark:bg-zinc-800/30 overflow-hidden">
      <button
        type="button"
        onClick={() => setManualToggle(!open)}
        className="flex items-center gap-1.5 w-full px-3 py-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors"
      >
        <Brain className="h-3.5 w-3.5 text-violet-500 dark:text-violet-400" />
        <span>
          {streaming && !hasContent
            ? t("chat.reasoning.thinking")
            : t("chat.reasoning.title")}
        </span>
        {streaming && !hasContent && (
          <Loader2 className="h-3 w-3 animate-spin text-violet-400" />
        )}
        <ChevronDown
          className={cn(
            "h-3 w-3 ml-auto transition-transform",
            open ? "rotate-180" : ""
          )}
        />
      </button>
      {open && (
        <div className="px-3 pb-2.5 pt-0.5 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400 border-t border-zinc-200/60 dark:border-zinc-700/40 max-h-64 overflow-y-auto">
          <div className="whitespace-pre-wrap break-words">{reasoning}</div>
        </div>
      )}
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
  onScroll,
}: {
  children: ReactNode;
  className?: string;
  autoScrollRef?: React.RefObject<HTMLDivElement | null>;
  onScroll?: React.UIEventHandler<HTMLDivElement>;
}) {
  return (
    <div
      ref={autoScrollRef}
      onScroll={onScroll}
      className={cn(
        "flex-1 overflow-y-auto px-4 sm:px-5 py-4 space-y-4",
        className
      )}
    >
      {children}
    </div>
  );
}

// ---------- Chat Minimap (conversation overview) ----------

/**
 * A compact vertical overview of the conversation structure.
 * Each message is represented as a colored block; clicking a block
 * scrolls the chat container to that message.
 *
 * - User messages: brand color
 * - Assistant messages: zinc
 * - Tool calls: violet dots within the assistant block
 * - Streaming messages: pulsing indicator
 */
export function ChatMinimap({
  messages,
  onJumpTo,
  activeIndex,
}: {
  messages: Array<{
    id: string;
    role: "user" | "assistant" | "system";
    content: string;
    toolCalls?: Array<{ id: string }>;
    streaming?: boolean;
  }>;
  onJumpTo: (index: number) => void;
  activeIndex?: number;
}) {
  if (messages.length === 0) return null;

  return (
    <div className="w-7 shrink-0 flex flex-col gap-0.5 py-2 overflow-y-auto scrollbar-thin">
      {messages.map((m, i) => {
        const isUser = m.role === "user";
        const toolCount = m.toolCalls?.length ?? 0;
        const len = Math.max(2, Math.min(20, Math.ceil(m.content.length / 80)));
        const isActive = activeIndex === i;
        return (
          <button
            key={m.id}
            onClick={() => onJumpTo(i)}
            title={m.content.slice(0, 80) || (isUser ? "User" : "AI")}
            className={cn(
              "w-full rounded-sm transition-all relative group",
              isUser
                ? "bg-brand-500/40 hover:bg-brand-500/70"
                : "bg-zinc-500/30 hover:bg-zinc-500/50",
              isActive && "ring-1 ring-brand-400",
              m.streaming && "animate-pulse"
            )}
            style={{ height: `${len * 3}px` }}
          >
            {toolCount > 0 && (
              <span className="absolute -right-0.5 top-0.5 w-1.5 h-1.5 rounded-full bg-violet-400" />
            )}
          </button>
        );
      })}
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
