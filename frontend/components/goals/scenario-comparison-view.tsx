"use client";

import { GitBranch, Moon } from "lucide-react";
import type { KeyedMutator } from "swr";
import { ScenarioCurveOverlay } from "@/components/scenarios/scenario-curve-overlay";
import type { ScenarioNodeData } from "@/components/scenarios/scenario-tree";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

export function ScenarioComparisonView({
  scenarios,
  mutate,
}: {
  scenarios: ScenarioNodeData[];
  mutate: KeyedMutator<unknown[]>;
}) {
  const t = useT();
  const toast = useToast();

  async function toggleStatus(scenario: ScenarioNodeData) {
    const status = scenario.status === "dormant" ? "active" : "dormant";
    try {
      await api.updateScenario(scenario.id, { status });
      toast({
        title: status === "dormant" ? t("scenarios.toast.dormant") : t("scenarios.toast.activated"),
        variant: "success",
      });
      mutate();
    } catch (error: any) {
      toast({ title: t("scenarios.toast.failed"), description: error?.message, variant: "error" });
    }
  }

  return (
    <div className="space-y-4">
      <ScenarioCurveOverlay scenarios={scenarios} />
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
              <tr className="text-left text-zinc-500 border-b border-black/5 dark:border-white/5">
                <th className="py-2 pr-3 font-medium">{t("scenarioComparison.colScenario")}</th>
                <th className="py-2 px-3 font-medium">{t("scenarioComparison.colStatus")}</th>
                <th className="py-2 px-3 font-medium text-right">P10</th>
                <th className="py-2 px-3 font-medium text-right">P50</th>
                <th className="py-2 px-3 font-medium text-right">P90</th>
                <th className="py-2 px-3 font-medium">{t("scenarioComparison.colTopRisk")}</th>
                <th className="py-2 pl-3 font-medium text-right">{t("scenarios.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((scenario) => {
                const probability = scenario.success_probability ?? {};
                const risk = scenario.key_risk_factors?.[0];
                return (
                  <tr key={scenario.id} className="border-b border-black/5 dark:border-white/5 last:border-0">
                    <td className="py-2 pr-3 font-medium truncate max-w-[200px]">{scenario.name}</td>
                    <td className="py-2 px-3"><Status status={scenario.status} /></td>
                    <Probability value={probability.p10} />
                    <Probability value={probability.p50} emphasized />
                    <Probability value={probability.p90} />
                    <td className="py-2 px-3 text-zinc-500 truncate max-w-[180px]">
                      {risk ? `${risk.name} (${Math.round(risk.contribution * 100)}%)` : "—"}
                    </td>
                    <td className="py-2 pl-3 text-right">
                      <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={() => toggleStatus(scenario)}>
                        <Moon className="h-3 w-3 mr-1" />
                        {scenario.status === "dormant" ? t("scenarios.activate") : t("scenarios.dormant")}
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
  );
}

function Probability({ value, emphasized = false }: { value?: number; emphasized?: boolean }) {
  return <td className={cn("py-2 px-3 text-right tabular-nums", emphasized && "font-semibold text-brand-700 dark:text-brand-300")}>{value == null ? "—" : `${Math.round(value * 100)}%`}</td>;
}

function Status({ status }: { status: string }) {
  return <span className={cn("inline-block px-1.5 py-0.5 rounded text-[10px] font-medium", status === "active" ? "bg-emerald-500/15 text-emerald-700" : status === "draft" ? "bg-sky-500/15 text-sky-700" : status === "dormant" ? "bg-amber-500/15 text-amber-700" : "bg-zinc-500/15 text-zinc-600")}>{status}</span>;
}
