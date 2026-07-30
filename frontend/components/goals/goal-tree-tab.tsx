"use client";

/**
 * GoalTreeTab — embeds the decision-tree visualization as a tab inside
 * the goal workspace. Reuses the same DecisionTreeWorkspace component
 * as the standalone /tree/[goalId] page.
 *
 * The workspace is wrapped in a tab-friendly container with a fixed
 * viewport-derived height (similar to GoalScenariosTab) so the canvas
 * can render at a sensible size without overflowing the workspace
 * tab panel.
 */

import { DecisionTreeWorkspace } from "@/components/tree/decision-tree-workspace";

export function GoalTreeTab({ goalId }: { goalId: string }) {
  return (
    <div className="h-[calc(100vh-220px)] min-h-[500px] rounded-lg border border-black/5 dark:border-white/5 overflow-hidden">
      <DecisionTreeWorkspace
        goalId={goalId}
        className="h-full min-h-0 border-0 rounded-none"
      />
    </div>
  );
}
