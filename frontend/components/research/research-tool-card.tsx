"use client";

import Link from "next/link";
import { Microscope, ExternalLink, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import type { ToolCall } from "@/lib/chat-store";
import type { ResearchStatus } from "@/lib/api";

const TERMINAL_STATES: ResearchStatus[] = ["completed", "failed", "cancelled"];

function statusColor(status: string): string {
  if (status === "completed") return "text-green-600 dark:text-green-400";
  if (status === "failed") return "text-red-600 dark:text-red-400";
  if (status === "cancelled") return "text-zinc-500";
  return "text-brand-500";
}

/**
 * ResearchToolCard — compact inline card rendered in the chat when the
 * LLM invokes `start_research` or `get_research_status`.
 *
 * Instead of showing raw JSON output, this card displays the research
 * question, current status, and a clickable link to the full research
 * detail page (`/research?job=<id>`).
 *
 * The card is always rendered as a Link so the user can click anywhere
 * on it to navigate to the research progress view.
 */
export function ResearchToolCard({ tool }: { tool: ToolCall }) {
  const t = useT();

  // Extract job_id and status from the tool result.
  const result = (tool.result ?? {}) as Record<string, unknown>;
  const jobId = result.job_id as string | undefined;
  const status = (result.status as string) ?? "planning";
  const progress = result.progress as number | undefined;
  const isTerminal = TERMINAL_STATES.includes(status as ResearchStatus);
  const running = !isTerminal && tool.result !== null;

  // The research question comes from the tool args.
  const question = (tool.args.question as string) ?? "—";

  // If we don't have a job_id yet (e.g. tool is still running or
  // returned an error), fall back to a minimal non-clickable card.
  if (!jobId && !tool.error) {
    return (
      <div className="mb-0 rounded-md border border-black/5 dark:border-white/10 bg-surface/40 px-3 py-2 flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin text-brand-500 shrink-0" />
        <span className="text-muted-foreground truncate">{question}</span>
      </div>
    );
  }

  if (tool.error || (result && typeof result === "object" && "error" in result)) {
    return (
      <div className="mb-0 rounded-md border border-red-500/30 bg-red-500/[0.04] px-3 py-2 text-sm text-red-700 dark:text-red-300">
        {tool.error ?? String(result.error)}
      </div>
    );
  }

  return (
    <Link
      href={`/research?job=${jobId}`}
      className="mb-0 group/research rounded-md border border-brand-500/20 bg-brand-500/[0.04] hover:bg-brand-500/[0.08] transition-colors px-3 py-2.5 flex items-center gap-3"
    >
      <div className="flex items-center justify-center h-8 w-8 rounded-md bg-brand-500/10 shrink-0">
        {running ? (
          <Loader2 className="h-4 w-4 animate-spin text-brand-500" />
        ) : (
          <Microscope className="h-4 w-4 text-brand-500" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-brand-700 dark:text-brand-300">
            {t("research.chat.jobCreated")}
          </span>
          <span className={cn("text-[10px]", statusColor(status))}>
            {t(`research.status.${status}`) === `research.status.${status}`
              ? status
              : t(`research.status.${status}`)}
          </span>
        </div>
        <p className="text-xs text-foreground truncate mt-0.5">{question}</p>
        {typeof progress === "number" && !isTerminal && (
          <div className="mt-1 flex items-center gap-1.5">
            <div className="h-1 flex-1 rounded-full bg-black/5 dark:bg-white/10 overflow-hidden">
              <div
                className="h-full bg-brand-500 transition-all"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            </div>
            <span className="text-[10px] text-muted-foreground">
              {Math.round(progress * 100)}%
            </span>
          </div>
        )}
      </div>
      <ExternalLink className="h-3.5 w-3.5 text-muted-foreground group-hover/research:text-brand-500 shrink-0 transition-colors" />
    </Link>
  );
}
