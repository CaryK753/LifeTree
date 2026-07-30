"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, GitBranch, LineChart, Network, Plus, Sparkles, X } from "lucide-react";
import { ScenarioComparisonView } from "@/components/goals/scenario-comparison-view";
import { ScenarioCreateDialog } from "@/components/goals/scenario-create-dialog";
import { ScenarioDetailPanel } from "@/components/scenarios/scenario-detail-panel";
import { ScenarioEvolution } from "@/components/scenarios/scenario-evolution";
import { ScenarioTree, type ScenarioNodeData } from "@/components/scenarios/scenario-tree";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { usePathways, useScenarios } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

type ViewMode = "tree" | "compare" | "evolve";

export function GoalScenariosTab({ goalId }: { goalId: string }) {
  const t = useT();
  const { data: scenarios, mutate } = useScenarios(goalId);
  const { data: pathwaysData } = usePathways(goalId);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<ScenarioNodeData | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("tree");
  const [warnDismissed, setWarnDismissed] = useState(false);

  const scenarioList = (scenarios ?? []) as ScenarioNodeData[];
  const pathways = (pathwaysData ?? []) as Array<{ id: string; name: string }>;
  const active = useMemo(
    () => scenarioList.filter((item) => item.status === "active" || item.status === "draft"),
    [scenarioList]
  );
  const comparison = active.slice(0, 3);
  const parent = selected?.parent_scenario_id
    ? scenarioList.find((item) => item.id === selected.parent_scenario_id) ?? null
    : null;

  return (
    <div className="space-y-4 min-w-0">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <Badge
          className={cn(
            "gap-1 text-xs px-2.5 py-1",
            active.length > 3
              ? "border-amber-500/40 text-amber-600 bg-amber-500/10"
              : "border-emerald-500/40 text-emerald-600 bg-emerald-500/10"
          )}
        >
          <GitBranch className="h-3.5 w-3.5" />
          {active.length}/3 {t("scenarios.activeBranches")}
        </Badge>
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center rounded-md border border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5 p-0.5">
            <ViewButton mode="tree" active={viewMode} onClick={setViewMode} icon={Network} label={t("scenarioTree.viewTree")} />
            <ViewButton mode="compare" active={viewMode} onClick={setViewMode} icon={LineChart} label={t("scenarioTree.viewCompare")} />
            <ViewButton mode="evolve" active={viewMode} onClick={setViewMode} icon={Sparkles} label={t("scenarioTree.viewEvolution")} />
          </div>
          <Button size="sm" variant="outline" onClick={() => setShowCreate(true)} disabled={pathways.length === 0}>
            <Plus className="h-3.5 w-3.5 mr-1" />{t("scenarios.new")}
          </Button>
        </div>
      </div>

      {active.length > 3 && !warnDismissed && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">{t("scenarios.maxActiveWarn")}</span>
          <button type="button" onClick={() => setWarnDismissed(true)} title={t("scenarios.maxActiveWarnDismiss")}>
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <ScenarioCreateDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        goalId={goalId}
        pathways={pathways}
        onCreated={() => mutate()}
      />

      {scenarioList.length === 0 ? (
        <Card><CardHeader><CardTitle className="flex items-center gap-2"><GitBranch className="h-4 w-4" />{t("scenarioComparison.title")}</CardTitle><CardDescription>{t("scenarioComparison.empty")}</CardDescription></CardHeader></Card>
      ) : viewMode === "compare" ? (
        <ScenarioComparisonView scenarios={comparison} mutate={mutate} />
      ) : viewMode === "tree" ? (
        <div className="relative rounded-lg border border-black/5 dark:border-white/5 bg-surface overflow-hidden h-[calc(100vh-220px)] min-h-[500px]">
          <ScenarioTree scenarios={scenarioList} onSelect={setSelected} onRerun={mutate} selectedId={selected?.id ?? null} panelOpen={!!selected} />
          {selected && (
            <aside className="absolute right-4 top-4 bottom-4 w-80 xl:w-96 z-10 lg:block">
              <ScenarioDetailPanel scenario={selected} parentScenario={parent} onClose={() => setSelected(null)} onRerun={mutate} onBranched={mutate} onEvolve={() => setViewMode("evolve")} />
            </aside>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-black/5 dark:border-white/5 bg-surface overflow-hidden h-[calc(100vh-220px)] min-h-[500px]">
          {selected ? <ScenarioEvolution scenarioId={selected.id} scenarioName={selected.name} /> : <EmptyEvolution />}
        </div>
      )}
    </div>
  );
}

function ViewButton({ mode, active, onClick, icon: Icon, label }: {
  mode: ViewMode;
  active: ViewMode;
  onClick: (mode: ViewMode) => void;
  icon: typeof Network;
  label: string;
}) {
  return <button type="button" onClick={() => onClick(mode)} title={label} className={cn("inline-flex items-center gap-1 px-2 py-1 rounded text-xs", active === mode ? "bg-brand-500/20 text-brand-700 dark:text-brand-300" : "text-zinc-500 hover:text-zinc-800")}><Icon className="h-3.5 w-3.5" /><span className="hidden sm:inline">{label}</span></button>;
}

function EmptyEvolution() {
  const t = useT();
  return <div className="flex flex-col items-center justify-center h-full gap-3 text-center p-8"><Sparkles className="h-10 w-10 text-brand-600 opacity-60" /><p className="text-sm text-zinc-500 max-w-sm">{t("scenarioEvolution.selectScenario")}</p></div>;
}
