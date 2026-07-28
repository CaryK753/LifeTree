"use client";

import { useState } from "react";
import { useGoals, useGraph, useScenarios } from "@/lib/hooks";
import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Network } from "lucide-react";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { Skeleton } from "@/components/ui/skeleton";

export default function GraphPage() {
  const t = useT();
  const { data: goals } = useGoals();
  const [goalId, setGoalId] = useState<string | undefined>();
  const selectedGoal = goalId ?? (goals as any[])?.[0]?.id;
  const { data: scenarios } = useScenarios(selectedGoal);
  const [scenarioId, setScenarioId] = useState<string | undefined>();
  const { data: graph, isLoading } = useGraph(selectedGoal, scenarioId);

  const nodeCount = graph?.nodes?.length ?? 0;
  const edgeCount = graph?.edges?.length ?? 0;

  return (
    <div className="flex flex-col h-full animate-fade-in">
      {/* Header — single flat bar: title + counts on the left,
          goal/scenario selectors on the right. No nested Card title. */}
      <header className="flex items-center justify-between gap-4 flex-wrap px-4 sm:px-6 lg:px-8 py-3 border-b border-black/5 dark:border-white/5 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <SidebarToggleButton />
          <Network className="h-5 w-5 text-brand-600 dark:text-brand-400 shrink-0" />
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 truncate">
            {t("graph.title")}
          </h1>
          {/* Node/edge counts — shown inline next to the title once data
              is loaded. Replaces the old nested CardDescription. */}
          {nodeCount > 0 && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400 shrink-0">
              {t("graph.summary", { nodes: nodeCount, edges: edgeCount })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Select value={selectedGoal ?? ""} onValueChange={(v) => setGoalId(v || undefined)}>
            <SelectTrigger className="w-48 h-8 text-xs">
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
            <SelectTrigger className="w-44 h-8 text-xs">
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

      {/* Full-bleed graph canvas — no Card wrapper, no nested title.
          The canvas fills all remaining vertical space below the header. */}
      <div className="flex-1 min-h-0 relative">
        {isLoading && (
          <div className="absolute inset-0 p-6 space-y-4">
            <div className="flex items-center justify-center h-48">
              <Skeleton className="h-32 w-32 rounded-full" />
            </div>
            <div className="flex justify-center gap-3 flex-wrap">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-2 w-20" />
              ))}
            </div>
          </div>
        )}
        {!isLoading && !graph && (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
            <Network className="h-8 w-8 opacity-40" />
            <p>{selectedGoal ? t("graph.noData") : t("graph.selectGoalHint")}</p>
          </div>
        )}
        {graph && (
          <KnowledgeGraph nodes={graph.nodes as any[]} edges={graph.edges as any[]} />
        )}
      </div>

      {/* Legend — thin strip at the bottom, outside the canvas */}
      <div className="flex flex-wrap items-center gap-3 px-4 sm:px-6 lg:px-8 py-2 border-t border-black/5 dark:border-white/5 text-[11px] text-zinc-500 dark:text-zinc-400 shrink-0">
        <Legend color="#3b8d61" label={t("graph.legend.goal")} />
        <Legend color="#5eab7f" label={t("graph.legend.pathway")} />
        <Legend color="#8fcaa6" label={t("graph.legend.requirement")} />
        <Legend color="#ef4444" label={t("graph.legend.riskFactor")} />
        <Legend color="#f59e0b" label={t("graph.legend.event")} />
        <Legend color="#94a3b8" label={t("graph.legend.source")} />
        <span className="text-zinc-400 dark:text-zinc-500 italic ml-auto">
          {t("graph.clickHint")}
        </span>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 text-zinc-500 dark:text-zinc-400">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
      <span>{label}</span>
    </div>
  );
}
