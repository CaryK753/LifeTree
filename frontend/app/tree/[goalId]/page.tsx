"use client";

/**
 * Decision Tree page — thin wrapper around the reusable
 * DecisionTreeWorkspace component.
 *
 * The page owns the page-level header (sidebar toggle, back button,
 * GitBranch icon, goal title, "决策树" subtitle) and lets the workspace
 * fill the remaining viewport height with the canvas, side panel,
 * context menu, and add-child dialog.
 *
 * The actual tree visualization (React Flow, dagre layout, custom node
 * types, action handlers) lives in
 * @/components/tree/decision-tree-workspace and is shared with the
 * GoalTreeTab component for tab embedding.
 */

import { use } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ArrowLeft, GitBranch } from "lucide-react";

import { api } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { Button } from "@/components/ui/button";
import {
  getDecisionTree,
  type DecisionTreeNode,
} from "@/lib/api-decision-tree";
import { DecisionTreeWorkspace } from "@/components/tree/decision-tree-workspace";

export default function DecisionTreePage({
  params,
}: {
  params: Promise<{ goalId: string }>;
}) {
  const t = useT();
  const { goalId } = use(params);

  // Goal title for the top bar — fetch via the existing api.getGoal
  // which is shared with the goals page so SWR dedupes the request.
  // We also tap into the decision-tree SWR cache (same key as the
  // workspace) so the title can fall back to the tree's root name
  // before the goal record arrives.
  const { data: tree } = useSWR(
    ["decision-tree", goalId] as const,
    () => getDecisionTree(goalId),
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  const { data: goal } = useSWR(
    ["goal", goalId] as const,
    () => api.getGoal(goalId),
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  const goalTitle =
    ((goal as Record<string, unknown> | null)?.title as string | undefined) ??
    (tree as DecisionTreeNode | null)?.name ??
    goalId;

  return (
    <div className="flex flex-col h-full animate-fade-in">
      {/* Page-level header */}
      <header className="flex items-center justify-between gap-3 flex-wrap px-4 sm:px-6 lg:px-8 py-3 border-b border-black/5 dark:border-white/5 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <SidebarToggleButton />
          <Button asChild variant="ghost" size="icon-sm" className="shrink-0">
            <Link href={`/goals/${goalId}`} title={t("tree.back")}>
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <GitBranch className="h-5 w-5 text-brand-600 dark:text-brand-400 shrink-0" />
          <h1 className="text-base sm:text-lg font-semibold text-zinc-900 dark:text-zinc-100 truncate">
            {goalTitle}
          </h1>
          <span className="text-[11px] text-zinc-500 dark:text-zinc-400 shrink-0 hidden sm:inline">
            {t("tree.title")}
          </span>
        </div>
      </header>

      {/* Workspace fills the remaining height below the header.
          Override the default tab-friendly height (h-[60vh] min-h-[400px])
          with flex-grow so it fills the remaining viewport below the
          header instead of being capped at 60vh. */}
      <DecisionTreeWorkspace
        goalId={goalId}
        className="flex-1 min-h-0 h-auto border-0 rounded-none"
      />
    </div>
  );
}
