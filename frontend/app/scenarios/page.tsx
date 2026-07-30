"use client";

import { useState, useMemo, useEffect } from "react";
import { useGoals, useScenarios } from "@/lib/hooks";
import { ScenarioTree, type ScenarioNodeData } from "@/components/scenarios/scenario-tree";
import { ScenarioDetailPanel } from "@/components/scenarios/scenario-detail-panel";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Loader2, Plus, GitBranch, Network, LineChart, AlertTriangle, Moon, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { ScenarioCurveOverlay } from "@/components/scenarios/scenario-curve-overlay";
import { ScenarioEvolution } from "@/components/scenarios/scenario-evolution";

type ViewMode = "tree" | "compare" | "evolve";

export default function ScenariosPage() {
  const t = useT();
  const toast = useToast();
  const { data: goals } = useGoals();
  const [goalId, setGoalId] = useState<string | undefined>();
  const selected = goalId ?? (goals as any[])?.[0]?.id;
  const { data: scenarios, mutate } = useScenarios(selected);

  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    assumptions: "",
  });

  const [selectedScenario, setSelectedScenario] =
    useState<ScenarioNodeData | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("tree");

  const scenariosList = (scenarios as any[]) ?? [];

  // Active branches (max 3 allowed simultaneously per §5.5)
  const activeBranches = useMemo(() => {
    return scenariosList.filter(
      (s) => s.status === "active" || s.status === "draft"
    );
  }, [scenariosList]);
  const activeCount = activeBranches.length;

  // Auto-archive excess active branches if activeCount > 3
  useEffect(() => {
    if (activeCount > 3) {
      const excess = activeBranches.slice(3);
      Promise.all(
        excess.map((s) => api.updateScenario(s.id, { status: "dormant" }))
      ).then(() => {
        toast({
          title: "已自动休眠超限分支",
          description: "最多同时支持 3 个活跃对比分支，超出部分已自动设为休眠。",
          variant: "default",
        });
        mutate();
      });
    }
  }, [activeBranches, activeCount, mutate, toast]);

  // Look up parent scenario for the breadcrumb in the detail panel.
  const parentScenario = useMemo(() => {
    if (!selectedScenario?.parent_scenario_id) return null;
    return (
      (scenariosList.find((s) => s.id === selectedScenario.parent_scenario_id) as
        | ScenarioNodeData
        | undefined) ?? null
    );
  }, [selectedScenario, scenariosList]);

  async function handleCreate() {
    if (!selected || !form.name.trim()) return;
    setCreating(true);
    try {
      let assumptions: Record<string, unknown> = {};
      if (form.assumptions.trim()) {
        try {
          assumptions = JSON.parse(form.assumptions);
        } catch {
          toast({
            title: t("scenarios.toast.createFailed"),
            description: t("scenarios.invalidJson"),
            variant: "error",
          });
          setCreating(false);
          return;
        }
      }
      await api.createScenario({
        goal_id: selected,
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        assumptions,
      });
      toast({ title: t("scenarios.toast.created"), variant: "success" });
      setForm({ name: "", description: "", assumptions: "" });
      setShowCreate(false);
      mutate();
    } catch (e: any) {
      toast({
        title: t("scenarios.toast.createFailed"),
        description: e?.message,
        variant: "error",
      });
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-4">
      {/* Header */}
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            {t("scenarios.title")}
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            {t("scenarios.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {selected && (
            <Badge
              variant="default"
              className={cn(
                "gap-1 text-xs px-2.5 py-1 font-medium transition-colors",
                activeCount >= 3
                  ? "border-amber-500/40 text-amber-600 dark:text-amber-400 bg-amber-500/10"
                  : "border-emerald-500/40 text-emerald-600 dark:text-emerald-400 bg-emerald-500/10"
              )}
            >
              <GitBranch className="h-3.5 w-3.5" />
              <span>{activeCount}/3 活跃分支</span>
            </Badge>
          )}

          <select
            value={selected ?? ""}
            onChange={(e) => setGoalId(e.target.value)}
            className="h-8 rounded-md bg-black/5 dark:bg-white/5 border border-black/10 dark:border-white/10 px-2 text-xs text-zinc-800 dark:text-zinc-200"
          >
            <option value="">{t("scenarios.selectGoal")}</option>
            {(goals as any[])?.map((g) => (
              <option key={g.id} value={g.id}>
                {g.title}
              </option>
            ))}
          </select>

          {/* View mode toggle */}
          <div className="inline-flex items-center rounded-md border border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5 p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("tree")}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors",
                viewMode === "tree"
                  ? "bg-brand-500/20 text-brand-700 dark:text-brand-300"
                  : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
              )}
              title={t("scenarioTree.viewTree")}
            >
              <Network className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">
                {t("scenarioTree.viewTree")}
              </span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("compare")}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors",
                viewMode === "compare"
                  ? "bg-brand-500/20 text-brand-700 dark:text-brand-300"
                  : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
              )}
              title={t("scenarioTree.viewCompare")}
            >
              <LineChart className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">
                {t("scenarioTree.viewCompare")}
              </span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("evolve")}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors",
                viewMode === "evolve"
                  ? "bg-brand-500/20 text-brand-700 dark:text-brand-300"
                  : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
              )}
              title={t("scenarioTree.viewEvolution")}
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">
                {t("scenarioTree.viewEvolution")}
              </span>
            </button>
          </div>

          {selected && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowCreate((v) => !v)}
            >
              <Plus className="h-3.5 w-3.5 mr-1" />
              {t("scenarios.new")}
            </Button>
          )}
        </div>
      </header>

      {/* Warning banner when active branches >= 3 */}
      {selected && activeCount >= 3 && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
          <span>推荐保持 ≤3 个活跃分支以避免决策瘫痪</span>
        </div>
      )}

      {/* Create scenario dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("scenarios.create.title")}</DialogTitle>
            <DialogDescription>{t("scenarios.create.subtitle")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-xs">{t("scenarios.create.name")}</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t("scenarios.create.namePlaceholder")}
                className="h-9 text-sm"
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{t("scenarios.create.description")}</Label>
              <Input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder={t("scenarios.create.descriptionPlaceholder")}
                className="h-9 text-sm"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{t("scenarios.create.assumptions")}</Label>
              <Textarea
                value={form.assumptions}
                onChange={(e) => setForm({ ...form, assumptions: e.target.value })}
                placeholder={t("scenarios.create.assumptionsPlaceholder")}
                className="text-xs font-mono"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button size="sm" variant="ghost">{t("scenarios.create.cancel")}</Button>
            </DialogClose>
            <Button size="sm" onClick={handleCreate} disabled={!form.name.trim() || creating}>
              {creating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              ) : (
                <Plus className="h-3.5 w-3.5 mr-1" />
              )}
              {creating ? t("scenarios.create.creating") : t("scenarios.create.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Empty state */}
      {scenariosList.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              {t("scenarioComparison.title")}
            </CardTitle>
            <CardDescription>
              {t("scenarioComparison.empty")}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : viewMode === "compare" ? (
        /* Compare view — overlays survival curves from every scenario on a
           single chart so the user can visually contrast how each branch's
           probability of success evolves over time. §5 情景对比面板. */
        <div className="space-y-4">
          <ScenarioCurveOverlay scenarios={scenariosList} />

          {/* Per-scenario summary table — P10/P50/P90 + top risk factor */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-brand-600 dark:text-brand-400" />
                {t("scenarioComparison.summaryTable")}
              </CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-zinc-500 dark:text-zinc-400 border-b border-black/5 dark:border-white/5">
                    <th className="py-2 pr-3 font-medium">{t("scenarioComparison.colScenario")}</th>
                    <th className="py-2 px-3 font-medium">{t("scenarioComparison.colStatus")}</th>
                    <th className="py-2 px-3 font-medium text-right">P10</th>
                    <th className="py-2 px-3 font-medium text-right">P50</th>
                    <th className="py-2 px-3 font-medium text-right">P90</th>
                    <th className="py-2 px-3 font-medium">{t("scenarioComparison.colTopRisk")}</th>
                    <th className="py-2 px-3 font-medium text-right">{t("scenarioComparison.colMedian")}</th>
                    <th className="py-2 pl-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {scenariosList.map((s) => {
                    const p10 = s.success_probability?.p10;
                    const p50 = s.success_probability?.p50;
                    const p90 = s.success_probability?.p90;
                    const topRisk = s.key_risk_factors?.[0];
                    return (
                      <tr
                        key={s.id}
                        className="border-b border-black/5 dark:border-white/5 last:border-0"
                      >
                        <td className="py-2 pr-3 font-medium text-zinc-800 dark:text-zinc-200 truncate max-w-[200px]">
                          {s.name}
                        </td>
                        <td className="py-2 px-3">
                          <span
                            className={cn(
                              "inline-block px-1.5 py-0.5 rounded text-[10px] font-medium",
                              s.status === "active"
                                ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                                : s.status === "draft"
                                ? "bg-sky-500/15 text-sky-700 dark:text-sky-300"
                                : s.status === "dormant"
                                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                                : "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400"
                            )}
                          >
                            {s.status}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-zinc-700 dark:text-zinc-300">
                          {p10 != null ? `${Math.round(p10 * 100)}%` : "—"}
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums font-semibold text-brand-700 dark:text-brand-300">
                          {p50 != null ? `${Math.round(p50 * 100)}%` : "—"}
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-zinc-700 dark:text-zinc-300">
                          {p90 != null ? `${Math.round(p90 * 100)}%` : "—"}
                        </td>
                        <td className="py-2 px-3 text-zinc-600 dark:text-zinc-400 truncate max-w-[180px]">
                          {topRisk ? `${topRisk.name} (${Math.round(topRisk.contribution * 100)}%)` : "—"}
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-zinc-600 dark:text-zinc-400">
                          {s.median_time_months != null ? `${s.median_time_months}m` : "—"}
                        </td>
                        <td className="py-2 pl-3 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-[10px]"
                            onClick={async () => {
                              const nextStatus = s.status === "dormant" ? "active" : "dormant";
                              try {
                                await api.updateScenario(s.id, { status: nextStatus });
                                toast({
                                  title: nextStatus === "dormant" ? "分支已休眠" : "分支已激活",
                                  variant: "success",
                                });
                                mutate();
                              } catch (e: any) {
                                toast({ title: "操作失败", description: e?.message, variant: "error" });
                              }
                            }}
                          >
                            <Moon className="h-3 w-3 mr-1" />
                            {s.status === "dormant" ? "激活" : "休眠"}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      ) : viewMode === "tree" ? (
        /* Tree view — React Flow canvas fills the area; detail panel floats
           above the canvas (absolute) and only appears when a node is selected.
           No extra layout space is consumed by the panel.

           Canvas height is sized to fill nearly the full viewport below
           the header so the tree has room to breathe. */
        <div className="relative rounded-xl border border-black/5 dark:border-white/5 bg-surface overflow-hidden h-[calc(100vh-100px)] min-h-[600px]">
          <ScenarioTree
            scenarios={scenariosList}
            onSelect={setSelectedScenario}
            onRerun={mutate}
            selectedId={selectedScenario?.id ?? null}
          />
          {/* Floating detail panel — only when a node is selected */}
          {selectedScenario && (
            <aside className="absolute right-4 top-4 bottom-4 w-80 xl:w-96 z-10 lg:block">
              <ScenarioDetailPanel
                scenario={selectedScenario}
                parentScenario={parentScenario}
                onClose={() => setSelectedScenario(null)}
                onRerun={mutate}
                onBranched={mutate}
                onEvolve={() => setViewMode("evolve")}
              />
            </aside>
          )}
        </div>
      ) : viewMode === "evolve" ? (
        /* Evolution view — LLM-driven timeline projection of future events.
           The user picks a scenario in the tree view first; switching here
           shows the ScenarioEvolution component which calls
           POST /scenarios/{id}/evolve to invoke the chat-role LLM with a
           structured-output schema. The returned events are rendered as
           timeline nodes color-coded by type (milestone/risk/opportunity/
           decision), with a probability trajectory derived from the events. */
        <div className="rounded-xl border border-black/5 dark:border-white/5 bg-surface overflow-hidden h-[calc(100vh-100px)] min-h-[600px]">
          {selectedScenario ? (
            <ScenarioEvolution
              scenarioId={selectedScenario.id}
              scenarioName={selectedScenario.name}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-center p-8">
              <Sparkles className="h-10 w-10 text-brand-600 dark:text-brand-400 opacity-60" />
              <p className="text-sm text-zinc-500 dark:text-zinc-400 max-w-sm">
                {t("scenarioEvolution.selectScenario")}
              </p>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
