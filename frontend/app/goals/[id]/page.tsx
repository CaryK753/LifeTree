"use client";

import { use, useState } from "react";
import { useDashboard, usePathways, useRequirements, useScenarios } from "@/lib/hooks";
import { GoalCompass } from "@/components/dashboard/goal-compass";
import { RiskHeatmap } from "@/components/dashboard/risk-heatmap";
import { EventFeed } from "@/components/dashboard/event-feed";
import { Milestones } from "@/components/dashboard/milestones";
import { CredibilityMeter } from "@/components/dashboard/credibility-meter";
import { ScenarioComparison } from "@/components/scenarios/scenario-comparison";
import {
  GoalEditDialog,
  type GoalEditState,
} from "@/components/goals/goal-edit-dialog";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Calendar, Tag, Activity, Pencil, CheckCircle2, Play } from "lucide-react";
import { api, type GoalStatus } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { mutate } from "swr";

export default function GoalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const t = useT();
  const toast = useToast();
  const { id: goalId } = use(params);
  const { data: dashboard, mutate: mutateDashboard } = useDashboard(goalId);
  const { data: pathways } = usePathways(goalId);
  const { data: scenarios, mutate: rerunScenarios } = useScenarios(goalId);
  const [activePathway, setActivePathway] = useState<string | undefined>();
  const { data: requirements } = useRequirements(activePathway ?? (pathways as any)?.[0]?.id);
  const [editOpen, setEditOpen] = useState(false);
  const [quickBusy, setQuickBusy] = useState(false);

  const statusLabel = (s?: string) => (s ? t(`status.${s}`) : "—");
  const gapLabel = (g?: string) => (g ? t(`gap.${g}`) : "—");

  const goal = (dashboard as any) ?? {};
  const goalTitle = goal.goal_title ?? `Goal ${goalId}`;
  const goalScenario = goal.goal_scenario;
  const goalStatus = goal.goal_status as GoalStatus | undefined;
  const goalTargetDate = goal.goal_target_date;
  const successProb = goal.success_probability ?? {};
  const milestones = goal.milestones ?? [];
  const recentEvents = goal.recent_events ?? [];
  const riskHeatmap = goal.risk_heatmap ?? [];
  const credibility = goal.credibility;

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
          <h1 className="text-2xl font-semibold text-zinc-100">{goalTitle}</h1>
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
            <Button
              size="sm"
              variant="default"
              onClick={() => setEditOpen(true)}
            >
              <Pencil className="h-3.5 w-3.5 mr-1" />
              {t("goal.edit.title")}
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap text-xs text-zinc-500">
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
                goalStatus === "active" ? "low"
                : goalStatus === "achieved" ? "low"
                : goalStatus === "paused" ? "medium"
                : goalStatus === "draft" ? "medium"
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
        onSaved={() => {
          mutateDashboard();
          mutate("goals");
        }}
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">{t("goalDetail.tab.overview")}</TabsTrigger>
          <TabsTrigger value="pathways">{t("goalDetail.tab.pathways")}</TabsTrigger>
          <TabsTrigger value="scenarios">{t("goalDetail.tab.scenarios")}</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <GoalCompass
              goalId={goalId}
              title={goalTitle}
              scenario={goalScenario}
              targetDate={goalTargetDate}
              status={goalStatus}
              successProbability={successProb}
              activeScenarios={goal.active_scenarios}
            />
            <RiskHeatmap risks={riskHeatmap} />
            <Milestones milestones={milestones} />
            <EventFeed events={recentEvents} />
            <CredibilityMeter credibility={credibility} />
          </div>
        </TabsContent>

        <TabsContent value="pathways" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {(pathways as any[])?.map((p) => (
              <Card
                key={p.id}
                className="hover:border-brand-500/30 cursor-pointer transition-colors"
                onClick={() => setActivePathway(p.id)}
              >
                <CardHeader>
                  <div>
                    <CardTitle className="text-sm">{p.name}</CardTitle>
                    <CardDescription>
                      {p.region || "—"} · {statusLabel(p.status)}
                    </CardDescription>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-xs text-zinc-500">
                    {t("goalDetail.requirements.count", { n: p.requirements?.length ?? "?" })}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
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
              <div className="space-y-2">
                {(requirements as any[])?.map((r) => (
                  <div
                    key={r.id}
                    className="grid grid-cols-[1fr_auto_auto] gap-3 items-center py-2 border-b border-white/5 last:border-0"
                  >
                    <div>
                      <div className="text-sm text-zinc-200">{r.name}</div>
                      <div className="text-[11px] text-zinc-500 mt-0.5">
                        {r.type}{r.description ? ` · ${r.description}` : ""}
                      </div>
                    </div>
                    <Badge
                      variant="risk"
                      riskLevel={
                        r.gap_status === "met" ? "low"
                        : r.gap_status === "partial" ? "medium"
                        : r.gap_status === "missing" ? "high"
                        : "medium"
                      }
                    >
                      {gapLabel(r.gap_status)}
                    </Badge>
                    <div className="text-[11px] text-zinc-500 text-right min-w-[60px]">
                      <div>{t("goalDetail.requirements.weight")} {r.weight ?? "—"}</div>
                      {r.gap_delta != null && (
                        <div className={r.gap_delta < 0 ? "text-red-400" : "text-emerald-400"}>
                          {t("goalDetail.requirements.gap")} {r.gap_delta > 0 ? "+" : ""}{r.gap_delta}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {(!requirements || (requirements as any[]).length === 0) && (
                  <div className="text-xs text-zinc-500 text-center py-8">
                    {t("goalDetail.requirements.empty")}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="scenarios">
          <ScenarioComparison scenarios={(scenarios as any[]) ?? []} onRerun={rerunScenarios} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
