"use client";

import { use, useState } from "react";
import { useDashboard, usePathways, useRequirements, useScenarios } from "@/lib/hooks";
import { DashboardBody } from "@/components/dashboard/dashboard-body";
import { ChangesSummaryBanner } from "@/components/dashboard/changes-summary-banner";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { GoalGraphTab } from "@/components/goals/goal-graph-tab";
import { GoalScenariosTab } from "@/components/goals/goal-scenarios-tab";
import { GoalTreeTab } from "@/components/goals/goal-tree-tab";
import {
  GoalEditDialog,
  type GoalEditState,
} from "@/components/goals/goal-edit-dialog";
import { GoalCelebration } from "@/components/goals/goal-celebration";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  Calendar,
  Tag,
  Activity,
  Pencil,
  CheckCircle2,
  Play,
  Compass,
  Network,
  GitBranch,
  TreePine,
  ListTodo,
} from "lucide-react";
import { api, type GoalStatus } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { mutate } from "swr";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Goal workspace — single-page view consolidating everything about a goal:
 *
 *   overview   — DashboardBody (Streak/Cruising strip + GoalCompass +
 *                RegretFreeActions + FactorBreakdown + SurvivalCurve +
 *                RiskHeatmap + TimelineGantt + Milestones + EventFeed +
 *                CredibilityMeter) + ChangesSummaryBanner
 *   pathways   — Pathway cards + Requirements table
 *   graph      — Cytoscape knowledge graph (GoalGraphTab)
 *   scenarios  — Scenario tree / compare / evolve (GoalScenariosTab)
 *   tree       — React Flow + dagre decision tree (GoalTreeTab)
 *
 * Replaces the previous split between /dashboard and /goals/[id] which
 * rendered overlapping sets of analysis cards. The /dashboard route now
 * redirects here.
 */
