"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { GoalDetailPage } from "@/components/goals/goal-detail-page";

function GoalView() {
  const goalId = useSearchParams().get("id");
  return goalId ? <GoalDetailPage goalId={goalId} /> : null;
}

export default function GoalViewPage() {
  return (
    <Suspense fallback={null}>
      <GoalView />
    </Suspense>
  );
}
