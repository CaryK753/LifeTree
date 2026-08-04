"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { DecisionTreePage } from "@/components/tree/decision-tree-page";

function DecisionTreeView() {
  const goalId = useSearchParams().get("goalId");
  return goalId ? <DecisionTreePage goalId={goalId} /> : null;
}

export default function DecisionTreeViewPage() {
  return (
    <Suspense fallback={null}>
      <DecisionTreeView />
    </Suspense>
  );
}