export default function GoalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const t = useT();
  const toast = useToast();
  const { id: goalId } = use(params);
  const { data: dashboard, mutate: mutateDashboard, isLoading } = useDashboard(goalId);
  const { data: pathways } = usePathways(goalId);
  const { data: scenarios } = useScenarios(goalId);
  const [activePathway, setActivePathway] = useState<string | undefined>();
  const { data: requirements } = useRequirements(
    activePathway ?? (pathways as any)?.[0]?.id
  );
  const [editOpen, setEditOpen] = useState(false);
  const [quickBusy, setQuickBusy] = useState(false);
  // Celebration overlay — shown when goal moves to a terminal state.
  const [celebration, setCelebration] = useState<
    | { status: "achieved" | "abandoned" }
    | null
  >(null);

  const statusLabel = (s?: string) => (s ? t(`status.${s}`) : "—");
  const gapLabel = (g?: string) => (g ? t(`gap.${g}`) : "—");

  const goal = (dashboard as any) ?? {};
  const goalTitle = goal.goal_title ?? `Goal ${goalId}`;
  const goalScenario = goal.goal_scenario;
  const goalStatus = goal.goal_status as GoalStatus | undefined;
  const goalTargetDate = goal.goal_target_date;
  const milestones = goal.milestones ?? [];
  const scenariosList = (scenarios as any[]) ?? [];

  const editState: GoalEditState | null = goalStatus
    ? {
        id: goalId,
        title: goalTitle,
        description: "",
        scenario: goalScenario ?? "generic",
        target_date: goalTargetDate ?? "",
        status: goalStatus,
      }
    : null;

  // Quick status change from the header (no dialog needed).
  async function handleQuickStatus(status: GoalStatus) {
    setQuickBusy(true);
    try {
      await api.updateGoal(goalId, { status });
      toast({ title: t("goals.toast.updated"), variant: "success" });
      // Refresh dashboard + the goals list cache.
      mutateDashboard();
      mutate("goals");
      // Trigger celebration overlay for terminal states.
      if (status === "achieved" || status === "abandoned") {
        setCelebration({ status });
      }
    } catch (e: any) {
      toast({
        title: t("goals.toast.updateFailed"),
        description: e?.message ?? "",
        variant: "error",
      });
    } finally {
      setQuickBusy(false);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header className="space-y-2">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            {goalTitle}
          </h1>
          <div className="flex items-center gap-2 shrink-0">
            {/* Quick "mark achieved" / "reactivate" shortcuts */}
            {goalStatus && goalStatus !== "achieved" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleQuickStatus("achieved")}
                disabled={quickBusy}
                title={t("goal.edit.markAchieved")}
              >
                <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                {t("goal.edit.markAchieved")}
              </Button>
            )}
            {goalStatus === "achieved" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleQuickStatus("active")}
                disabled={quickBusy}
                title={t("goal.edit.markActive")}
              >
                <Play className="h-3.5 w-3.5 mr-1" />
                {t("goal.edit.markActive")}
              </Button>
            )}
            <Button size="sm" variant="default" onClick={() => setEditOpen(true)}>
              <Pencil className="h-3.5 w-3.5 mr-1" />
              {t("goal.edit.title")}
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap text-xs text-zinc-500 dark:text-zinc-400">
          {goalScenario && (
            <span className="inline-flex items-center gap-1">
              <Tag className="h-3 w-3" />
              {goalScenario}
            </span>
          )}
          {goalStatus && (
            <Badge
              variant="risk"
              riskLevel={
                goalStatus === "active"
                  ? "low"
                  : goalStatus === "achieved"
                  ? "low"
                  : goalStatus === "paused"
                  ? "medium"
                  : goalStatus === "draft"
                  ? "medium"
                  : "high"
              }
              className="text-[10px]"
            >
              <Activity className="h-2.5 w-2.5 mr-0.5" />
              {statusLabel(goalStatus)}
            </Badge>
          )}
          {goalTargetDate && (
            <span className="inline-flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              {goalTargetDate}
            </span>
          )}
        </div>
      </header>

      <GoalEditDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        goal={editState}
        onSaved={(newStatus) => {
          mutateDashboard();
          mutate("goals");
          // Trigger celebration overlay for terminal states.
          if (newStatus === "achieved" || newStatus === "abandoned") {
            setCelebration({ status: newStatus });
          }
        }}
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview" className="gap-1.5">
            <Compass className="h-3.5 w-3.5" />
            {t("goalDetail.tab.overview")}
          </TabsTrigger>
          <TabsTrigger value="pathways" className="gap-1.5">
            <ListTodo className="h-3.5 w-3.5" />
            {t("goalDetail.tab.pathways")}
          </TabsTrigger>
          <TabsTrigger value="graph" className="gap-1.5">
            <Network className="h-3.5 w-3.5" />
            {t("goalDetail.tab.graph")}
          </TabsTrigger>
          <TabsTrigger value="scenarios" className="gap-1.5">
            <GitBranch className="h-3.5 w-3.5" />
            {t("goalDetail.tab.scenarios")}
          </TabsTrigger>
          <TabsTrigger value="tree" className="gap-1.5">
            <TreePine className="h-3.5 w-3.5" />
            {t("goalDetail.tab.tree")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          {/* 变更摘要 — since-last-visit digest. Wrapped in its own
              ErrorBoundary so a render-level failure in the banner never
              hides the dashboard body below. */}
          <ErrorBoundary title={t("changes.errorTitle")}>
            <ChangesSummaryBanner />
          </ErrorBoundary>
          {isLoading && !dashboard ? (
            <div className="space-y-4">
              {/* Compass skeleton */}
              <Card>
                <CardContent className="p-6 flex items-center gap-6">
                  <Skeleton className="h-32 w-32 rounded-full shrink-0" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-5 w-1/3" />
                    <Skeleton className="h-3 w-1/2" />
                    <Skeleton className="h-2 w-2/3" />
                    <Skeleton className="h-2 w-1/2" />
                  </div>
                </CardContent>
              </Card>
              {/* Grid of stat / chart cards skeleton */}
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <Card key={i}>
                    <CardContent className="p-4 space-y-3">
                      <Skeleton className="h-3.5 w-1/3" />
                      <Skeleton className="h-24 w-full" />
                      <Skeleton className="h-2 w-2/3" />
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          ) : dashboard ? (
            <ErrorBoundary>
              <DashboardBody
                dashboard={dashboard}
                goalTitle={goalTitle}
                statusLabel={statusLabel}
              />
            </ErrorBoundary>
          ) : null}
        </TabsContent>

        <TabsContent value="pathways" className="space-y-4">
          {/* Left/right split: pathway list (left) + requirements panel (right). */}
          <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 min-h-[60vh]">
            {/* Left column — pathway list */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  {t("scenarios.pathwayCount", {
                    n: (pathways as any[])?.length ?? 0,
                  })}
                </span>
              </div>
              <div className="space-y-2 lg:max-h-[70vh] lg:overflow-y-auto lg:pr-1">
                {(pathways as any[])?.map((p) => {
                  const isActive = activePathway === p.id;
                  return (
                    <Card
                      key={p.id}
                      className={cn(
                        "cursor-pointer transition-colors",
                        isActive
                          ? "border-brand-500/50 ring-1 ring-brand-500/20"
                          : "hover:border-brand-500/30"
                      )}
                      onClick={() => setActivePathway(p.id)}
                    >
                      <CardHeader className="p-3">
                        <div>
                          <CardTitle className="text-sm flex items-center gap-1.5">
                            {isActive && (
                              <CheckCircle2 className="h-3.5 w-3.5 text-brand-500 shrink-0" />
                            )}
                            <span className="truncate">{p.name}</span>
                          </CardTitle>
                          <CardDescription className="mt-0.5">
                            {p.region || "—"} · {statusLabel(p.status)}
                          </CardDescription>
                        </div>
                      </CardHeader>
                      <CardContent className="p-3 pt-0">
                        <div className="text-xs text-zinc-500 dark:text-zinc-400">
                          {t("goalDetail.requirements.count", {
                            n: p.requirements?.length ?? "?",
                          })}
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
                {(!pathways || (pathways as any[]).length === 0) && (
                  <div className="text-xs text-zinc-500 dark:text-zinc-400 text-center py-8">
                    {t("goalDetail.requirements.empty")}
                  </div>
                )}
              </div>
            </div>

            {/* Right column — requirements list for the selected pathway */}
            <Card className="min-h-[60vh]">
              <CardHeader>
                <div>
                  <CardTitle className="text-base">
                    {t("goalDetail.requirements.title")}
                  </CardTitle>
                  <CardDescription className="mt-1">
                    {t("goalDetail.requirements.subtitle")}
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {activePathway ? (
                  <div className="space-y-2">
                    {(requirements as any[])?.map((r) => (
                      <div
                        key={r.id}
                        className="flex flex-col sm:grid sm:grid-cols-[1fr_auto_auto] gap-2 sm:gap-3 sm:items-center py-2 border-b border-black/5 dark:border-white/5 last:border-0"
                      >
                        <div>
                          <div className="text-sm text-zinc-800 dark:text-zinc-200">
                            {r.name}
                          </div>
                          <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                            {r.type}
                            {r.description ? ` · ${r.description}` : ""}
                          </div>
                        </div>
                        <Badge
                          variant="risk"
                          riskLevel={
                            r.gap_status === "met"
                              ? "low"
                              : r.gap_status === "partial"
                              ? "medium"
                              : r.gap_status === "missing"
                              ? "high"
                              : "medium"
                          }
                        >
                          {gapLabel(r.gap_status)}
                        </Badge>
                        <div className="text-[11px] text-zinc-500 dark:text-zinc-400 sm:text-right min-w-[60px]">
                          <div>
                            {t("goalDetail.requirements.weight")} {r.weight ?? "—"}
                          </div>
                          {r.gap_delta != null && (
                            <div
                              className={
                                r.gap_delta < 0
                                  ? "text-red-500 dark:text-red-400"
                                  : "text-emerald-500 dark:text-emerald-400"
                              }
                            >
                              {t("goalDetail.requirements.gap")}{" "}
                              {r.gap_delta > 0 ? "+" : ""}
                              {r.gap_delta}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                    {(!requirements || (requirements as any[]).length === 0) && (
                      <div className="text-xs text-zinc-500 dark:text-zinc-400 text-center py-8">
                        {t("goalDetail.requirements.empty")}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
                    <ListTodo className="h-8 w-8 text-zinc-400 dark:text-zinc-500 opacity-50" />
                    <p className="text-sm font-medium text-zinc-600 dark:text-zinc-300">
                      {t("scenarios.noPathwaySelected")}
                    </p>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-sm">
                      {t("scenarios.noPathwaySelectedHint")}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="graph">
          <GoalGraphTab goalId={goalId} />
        </TabsContent>

        <TabsContent value="scenarios">
          <GoalScenariosTab goalId={goalId} />
        </TabsContent>

        <TabsContent value="tree">
          <GoalTreeTab goalId={goalId} />
        </TabsContent>
      </Tabs>

      {/* Celebration overlay — shown when goal is achieved or abandoned. */}
      {celebration && (
        <GoalCelebration
          onClose={() => setCelebration(null)}
          goalTitle={goalTitle}
          status={celebration.status}
          milestones={milestones}
          scenarioCount={scenariosList.length}
        />
      )}
    </div>
  );
}
