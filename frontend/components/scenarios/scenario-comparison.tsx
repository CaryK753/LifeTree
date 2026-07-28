"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Loader2, Play, GitBranch, GitMerge, X, Moon } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { formatPercent, formatDate } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";

interface Scenario {
  id: string;
  name: string;
  description?: string;
  status: string;
  parent_scenario_id?: string | null;
  assumptions?: Record<string, unknown>;
  success_probability?: {
    p10?: number;
    p50?: number;
    p90?: number;
    bayesian_point?: number;
    p_by_target_date?: number;
  };
  risk_score?: number | null;
  key_risk_factors?: Array<{ name: string; level: string; contribution: number }>;
  computed_at?: string | null;
}

interface Props {
  scenarios: Scenario[];
  onRerun?: () => void;
}

export function ScenarioComparison({ scenarios, onRerun }: Props) {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const [running, setRunning] = useState<string | null>(null);
  const [mergingId, setMergingId] = useState<string | null>(null);
  const [branchingId, setBranchingId] = useState<string | null>(null);
  const [branchName, setBranchName] = useState("");
  const [branching, setBranching] = useState(false);
  const [updatingStatusId, setUpdatingStatusId] = useState<string | null>(null);

  async function handleToggleDormant(s: Scenario) {
    const nextStatus = s.status === "dormant" ? "active" : "dormant";
    setUpdatingStatusId(s.id);
    try {
      await api.updateScenario(s.id, { status: nextStatus });
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
      setUpdatingStatusId(null);
    }
  }

  async function handleRun(id: string) {
    setRunning(id);
    try {
      await api.runScenario(id);
      onRerun?.();
    } finally {
      setRunning(null);
    }
  }

  async function handleBranch(parent: Scenario) {
    if (!branchName.trim()) return;
    setBranching(true);
    try {
      const assumptions = parent.assumptions ?? {};
      await api.branchScenario(parent.id, branchName.trim(), assumptions);
      toast({ title: t("scenarios.toast.branched"), variant: "success" });
      setBranchName("");
      setBranchingId(null);
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

  async function handleMerge(s: Scenario) {
    if (!s.parent_scenario_id) {
      toast({
        title: t("scenarios.toast.mergeFailed"),
        description: t("scenarios.toast.noParent"),
        variant: "warning",
      });
      return;
    }
    const ok = await confirm({
      title: t("scenarioComparison.merge"),
      description: t("scenarioComparison.mergeHint"),
      confirmLabel: t("scenarioComparison.merge"),
      cancelLabel: t("common.cancel"),
    });
    if (!ok) return;
    setMergingId(s.id);
    try {
      await api.mergeScenario(s.id);
      toast({ title: t("scenarios.toast.merged"), variant: "success" });
      onRerun?.();
    } catch (e: any) {
      const detail = (e as { details?: { detail?: string } })?.details?.detail;
      toast({
        title: t("scenarios.toast.mergeFailed"),
        description: detail ?? e?.message,
        variant: "error",
      });
    } finally {
      setMergingId(null);
    }
  }

  if (scenarios.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("scenarioComparison.title")}</CardTitle>
          <CardDescription>{t("scenarioComparison.empty")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {scenarios.map((s) => {
        const p50 = s.success_probability?.p50;
        const p10 = s.success_probability?.p10;
        const p90 = s.success_probability?.p90;
        const isRunning = running === s.id;
        const isBranching = branchingId === s.id;
        const isMerging = mergingId === s.id;
        const canMerge = !!s.parent_scenario_id && s.status !== "merged" && s.status !== "closed";

        return (
          <Card key={s.id} className="flex flex-col">
            <CardHeader>
              <div>
                <CardTitle className="flex items-center gap-2">
                  <GitBranch className="h-4 w-4 text-brand-400" />
                  <span className="truncate">{s.name}</span>
                </CardTitle>
                <CardDescription className="mt-1">{s.description}</CardDescription>
              </div>
              <Badge variant="risk" riskLevel={
                s.status === "active" ? "low"
                : s.status === "draft" ? "medium"
                : "high"
              }>
                {s.status}
              </Badge>
            </CardHeader>

            <CardContent className="flex-1 space-y-3">
              <div>
                <div className="text-xs text-zinc-500 mb-1">
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

              {s.key_risk_factors && s.key_risk_factors.length > 0 && (
                <div>
                  <div className="text-xs text-zinc-500 mb-1">
                    {t("scenarioComparison.keyRisks")}
                  </div>
                  <div className="space-y-1">
                    {s.key_risk_factors.slice(0, 3).map((rf, i) => (
                      <div key={i} className="flex justify-between text-xs">
                        <span className="text-zinc-300 truncate">{rf.name}</span>
                        <span className="text-zinc-500">{formatPercent(rf.contribution, 0)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {s.assumptions && Object.keys(s.assumptions).length > 0 && (
                <div>
                  <div className="text-xs text-zinc-500 mb-1">
                    {t("scenarioComparison.assumptions")}
                  </div>
                  <pre className="text-[10px] text-zinc-400 bg-white/5 rounded-md p-2 overflow-x-auto">
                    {JSON.stringify(s.assumptions, null, 2)}
                  </pre>
                </div>
              )}

              <div className="text-[10px] text-zinc-600">
                {t("scenarioComparison.computedAt", { date: formatDate(s.computed_at) })}
              </div>

              {isBranching && (
                <div className="pt-2 border-t border-white/5 space-y-2">
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
                      onClick={() => handleBranch(s)}
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
                        setBranchingId(null);
                        setBranchName("");
                      }}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>

            <div className="mt-auto pt-3 border-t border-white/5 flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={isRunning}
                onClick={() => handleRun(s.id)}
              >
                {isRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                <span className="ml-1">{t("scenarioComparison.rerun")}</span>
              </Button>
              {!isBranching && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={branching}
                  onClick={() => {
                    setBranchingId(s.id);
                    setBranchName(`${s.name} (branch)`);
                  }}
                >
                  <GitBranch className="h-3 w-3" />
                  <span className="ml-1">{t("scenarioComparison.branch")}</span>
                </Button>
              )}
              {canMerge && !isBranching && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={isMerging || branching}
                  onClick={() => handleMerge(s)}
                  title={t("scenarioComparison.mergeHint")}
                >
                  {isMerging ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <GitMerge className="h-3 w-3" />
                  )}
                  <span className="ml-1">{t("scenarioComparison.merge")}</span>
                </Button>
              )}
              {!isBranching && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={updatingStatusId === s.id}
                  onClick={() => handleToggleDormant(s)}
                  title={s.status === "dormant" ? "激活分支" : "归档/休眠分支"}
                >
                  {updatingStatusId === s.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Moon className="h-3 w-3" />
                  )}
                  <span className="ml-1">
                    {s.status === "dormant" ? "激活" : "休眠"}
                  </span>
                </Button>
              )}
            </div>
          </Card>
        );
      })}
      {ConfirmRoot}
    </div>
  );
}
