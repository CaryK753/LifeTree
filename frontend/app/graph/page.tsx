"use client";

import { useState } from "react";
import { useGoals, useGraph, useScenarios } from "@/lib/hooks";
import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Network, Layers } from "lucide-react";
import { useT } from "@/lib/i18n/provider";

export default function GraphPage() {
  const t = useT();
  const { data: goals } = useGoals();
  const [goalId, setGoalId] = useState<string | undefined>();
  const selectedGoal = goalId ?? (goals as any[])?.[0]?.id;
  const { data: scenarios } = useScenarios(selectedGoal);
  const [scenarioId, setScenarioId] = useState<string | undefined>();
  const { data: graph, isLoading } = useGraph(selectedGoal, scenarioId);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <Network className="h-6 w-6 text-brand-400" />
            {t("graph.title")}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">{t("graph.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={selectedGoal ?? ""} onValueChange={(v) => setGoalId(v || undefined)}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder={t("graph.selectGoal")} />
            </SelectTrigger>
            <SelectContent>
              {(goals as any[])?.map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={scenarioId ?? "__all__"}
            onValueChange={(v) => setScenarioId(v === "__all__" ? undefined : v)}
          >
            <SelectTrigger className="w-44">
              <SelectValue placeholder={t("graph.allScenarios")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">{t("graph.allScenarios")}</SelectItem>
              {(scenarios as any[])?.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </header>

      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Layers className="h-4 w-4 text-brand-400" />
              {t("graph.view")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("graph.summary", {
                nodes: graph?.nodes?.length ?? 0,
                edges: graph?.edges?.length ?? 0,
              })}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-[70vh] rounded-lg overflow-hidden border border-white/5 bg-surface-2/40">
            {isLoading && <div className="text-xs text-zinc-500 p-4">{t("common.loading")}</div>}
            {graph && (
              <KnowledgeGraph nodes={graph.nodes as any[]} edges={graph.edges as any[]} />
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-zinc-400">
            <Legend color="#3b8d61" label={t("graph.legend.goal")} />
            <Legend color="#5eab7f" label={t("graph.legend.pathway")} />
            <Legend color="#8fcaa6" label={t("graph.legend.requirement")} />
            <Legend color="#ef4444" label={t("graph.legend.riskFactor")} />
            <Legend color="#f59e0b" label={t("graph.legend.event")} />
            <Legend color="#94a3b8" label={t("graph.legend.source")} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 text-zinc-400">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
      <span>{label}</span>
    </div>
  );
}
