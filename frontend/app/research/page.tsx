"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Microscope, ArrowLeft, Plus, Trash2, Loader2 } from "lucide-react";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { ResearchLauncher } from "@/components/research/research-launcher";
import { ResearchProgress } from "@/components/research/research-progress";
import { ResearchReportView } from "@/components/research/research-report";
import { useResearchJobs, useResearchJob } from "@/lib/hooks";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn, formatDate } from "@/lib/utils";
import type { ResearchStatus } from "@/lib/api";

function statusColor(status: ResearchStatus): string {
  if (status === "completed") return "text-green-600 dark:text-green-400";
  if (status === "failed") return "text-red-600 dark:text-red-400";
  if (status === "cancelled") return "text-zinc-500";
  return "text-brand-500";
}

/**
 * ResearchPage — deep research task management.
 *
 * Two views:
 *   1. List view (no ?job= param): shows the launcher form (toggleable)
 *      and a list of past research jobs. Each row has a delete button.
 *   2. Detail view (?job=<id>): shows the research progress card with
 *      live SWR polling, and the full report once the job completes.
 *      Header includes a delete button.
 */
export default function ResearchPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  if (jobId) {
    return <ResearchDetail jobId={jobId} onBack={() => router.push("/research")} />;
  }

  return <ResearchList />;
}

// ---------- List view ----------

function ResearchList() {
  const t = useT();
  const router = useRouter();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data: jobs, isLoading, mutate } = useResearchJobs();
  const [showLauncher, setShowLauncher] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && (jobs ?? []).length === 0) {
      setShowLauncher(true);
    }
  }, [isLoading, jobs]);

  async function handleDelete(id: string, question: string) {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("research.list.deleteConfirm", { name: question }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setDeletingId(id);
    try {
      await api.deleteResearchJob(id);
      await mutate();
      toast({ title: t("research.toast.deleted"), variant: "success" });
    } catch (err: any) {
      toast({
        title: t("research.toast.deleteFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 min-w-0">
      <header className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
            <SidebarToggleButton />
            <Microscope className="h-6 w-6 text-brand-500" />
            {t("research.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("research.subtitle")}
          </p>
        </div>
        <Button
          variant={showLauncher ? "outline" : "default"}
          size="sm"
          onClick={() => setShowLauncher((v) => !v)}
          className="gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("research.list.new")}
        </Button>
      </header>

      {showLauncher && (
        <ResearchLauncher
          onCreated={(j) => {
            setShowLauncher(false);
            router.push(`/research?job=${j.id}`);
          }}
        />
      )}

      {/* Job list */}
      <div className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          {t("research.list.title")}
        </h2>
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : (jobs ?? []).length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t("research.list.empty")}
            </CardContent>
          </Card>
        ) : (
          (jobs ?? []).map((j) => {
            const isRunning =
              j.status !== "completed" &&
              j.status !== "failed" &&
              j.status !== "cancelled";
            return (
              <div
                key={j.id}
                onClick={() => router.push(`/research?job=${j.id}`)}
                className="group w-full text-left rounded-lg border border-black/5 dark:border-white/10 bg-surface/40 hover:bg-surface/80 transition-colors p-3 space-y-1.5 cursor-pointer"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground truncate">
                    {j.question}
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Badge className={cn("shrink-0 gap-1", statusColor(j.status))}>
                      {t(`research.status.${j.status}`)}
                    </Badge>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 w-6 p-0 text-zinc-500 hover:text-red-600 dark:hover:text-red-300 opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(j.id, j.question);
                      }}
                      disabled={deletingId === j.id}
                      title={t("common.delete")}
                    >
                      {deletingId === j.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Trash2 className="h-3 w-3" />
                      )}
                    </Button>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>
                    {t("research.list.created")}: {formatDate(j.created_at)}
                  </span>
                  <span>
                    {j.engines.length} {t("research.list.engines")}
                  </span>
                  {isRunning && (
                    <span className="text-brand-500">
                      {Math.round((j.progress ?? 0) * 100)}%
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {ConfirmRoot}
    </div>
  );
}

// ---------- Detail view ----------

function ResearchDetail({
  jobId,
  onBack,
}: {
  jobId: string;
  onBack: () => void;
}) {
  const t = useT();
  const router = useRouter();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data: job, mutate } = useResearchJob(jobId);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    if (!job) return;
    const ok = await confirm({
      title: t("common.delete"),
      description: t("research.list.deleteConfirm", { name: job.question }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await api.deleteResearchJob(job.id);
      toast({ title: t("research.toast.deleted"), variant: "success" });
      router.push("/research");
    } catch (err: any) {
      toast({
        title: t("research.toast.deleteFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-4 min-w-0">
      <header className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
          <SidebarToggleButton />
          <Microscope className="h-6 w-6 text-brand-500" />
          {t("research.title")}
        </h1>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDelete}
            disabled={deleting || !job}
            className="gap-1.5 text-zinc-500 hover:text-red-600 dark:hover:text-red-300"
          >
            {deleting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            {t("common.delete")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onBack}
            className="gap-1.5"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t("research.progress.viewJobs")}
          </Button>
        </div>
      </header>

      {!job ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <ResearchProgress
            job={job}
            onCancelled={() => mutate()}
            onViewReport={() => {
              const el = document.getElementById("report");
              el?.scrollIntoView({ behavior: "smooth" });
            }}
          />
          {job.report ? (
            <div id="report">
              <ResearchReportView report={job.report} />
            </div>
          ) : (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                {t("research.report.noReport")}
              </CardContent>
            </Card>
          )}
        </>
      )}

      {ConfirmRoot}
    </div>
  );
}
