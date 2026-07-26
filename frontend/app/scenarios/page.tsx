"use client";

import { useState, useMemo } from "react";
import { useGoals, useScenarios } from "@/lib/hooks";
import { ScenarioTree, type ScenarioNodeData } from "@/components/scenarios/scenario-tree";
import { ScenarioDetailPanel } from "@/components/scenarios/scenario-detail-panel";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Loader2, Plus, X, GitBranch, Network, ListTree } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

type ViewMode = "tree" | "grid";

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
            description: "Invalid JSON",
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
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {t("scenarios.title")}
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            {t("scenarios.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
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
              onClick={() => setViewMode("grid")}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors",
                viewMode === "grid"
                  ? "bg-brand-500/20 text-brand-700 dark:text-brand-300"
                  : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
              )}
              title={t("scenarioTree.viewGrid")}
            >
              <ListTree className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">
                {t("scenarioTree.viewGrid")}
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
      ) : viewMode === "tree" ? (
        /* Tree view — React Flow canvas fills the area; detail panel floats
           above the canvas (absolute) and only appears when a node is selected.
           No extra layout space is consumed by the panel.

           Canvas height is sized to fill nearly the full viewport below
           the header so the tree has room to breathe. */
        <div className="relative rounded-xl border border-black/5 dark:border-white/5 bg-surface/30 overflow-hidden h-[calc(100vh-100px)] min-h-[600px]">
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
              />
            </aside>
          )}
        </div>
      ) : (
        /* Grid view — legacy comparison cards */
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {scenariosList.map((s) => (
            <ScenarioGridCard
              key={s.id}
              scenario={s as ScenarioNodeData}
              onRerun={mutate}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Grid card (lightweight, for grid view) ----------

function ScenarioGridCard({
  scenario,
  onRerun,
}: {
  scenario: ScenarioNodeData;
  onRerun?: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [showBranch, setShowBranch] = useState(false);
  const [branchName, setBranchName] = useState("");
  const [branching, setBranching] = useState(false);

  const p50 = scenario.success_probability?.p50;
  const p10 = scenario.success_probability?.p10;
  const p90 = scenario.success_probability?.p90;

  async function handleRun() {
    setRunning(true);
    try {
      await api.runScenario(scenario.id);
      onRerun?.();
    } catch (e: any) {
      toast({
        title: t("scenarioTree.runFailed"),
        description: e?.message,
        variant: "error",
      });
    } finally {
      setRunning(false);
    }
  }

  async function handleBranch() {
    if (!branchName.trim()) return;
    setBranching(true);
    try {
      await api.branchScenario(
        scenario.id,
        branchName.trim(),
        scenario.assumptions ?? {}
      );
      toast({ title: t("scenarios.toast.branched"), variant: "success" });
      setBranchName("");
      setShowBranch(false);
      onRerun?.();
    } catch (e: any) {
      toast({
        title: t("scenarios.toast.createFailed"),
        description: e?.message,
        variant: "error",
      });
    } finally {
      setBranching(false);
    }
  }

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            <span className="truncate">{scenario.name}</span>
          </CardTitle>
          {scenario.description && (
            <CardDescription className="mt-1">
              {scenario.description}
            </CardDescription>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 space-y-3">
        <div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400 mb-1">
            {t("scenarioComparison.successRange")}
          </div>
          <div className="text-2xl font-semibold text-brand-700 dark:text-brand-300">
            {p50 != null ? `${Math.round(p50 * 100)}%` : "—"}
          </div>
          <Progress value={(p50 ?? 0) * 100} className="mt-2" />
          <div className="flex justify-between text-[10px] text-zinc-500 dark:text-zinc-400 mt-1">
            <span>P10 {p10 != null ? `${Math.round(p10 * 100)}%` : "—"}</span>
            <span>P90 {p90 != null ? `${Math.round(p90 * 100)}%` : "—"}</span>
          </div>
        </div>

        {scenario.key_risk_factors && scenario.key_risk_factors.length > 0 && (
          <div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400 mb-1">
              {t("scenarioComparison.keyRisks")}
            </div>
            <div className="space-y-1">
              {scenario.key_risk_factors.slice(0, 3).map((rf, i) => (
                <div key={i} className="flex justify-between text-xs">
                  <span className="text-zinc-700 dark:text-zinc-300 truncate">{rf.name}</span>
                  <span className="text-zinc-500 dark:text-zinc-400">
                    {Math.round(rf.contribution * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {showBranch && (
          <div className="pt-2 border-t border-black/5 dark:border-white/5 space-y-2">
            <Input
              value={branchName}
              onChange={(e) => setBranchName(e.target.value)}
              placeholder={t("scenarios.create.namePlaceholder")}
              className="h-8 text-xs"
              autoFocus
            />
            <div className="flex items-center gap-1.5">
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={handleBranch}
                disabled={!branchName.trim() || branching}
              >
                {branching ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <GitBranch className="h-3 w-3 mr-1" />
                )}
                {t("scenarios.branch.submit")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => {
                  setShowBranch(false);
                  setBranchName("");
                }}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>

      <div className="mt-auto pt-3 border-t border-black/5 dark:border-white/5 flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={running}
          onClick={handleRun}
        >
          {running ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Plus className="h-3 w-3" />
          )}
          <span className="ml-1">{t("scenarioComparison.rerun")}</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={branching}
          onClick={() => {
            setShowBranch(true);
            setBranchName(`${scenario.name} (branch)`);
          }}
        >
          <GitBranch className="h-3 w-3" />
          <span className="ml-1">{t("scenarioComparison.branch")}</span>
        </Button>
      </div>
    </Card>
  );
}
