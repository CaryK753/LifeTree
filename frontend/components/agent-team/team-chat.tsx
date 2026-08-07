"use client";

import { useEffect, useRef, useState } from "react";
import {
  Bot,
  User,
  Loader2,
  X,
  Trash2,
  CheckCircle,
  XCircle,
  FileText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { api, type TeamJobDetail, type TeamStatus } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn, formatDate } from "@/lib/utils";

const TERMINAL_STATES: TeamStatus[] = ["completed", "failed", "cancelled"];

function statusColor(status: TeamStatus): string {
  if (status === "completed") return "text-green-600 dark:text-green-400";
  if (status === "failed") return "text-red-600 dark:text-red-400";
  if (status === "cancelled") return "text-zinc-500";
  return "text-brand-500";
}

// ---------- Chat message types ----------

type ChatMessage =
  | {
      type: "system";
      text: string;
      timestamp?: string;
    }
  | {
      type: "orchestrator";
      text: string;
      label?: string;
      timestamp?: string;
    }
  | {
      type: "specialist";
      role: string;
      text: string;
      status?: string;
      timestamp?: string;
    };

/**
 * Build an ordered chat transcript from the job's structured fields.
 *
 * Message order mirrors the orchestrator pipeline:
 *   system(created) → orchestrator(decomposed subtasks) → system(dispatching)
 *   → specialist(results) → orchestrator(review gaps) → orchestrator(final summary)
 *   → system(terminal)
 *
 * For running jobs, the current pipeline step is shown as a system message
 * so the user sees live progress in the chat flow.
 */
function buildMessages(
  job: TeamJobDetail,
  t: (k: string, vars?: Record<string, string | number>) => string
): ChatMessage[] {
  const msgs: ChatMessage[] = [];
  const isTerminal = TERMINAL_STATES.includes(job.status);

  // 1. Task created
  msgs.push({
    type: "system",
    text: t("agentTeam.chat.created"),
    timestamp: formatDate(job.created_at),
  });

  // 2. Orchestrator: decomposed subtasks
  const subtasks = job.subtasks ?? [];
  if (subtasks.length > 0) {
    const lines = subtasks.map(
      (s) => `• ${s.role ?? "—"}: ${s.instruction ?? ""}`
    );
    msgs.push({
      type: "orchestrator",
      label: t("agentTeam.chat.decomposed", { count: subtasks.length }),
      text: lines.join("\n"),
      timestamp: formatDate(job.created_at),
    });
  }

  // 3. Live status (non-terminal)
  if (!isTerminal) {
    const stepKey = `agentTeam.chat.step.${job.status}`;
    const stepText = t(stepKey);
    msgs.push({
      type: "system",
      text:
        stepText === stepKey
          ? t("agentTeam.chat.stepGeneric", { step: job.current_step ?? job.status })
          : stepText,
    });
  }

  // 4. Specialist results
  for (const result of job.specialist_results ?? []) {
    const role = String(result.role ?? "Specialist");
    const status = String(result.status ?? "completed");
    let text = "";
    if (result.output) {
      text =
        typeof result.output === "string"
          ? result.output
          : JSON.stringify(result.output, null, 2);
    } else if (result.error) {
      text = String(result.error);
    }
    // Include source/assertion counts as a meta line
    const sourcesCount = Array.isArray(result.sources)
      ? result.sources.length
      : 0;
    const atomsCount = Array.isArray(result.atoms) ? result.atoms.length : 0;
    if (sourcesCount > 0 || atomsCount > 0) {
      const metaParts: string[] = [];
      if (sourcesCount > 0)
        metaParts.push(`${sourcesCount} ${t("agentTeam.chat.sources")}`);
      if (atomsCount > 0)
        metaParts.push(`${atomsCount} ${t("agentTeam.chat.atoms")}`);
      text = text + (text ? "\n" : "") + metaParts.join(" · ");
    }
    if (text) {
      msgs.push({
        type: "specialist",
        role,
        text,
        status,
      });
    }
  }

  // 5. Review gaps
  const gaps = job.review_gaps ?? [];
  if (gaps.length > 0) {
    const gapLines = gaps.map((g) => {
      const desc =
        g.description ?? g.gap ?? g.topic ?? JSON.stringify(g);
      return `• ${desc}`;
    });
    msgs.push({
      type: "orchestrator",
      label: t("agentTeam.chat.reviewGaps", { count: gaps.length }),
      text: gapLines.join("\n"),
    });
  }

  // 6. Final summary
  if (job.final_output?.summary) {
    msgs.push({
      type: "orchestrator",
      label: t("agentTeam.chat.finalSummary"),
      text: job.final_output.summary,
    });
  }

  // 7. Terminal system message
  if (job.status === "completed") {
    msgs.push({
      type: "system",
      text: t("agentTeam.chat.completed"),
      timestamp: job.completed_at ? formatDate(job.completed_at) : undefined,
    });
  } else if (job.status === "failed") {
    msgs.push({
      type: "system",
      text: t("agentTeam.chat.failed"),
      timestamp: job.completed_at ? formatDate(job.completed_at) : undefined,
    });
  } else if (job.status === "cancelled") {
    msgs.push({
      type: "system",
      text: t("agentTeam.chat.cancelled"),
      timestamp: job.completed_at ? formatDate(job.completed_at) : undefined,
    });
  }

  // 8. Error detail (if failed)
  if (job.status === "failed" && job.error) {
    msgs.push({
      type: "system",
      text: `⚠️ ${job.error}`,
    });
  }

  return msgs;
}

