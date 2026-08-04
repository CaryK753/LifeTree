"use client";

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

export function DecisionTreePage({ goalId }: { goalId: string }) {
  const t = useT();
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
      <header className="flex items-center justify-between gap-3 flex-wrap px-4 sm:px-6 lg:px-8 py-3 border-b border-black/5 dark:border-white/5 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <SidebarToggleButton />
          <Button asChild variant="ghost" size="icon-sm" className="shrink-0">
            <Link href={`/goals/view?id=${encodeURIComponent(goalId)}`} title={t("tree.back")}>
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

      <DecisionTreeWorkspace
        goalId={goalId}
        className="flex-1 min-h-0 h-auto border-0 rounded-none"
      />
    </div>
  );
}
