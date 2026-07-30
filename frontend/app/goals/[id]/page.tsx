"use client";

import { use, useEffect, useState } from "react";
import { Compass, GitBranch, ListTodo, Network, TreePine } from "lucide-react";
import { mutate } from "swr";
import { GoalCelebration } from "@/components/goals/goal-celebration";
import { GoalEditDialog, type GoalEditState } from "@/components/goals/goal-edit-dialog";
import { GoalGraphTab } from "@/components/goals/goal-graph-tab";
import { GoalOverviewTab } from "@/components/goals/goal-overview-tab";
import { GoalPathwaysTab } from "@/components/goals/goal-pathways-tab";
import { GoalScenariosTab } from "@/components/goals/goal-scenarios-tab";
import { GoalTreeTab } from "@/components/goals/goal-tree-tab";
import { GoalWorkspaceHeader } from "@/components/goals/goal-workspace-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, type DashboardSummary, type GoalStatus } from "@/lib/api";
import { useDashboard, useGoal, usePathways, useRequirements, useScenarios } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";

type GoalRecord = {
  id: string;
  title: string;
  description?: string | null;
  scenario: string;
  target_date?: string | null;
  status: GoalStatus;
};

type WorkspaceView = "overview" | "pathways" | "graph" | "scenarios" | "tree";

export default function GoalDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const t = useT();
  const toast = useToast();
  const { id: goalId } = use(params);
  const { data: dashboard, mutate: mutateDashboard, isLoading } = useDashboard(goalId);
  const { data: goalData, mutate: mutateGoal } = useGoal(goalId);
  const { data: pathwaysData } = usePathways(goalId);
  const { data: scenarios } = useScenarios(goalId);
  const [activePathway, setActivePathway] = useState<string>();
  const { data: requirementsData } = useRequirements(activePathway);
  const [editOpen, setEditOpen] = useState(false);
  const [quickBusy, setQuickBusy] = useState(false);
  const [view, setView] = useState<WorkspaceView>("overview");
  const [celebration, setCelebration] = useState<{ status: "achieved" | "abandoned" } | null>(null);

  const goal = goalData as GoalRecord | undefined;
  const summary = dashboard as DashboardSummary | undefined;
  const pathways = (pathwaysData ?? []) as any[];
  const requirements = (requirementsData ?? []) as any[];
  const scenarioCount = ((scenarios ?? []) as any[]).length;
  const title = goal?.title ?? summary?.goal_title ?? `Goal ${goalId}`;
  const status = goal?.status ?? (summary?.goal_status as GoalStatus | undefined);
  const scenario = goal?.scenario ?? summary?.goal_scenario ?? undefined;
  const targetDate = goal?.target_date ?? summary?.goal_target_date ?? undefined;

  const editState: GoalEditState | null = goal && status
    ? {
        id: goalId,
        title: goal.title,
        description: goal.description ?? "",
        scenario: goal.scenario,
        target_date: goal.target_date ?? "",
        status,
      }
    : null;

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (requested === "overview" || requested === "pathways" || requested === "graph" || requested === "scenarios" || requested === "tree") {
      setView(requested);
    }
  }, []);

  function changeView(next: string) {
    const value = next as WorkspaceView;
    setView(value);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", value);
    window.history.replaceState(null, "", url);
  }

  async function refreshGoal() {
    await Promise.all([mutateGoal(), mutateDashboard(), mutate("goals")]);
  }

  async function handleQuickStatus(nextStatus: GoalStatus) {
    setQuickBusy(true);
    try {
      await api.updateGoal(goalId, { status: nextStatus });
      await refreshGoal();
      toast({ title: t("goals.toast.updated"), variant: "success" });
      if (nextStatus === "achieved" || nextStatus === "abandoned") {
        setCelebration({ status: nextStatus });
      }
    } catch (error: any) {
      toast({ title: t("goals.toast.updateFailed"), description: error?.message, variant: "error" });
    } finally {
      setQuickBusy(false);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in min-w-0">
      <GoalWorkspaceHeader
        title={title}
        scenario={scenario}
        status={status}
        targetDate={targetDate ?? undefined}
        busy={quickBusy}
        onStatusChange={handleQuickStatus}
        onEdit={() => setEditOpen(true)}
      />
      <GoalEditDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        goal={editState}
        onSaved={(newStatus) => {
          refreshGoal();
          if (newStatus === "achieved" || newStatus === "abandoned") setCelebration({ status: newStatus });
        }}
      />

      <Tabs value={view} onValueChange={changeView} className="min-w-0">
        <div className="max-w-full overflow-x-auto pb-1">
          <TabsList className="w-max min-w-full justify-start">
            <WorkspaceTab value="overview" icon={Compass} label={t("goalDetail.tab.overview")} />
            <WorkspaceTab value="pathways" icon={ListTodo} label={t("goalDetail.tab.pathways")} />
            <WorkspaceTab value="graph" icon={Network} label={t("goalDetail.tab.graph")} />
            <WorkspaceTab value="scenarios" icon={GitBranch} label={t("goalDetail.tab.scenarios")} />
            <WorkspaceTab value="tree" icon={TreePine} label={t("goalDetail.tab.tree")} />
          </TabsList>
        </div>
        <TabsContent value="overview">
          <GoalOverviewTab dashboard={summary} goalTitle={title} isLoading={isLoading} />
        </TabsContent>
        <TabsContent value="pathways">
          <GoalPathwaysTab
            pathways={pathways}
            activePathway={activePathway}
            requirements={requirements}
            onSelect={setActivePathway}
          />
        </TabsContent>
        <TabsContent value="graph"><GoalGraphTab goalId={goalId} /></TabsContent>
        <TabsContent value="scenarios"><GoalScenariosTab goalId={goalId} /></TabsContent>
        <TabsContent value="tree"><GoalTreeTab goalId={goalId} /></TabsContent>
      </Tabs>

      {celebration && (
        <GoalCelebration
          onClose={() => setCelebration(null)}
          goalTitle={title}
          status={celebration.status}
          milestones={summary?.milestones ?? []}
          scenarioCount={scenarioCount}
        />
      )}
    </div>
  );
}

function WorkspaceTab({ value, icon: Icon, label }: {
  value: string;
  icon: typeof Compass;
  label: string;
}) {
  return (
    <TabsTrigger value={value} className="gap-1.5">
      <Icon className="h-3.5 w-3.5" />
      {label}
    </TabsTrigger>
  );
}
