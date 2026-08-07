"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Bot, ArrowLeft, Plus, Users, Trash2, Loader2 } from "lucide-react";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { AgentTeamLauncher } from "@/components/agent-team/agent-team-launcher";
import { TeamChat } from "@/components/agent-team/team-chat";
import { TeamResultView } from "@/components/agent-team/team-result";
import { useTeamJobs, useTeamJob } from "@/lib/hooks";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn, formatDate } from "@/lib/utils";
import type { TeamStatus } from "@/lib/api";

function statusColor(status: TeamStatus): string {
  if (status === "completed") return "text-green-600 dark:text-green-400";
  if (status === "failed") return "text-red-600 dark:text-red-400";
  if (status === "cancelled") return "text-zinc-500";
  return "text-brand-500";
}

function templateLabel(t: (k: string) => string, name: string): string {
  const key = `agentTeam.template.${name}`;
  const label = t(key);
  return label === key ? name : label;
}

/**
 * AgentTeamPage — AgentTeam task management.
 *
 * Two views:
 *   1. List view (no ?job= param): shows the launcher form (toggleable)
 *      and a list of past team jobs. Clicking a job navigates to the
 *      detail view. Each row has a delete button.
 *   2. Detail view (?job=<id>): shows a WeChat-style group chat UI
 *      (TeamChat) with live SWR polling, plus the full result report
 *      below once the job completes.
 */
export default function AgentTeamPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  if (jobId) {
    return <TeamDetail jobId={jobId} onBack={() => router.push("/agent-team")} />;
  }

  return <TeamList />;
}

// ---------- List view ----------

function TeamList() {
  const t = useT();
  const router = useRouter();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data: jobs, isLoading, mutate } = useTeamJobs();
  const [showLauncher, setShowLauncher] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && (jobs ?? []).length === 0) {
      setShowLauncher(true);
    }
  }, [isLoading, jobs]);

  async function handleDelete(id: string, objective: string) {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("agentTeam.list.deleteConfirm", { name: objective }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setDeletingId(id);
    try {
      await api.deleteTeamJob(id);
      await mutate();
      toast({ title: t("agentTeam.toast.deleted"), variant: "success" });
    } catch (err: any) {
      toast({
        title: t("agentTeam.toast.deleteFailed"),
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
            <Bot className="h-6 w-6 text-brand-500" />
            {t("agentTeam.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("agentTeam.subtitle")}
          </p>
        </div>
        <Button
          variant={showLauncher ? "outline" : "default"}
          size="sm"
          onClick={() => setShowLauncher((v) => !v)}
          className="gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("agentTeam.list.new")}
        </Button>
      </header>

      {showLauncher && (
        <AgentTeamLauncher
          onCreated={(j) => {
            setShowLauncher(false);
            router.push(`/agent-team?job=${j.id}`);
          }}
        />
      )}

      {/* Job list */}
      <div className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          {t("agentTeam.list.title")}
        </h2>
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : (jobs ?? []).length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t("agentTeam.list.empty")}
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
                onClick={() => router.push(`/agent-team?job=${j.id}`)}
                className="group w-full text-left rounded-lg border border-black/5 dark:border-white/10 bg-surface/40 hover:bg-surface/80 transition-colors p-3 space-y-1.5 cursor-pointer"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground truncate">
                    {j.objective}
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Badge className={cn("gap-1", statusColor(j.status))}>
                      {t(`agentTeam.status.${j.status}`)}
                    </Badge>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 w-6 p-0 text-zinc-500 hover:text-red-600 dark:hover:text-red-300 opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(j.id, j.objective);
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
                <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                  <span>
                    {t("agentTeam.list.template")}:{" "}
                    {templateLabel(t, j.template)}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Users className="h-3 w-3" />
                    {j.specialist_count} {t("agentTeam.list.specialists")}
                  </span>
                  <span>
                    {t("agentTeam.list.created")}: {formatDate(j.created_at)}
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

function TeamDetail({
  jobId,
  onBack,
}: {
  jobId: string;
  onBack: () => void;
}) {
  const t = useT();
  const router = useRouter();
  const { data: job, mutate } = useTeamJob(jobId);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-4 min-w-0">
      <header className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
          <SidebarToggleButton />
          <Bot className="h-6 w-6 text-brand-500" />
          {t("agentTeam.title")}
        </h1>
        <Button
          variant="outline"
          size="sm"
          onClick={onBack}
          className="gap-1.5"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {t("agentTeam.progress.viewJobs")}
        </Button>
      </header>

      {!job ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <TeamChat
            job={job}
            onCancelled={() => mutate()}
            onDeleted={() => router.push("/agent-team")}
            onViewResult={() => {
              const el = document.getElementById("result");
              el?.scrollIntoView({ behavior: "smooth" });
            }}
          />
          {job.final_output ? (
            <div id="result" className="space-y-4">
              <TeamResultView result={job.final_output} />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
