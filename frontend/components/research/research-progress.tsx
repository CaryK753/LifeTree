"use client";

import { useState } from "react";
import {
  Loader2,
  X,
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
  CardTitle,
} from "@/components/ui/card";
import { api, type ResearchJobDetail, type ResearchStatus } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn, formatDate } from "@/lib/utils";

const PIPELINE_STEPS: ResearchStatus[] = [
  "planning",
  "searching",
  "extracting",
  "structuring",
  "validating",
  "synthesizing",
];

const TERMINAL_STATES: ResearchStatus[] = ["completed", "failed", "cancelled"];

function statusColor(status: ResearchStatus): string {
  if (status === "completed") return "text-green-600 dark:text-green-400";
  if (status === "failed") return "text-red-600 dark:text-red-400";
  if (status === "cancelled") return "text-zinc-500";
  return "text-brand-500";
}

function engineLabel(t: (k: string) => string, name: string): string {
  const key = `research.engine.${name}`;
  const label = t(key);
  return label === key ? name : label;
}

/**
 * ResearchProgress — displays a research job's pipeline state, progress
 * bar, current step, meta info, and cancel/view-report actions.
 *
 * The pipeline is visualized as a horizontal stepper: each of the 6
 * LangGraph nodes (planning → searching → extracting → structuring →
 * validating → synthesizing) is a pill that lights up as the job
 * advances. Terminal states (completed/failed/cancelled) stop the
 * stepper and show a result icon.
 */
export function ResearchProgress({
  job,
  onCancelled,
  onViewReport,
}: {
  job: ResearchJobDetail;
  onCancelled?: () => void;
  onViewReport?: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const [cancelling, setCancelling] = useState(false);

  const isTerminal = TERMINAL_STATES.includes(job.status);
  const currentStepIndex = PIPELINE_STEPS.indexOf(job.status);

  async function handleCancel() {
    const ok = await confirm({
      title: t("research.progress.cancel"),
      description: job.question,
      confirmLabel: t("research.progress.cancel"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setCancelling(true);
    try {
      await api.cancelResearchJob(job.id);
      toast({ title: t("research.toast.cancelled"), variant: "success" });
      onCancelled?.();
    } catch (err: any) {
      toast({
        title: t("research.toast.cancelFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setCancelling(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="min-w-0">
            <CardTitle className="text-sm flex items-center gap-2">
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
              <span className="truncate">{job.question}</span>
            </CardTitle>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge className={cn("gap-1", statusColor(job.status))}>
              {t(`research.status.${job.status}`)}
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
                {cancelling
                  ? t("research.progress.cancelling")
                  : t("research.progress.cancel")}
              </Button>
            )}
            {job.status === "completed" && onViewReport && (
              <Button
                size="sm"
                variant="outline"
                onClick={onViewReport}
                className="gap-1.5 h-7 text-xs"
              >
                <FileText className="h-3 w-3" />
                {t("research.progress.viewReport")}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Progress bar */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {t("research.progress.step")}: {job.current_step ?? "—"}
            </span>
            <span>{Math.round((job.progress ?? 0) * 100)}%</span>
          </div>
          <Progress value={(job.progress ?? 0) * 100} />
        </div>

        {/* Pipeline steps */}
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">
            {t("research.progress.runningSteps")}
          </div>
          <div className="flex items-center gap-1 flex-wrap">
            {PIPELINE_STEPS.map((step, i) => {
              const done = isTerminal && job.status === "completed";
              const active = i === currentStepIndex && !isTerminal;
              const passed = i < currentStepIndex || done;
              return (
                <div key={step} className="flex items-center gap-1">
                  <div
                    className={cn(
                      "flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] border",
                      active
                        ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-300"
                        : passed
                          ? "border-green-500/30 bg-green-500/5 text-green-700 dark:text-green-300"
                          : "border-black/5 dark:border-white/10 text-zinc-400 dark:text-zinc-500"
                    )}
                  >
                    {passed && <CheckCircle className="h-3 w-3" />}
                    {active && <Loader2 className="h-3 w-3 animate-spin" />}
                    {t(`research.status.${step}`)}
                  </div>
                  {i < PIPELINE_STEPS.length - 1 && (
                    <span className="text-zinc-300 dark:text-zinc-700">
                      →
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Meta info */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div>
            <span className="text-muted-foreground">
              {t("research.progress.engines")}:{" "}
            </span>
            <span>
              {job.engines.map((e) => engineLabel(t, e)).join(", ")}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">
              {t("research.progress.startedAt")}:{" "}
            </span>
            <span>{formatDate(job.started_at)}</span>
          </div>
          {job.completed_at && (
            <div>
              <span className="text-muted-foreground">
                {t("research.progress.completedAt")}:{" "}
              </span>
              <span>{formatDate(job.completed_at)}</span>
            </div>
          )}
        </div>

        {/* Error */}
        {job.status === "failed" && job.error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/[0.04] px-3 py-2">
            <div className="text-xs text-red-600 dark:text-red-400 font-medium">
              {t("research.progress.error")}
            </div>
            <div className="text-xs text-red-700 dark:text-red-300 mt-1 break-all">
              {job.error}
            </div>
          </div>
        )}
      </CardContent>
      {ConfirmRoot}
    </Card>
  );
}