// ---------- Avatar ----------

function Avatar({
  type,
  status,
}: {
  type: "orchestrator" | "specialist";
  status?: string;
}) {
  const failed = status === "failed";
  if (type === "orchestrator") {
    return (
      <div className="h-8 w-8 rounded-full bg-brand-500/15 flex items-center justify-center shrink-0">
        <Bot className="h-4 w-4 text-brand-600 dark:text-brand-400" />
      </div>
    );
  }
  return (
    <div
      className={cn(
        "h-8 w-8 rounded-full flex items-center justify-center shrink-0",
        failed
          ? "bg-red-500/15"
          : "bg-zinc-500/10 dark:bg-zinc-400/10"
      )}
    >
      {failed ? (
        <XCircle className="h-4 w-4 text-red-500" />
      ) : (
        <User className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />
      )}
    </div>
  );
}

// ---------- Chat bubble ----------

function ChatBubble({ msg }: { msg: ChatMessage }) {
  if (msg.type === "system") {
    return (
      <div className="flex flex-col items-center gap-0.5 py-1">
        <span className="text-[11px] text-zinc-400 dark:text-zinc-500 bg-zinc-500/5 dark:bg-zinc-400/5 rounded-full px-2.5 py-0.5">
          {msg.text}
        </span>
        {msg.timestamp && (
          <span className="text-[10px] text-zinc-400 dark:text-zinc-600">
            {msg.timestamp}
          </span>
        )}
      </div>
    );
  }

  if (msg.type === "orchestrator") {
    return (
      <div className="flex items-start gap-2 flex-row-reverse">
        <Avatar type="orchestrator" />
        <div className="flex flex-col items-end gap-0.5 max-w-[80%]">
          {msg.label && (
            <span className="text-[10px] text-brand-600 dark:text-brand-400 font-medium px-1">
              {msg.label}
            </span>
          )}
          <div className="rounded-2xl rounded-tr-sm bg-brand-500/10 border border-brand-500/20 px-3 py-2">
            <p className="text-sm text-foreground whitespace-pre-wrap break-words">
              {msg.text}
            </p>
          </div>
          {msg.timestamp && (
            <span className="text-[10px] text-zinc-400 dark:text-zinc-600 px-1">
              {msg.timestamp}
            </span>
          )}
        </div>
      </div>
    );
  }

  // specialist
  return (
    <div className="flex items-start gap-2">
      <Avatar type="specialist" status={msg.status} />
      <div className="flex flex-col items-start gap-0.5 max-w-[80%]">
        <span className="text-[10px] text-muted-foreground font-medium px-1">
          {msg.role}
        </span>
        <div
          className={cn(
            "rounded-2xl rounded-tl-sm border px-3 py-2",
            msg.status === "failed"
              ? "bg-red-500/5 border-red-500/20"
              : "bg-surface border-black/5 dark:border-white/10"
          )}
        >
          <p className="text-sm text-foreground whitespace-pre-wrap break-words">
            {msg.text}
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------- Main component ----------

/**
 * TeamChat — WeChat-style group chat UI for AgentTeam jobs.
 *
 * Replaces the traditional pipeline stepper + result cards with a
 * conversational transcript: the Orchestrator and each Specialist
 * "chat" as group members, with system messages for status transitions.
 *
 * The chat scroll area auto-scrolls to the bottom on new messages.
 * A compact header shows status, progress, and action buttons.
 * When the job completes, a collapsible "full report" section renders
 * below the chat (using TeamResultView).
 */
export function TeamChat({
  job,
  onCancelled,
  onDeleted,
  onViewResult,
}: {
  job: TeamJobDetail;
  onCancelled?: () => void;
  onDeleted?: () => void;
  onViewResult?: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const [cancelling, setCancelling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const isTerminal = TERMINAL_STATES.includes(job.status);
  const messages = buildMessages(job, t);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, job.status, job.progress]);

  async function handleCancel() {
    const ok = await confirm({
      title: t("agentTeam.progress.cancel"),
      description: job.objective,
      confirmLabel: t("agentTeam.progress.cancel"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setCancelling(true);
    try {
      await api.cancelTeamJob(job.id);
      toast({ title: t("agentTeam.toast.cancelled"), variant: "success" });
      onCancelled?.();
    } catch (err: any) {
      toast({
        title: t("agentTeam.toast.cancelFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setCancelling(false);
    }
  }

  async function handleDelete() {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("agentTeam.chat.deleteConfirm"),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await api.deleteTeamJob(job.id);
      toast({ title: t("agentTeam.toast.deleted"), variant: "success" });
      onDeleted?.();
    } catch (err: any) {
      toast({
        title: t("agentTeam.toast.deleteFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Card className="flex flex-col overflow-hidden">
      {/* Header — compact status bar */}
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            {job.status === "completed" ? (
              <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
            ) : job.status === "failed" ? (
              <XCircle className="h-4 w-4 text-red-500 shrink-0" />
            ) : (
              <Loader2
                className={cn(
                  "h-4 w-4 shrink-0",
                  !isTerminal && "animate-spin"
                )}
              />
            )}
            <span className="text-sm font-medium truncate">
              {job.objective}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge className={cn("gap-1", statusColor(job.status))}>
              {t(`agentTeam.status.${job.status}`)}
            </Badge>
            {!isTerminal && (
              <Button
                size="sm"
                variant="outline"
                onClick={handleCancel}
                disabled={cancelling}
                className="gap-1.5 h-7 text-xs"
              >
                {cancelling ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <X className="h-3 w-3" />
                )}
                {t("agentTeam.progress.cancel")}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={handleDelete}
              disabled={deleting}
              className="gap-1.5 h-7 text-xs text-zinc-500 hover:text-red-600 dark:hover:text-red-300"
            >
              {deleting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Trash2 className="h-3 w-3" />
              )}
            </Button>
          </div>
        </div>
        {/* Progress bar */}
        <div className="flex items-center gap-2 mt-1">
          <Progress value={(job.progress ?? 0) * 100} className="h-1" />
          <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">
            {Math.round((job.progress ?? 0) * 100)}%
          </span>
        </div>
      </CardHeader>

      {/* Chat scroll area */}
      <CardContent className="flex-1 p-0">
        <div
          ref={scrollRef}
          className="h-[420px] overflow-y-auto px-4 py-3 space-y-3"
        >
          {messages.map((msg, i) => (
            <ChatBubble key={i} msg={msg} />
          ))}
          {!isTerminal && (
            <div className="flex items-center gap-2 pl-10">
              <Loader2 className="h-3 w-3 animate-spin text-zinc-400" />
              <span className="text-xs text-zinc-400">
                {t("agentTeam.chat.typing")}
              </span>
            </div>
          )}
        </div>
      </CardContent>

      {/* Footer — view full result */}
      {job.status === "completed" && job.final_output && onViewResult && (
        <div className="border-t border-black/5 dark:border-white/10 px-4 py-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onViewResult}
            className="w-full gap-1.5 text-xs"
          >
            <FileText className="h-3.5 w-3.5" />
            {t("agentTeam.progress.viewResult")}
          </Button>
        </div>
      )}

      {ConfirmRoot}
    </Card>
  );
}
