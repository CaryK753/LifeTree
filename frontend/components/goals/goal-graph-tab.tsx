"use client";

/**
 * GoalGraphTab — embeds the Cytoscape knowledge graph as a tab inside
 * the goal workspace. Reuses the same KnowledgeGraph component as the
 * standalone /graph page.
 */

import { useGraph } from "@/lib/hooks";
import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { Skeleton } from "@/components/ui/skeleton";
import { Network } from "lucide-react";
import { useT } from "@/lib/i18n/provider";

export function GoalGraphTab({ goalId }: { goalId: string }) {
  const t = useT();
  const { data: graph, isLoading } = useGraph(goalId);

  const nodeCount = graph?.nodes?.length ?? 0;
  const edgeCount = graph?.edges?.length ?? 0;

  return (
    <div className="flex h-[calc(100vh-220px)] min-h-[500px] min-w-0 flex-col overflow-hidden rounded-lg border border-black/5 dark:border-white/5">
      {/* Header strip with counts */}
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-black/5 dark:border-white/5 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Network className="h-4 w-4 shrink-0 text-brand-600 dark:text-brand-400" />
          <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300 truncate">
            {t("graph.title")}
          </span>
        </div>
        {nodeCount > 0 && (
          <span className="shrink-0 text-[11px] text-zinc-500 dark:text-zinc-400">
            {t("graph.summary", { nodes: nodeCount, edges: edgeCount })}
          </span>
        )}
      </div>

      {/* Full-bleed graph canvas */}
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
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
            <p>{t("graph.noData")}</p>
          </div>
        )}
        {graph && (
          <KnowledgeGraph nodes={graph.nodes as any[]} edges={graph.edges as any[]} />
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 px-3 py-1.5 border-t border-black/5 dark:border-white/5 text-[10px] text-zinc-500 dark:text-zinc-400 shrink-0">
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
