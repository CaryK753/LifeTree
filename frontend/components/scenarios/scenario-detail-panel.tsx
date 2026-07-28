"use client";

/**
 * ScenarioDetailPanel — side panel showing full details of a selected scenario.
 * Supports inline branching (create a child scenario) and re-running inference.
 */

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Loader2,
  Play,
  GitBranch,
  X,
  AlertTriangle,
  Clock,
  ChevronRight,
  Moon,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatPercent, formatDate } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import type { ScenarioNodeData } from "./scenario-tree";

interface Props {
  scenario: ScenarioNodeData | null;
  parentScenario?: ScenarioNodeData | null;
  onClose?: () => void;
  onRerun?: () => void;
  onBranched?: () => void;
}

export function ScenarioDetailPanel({
  scenario,
  parentScenario,
  onClose,
  onRerun,
  onBranched,
}: Props) {
  const t = useT();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [showBranch, setShowBranch] = useState(false);
  const [branchName, setBranchName] = useState("");
  const [branchAssumptions, setBranchAssumptions] = useState("");
  const [branching, setBranching] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);

  if (!scenario) return null;

  const p50 = scenario.success_probability?.p50;
  const p10 = scenario.success_probability?.p10;
  const p90 = scenario.success_probability?.p90;

  async function handleToggleDormant() {
    if (!scenario) return;
    const nextStatus = scenario.status === "dormant" ? "active" : "dormant";
    setUpdatingStatus(true);
    try {
      await api.updateScenario(scenario.id, { status: nextStatus });
      toast({
        title: nextStatus === "dormant" ? "分支已休眠" : "分支已激活",
        variant: "success",
      });
      onRerun?.();
    } catch (e: any) {
      toast({
        title: "操作失败",
        description: e?.message,
        variant: "error",
      });
    } finally {
      setUpdatingStatus(false);
    }
  }

  async function handleRun() {
    if (!scenario) return;
    setRunning(true);
    try {
      await api.runScenario(scenario.id);
      toast({ title: t("scenarioTree.runComplete"), variant: "success" });
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
    if (!scenario || !branchName.trim()) return;
    setBranching(true);
    try {
      let assumptions: Record<string, unknown> = {};
      if (branchAssumptions.trim()) {
        try {
          assumptions = JSON.parse(branchAssumptions);
        } catch {
          toast({
            title: t("scenarios.toast.createFailed"),
            description: "Invalid JSON",
            variant: "error",
          });
          setBranching(false);
          return;
        }
      }
      await api.branchScenario(scenario.id, branchName.trim(), assumptions);
      toast({ title: t("scenarios.toast.branched"), variant: "success" });
      setBranchName("");
      setBranchAssumptions("");
      setShowBranch(false);
      onBranched?.();
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
    <Card className="h-full flex flex-col overflow-hidden shadow-2xl shadow-black/40 backdrop-blur-md bg-surface/95">
      <CardHeader className="shrink-0">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="text-base flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-brand-400 shrink-0" />
              <span className="truncate">{scenario.name}</span>
            </CardTitle>
            {scenario.description && (
              <CardDescription className="mt-1 line-clamp-2">
                {scenario.description}
              </CardDescription>
            )}
          </div>
          {onClose && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              onClick={onClose}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap mt-1">
          <Badge
            variant="risk"
            riskLevel={
              scenario.status === "active"
                ? "low"
                : scenario.status === "draft"
                ? "medium"
                : "high"
            }
          >
            {scenario.status}
          </Badge>
          {parentScenario && (
            <span className="text-[10px] text-zinc-500 inline-flex items-center gap-1">
              <span className="truncate max-w-[100px]">{parentScenario.name}</span>
              <ChevronRight className="h-3 w-3" />
              <span className="text-zinc-400 truncate max-w-[100px]">
                {scenario.name}
              </span>
            </span>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-y-auto space-y-4">
        {/* Success probability */}
        <div>
          <div className="text-xs text-zinc-500 mb-1.5">
            {t("scenarioComparison.successRange")}
          </div>
          <div className="text-2xl font-semibold text-brand-300">
            {formatPercent(p50, 0)}
          </div>
          <Progress value={(p50 ?? 0) * 100} className="mt-2" />
          <div className="flex justify-between text-[10px] text-zinc-500 mt-1">
            <span>P10 {formatPercent(p10, 0)}</span>
            <span>P90 {formatPercent(p90, 0)}</span>
          </div>
        </div>

        {/* Key risks */}
        {scenario.key_risk_factors && scenario.key_risk_factors.length > 0 && (
          <div>
            <div className="text-xs text-zinc-500 mb-1.5 flex items-center gap-1">
              <AlertTriangle className="h-3 w-3 text-amber-400" />
              {t("scenarioComparison.keyRisks")}
            </div>
            <div className="space-y-1">
              {scenario.key_risk_factors.slice(0, 5).map((rf, i) => (
                <div
                  key={i}
                  className="flex justify-between text-xs p-1.5 rounded bg-white/[0.02] border border-white/5"
                >
                  <span className="text-zinc-300 truncate">{rf.name}</span>
                  <span
                    className={
                      rf.level === "high"
                        ? "text-red-400"
                        : rf.level === "medium"
                        ? "text-amber-400"
                        : "text-emerald-400"
                    }
                  >
                    {formatPercent(rf.contribution, 0)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Assumptions */}
        {scenario.assumptions &&
          Object.keys(scenario.assumptions).length > 0 && (
            <div>
              <div className="text-xs text-zinc-500 mb-1.5">
                {t("scenarioComparison.assumptions")}
              </div>
              <pre className="text-[10px] text-zinc-400 bg-white/5 rounded-md p-2 overflow-x-auto max-h-40">
                {JSON.stringify(scenario.assumptions, null, 2)}
              </pre>
            </div>
          )}

        {/* Computed time */}
        {scenario.computed_at && (
          <div className="text-[10px] text-zinc-600 flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {t("scenarioComparison.computedAt", {
              date: formatDate(scenario.computed_at),
            })}
          </div>
        )}

        {/* Branch dialog trigger — rendered inline as footer button */}
      </CardContent>

      {/* Footer actions */}
      <div className="shrink-0 pt-3 border-t border-white/5 flex items-center gap-2 px-4 pb-4">
        <Button
          variant="outline"
          size="sm"
          disabled={running}
          onClick={handleRun}
        >
          {running ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Play className="h-3 w-3" />
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
            setBranchAssumptions(
              scenario.assumptions
                ? JSON.stringify(scenario.assumptions, null, 2)
                : ""
            );
          }}
        >
          <GitBranch className="h-3 w-3" />
          <span className="ml-1">{t("scenarioComparison.branch")}</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={updatingStatus}
          onClick={handleToggleDormant}
          title={scenario.status === "dormant" ? "激活分支" : "归档/休眠分支"}
        >
          {updatingStatus ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Moon className="h-3 w-3" />
          )}
          <span className="ml-1">
            {scenario.status === "dormant" ? "激活" : "休眠"}
          </span>
        </Button>
      </div>

      {/* Branch dialog */}
      <Dialog open={showBranch} onOpenChange={setShowBranch}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("scenarios.branch.title")}</DialogTitle>
            <DialogDescription>{scenario.name}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-xs">{t("scenarios.create.name")}</Label>
              <Input
                value={branchName}
                onChange={(e) => setBranchName(e.target.value)}
                placeholder={t("scenarios.create.namePlaceholder")}
                className="h-9 text-sm"
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{t("scenarios.create.assumptions")}</Label>
              <Textarea
                value={branchAssumptions}
                onChange={(e) => setBranchAssumptions(e.target.value)}
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
            <Button size="sm" onClick={handleBranch} disabled={!branchName.trim() || branching}>
              {branching ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              ) : (
                <GitBranch className="h-3.5 w-3.5 mr-1" />
              )}
              {t("scenarios.branch.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
