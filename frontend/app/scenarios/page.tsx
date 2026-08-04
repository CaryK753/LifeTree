"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GitBranch, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { useGoals, useUserProfile } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";

export default function ScenariosRedirectPage() {
  const t = useT();
  const router = useRouter();
  const { data: profile } = useUserProfile();
  const { data: goals, isLoading } = useGoals();
  const [redirected, setRedirected] = useState(false);

  useEffect(() => {
    if (redirected || isLoading || !goals) return;
    const goalList = goals as Array<{ id: string }>;
    const goalId = profile?.primary_goal_id ?? goalList[0]?.id;
    setRedirected(true);
    router.replace(goalId ? `/goals/view?id=${encodeURIComponent(goalId)}&tab=scenarios` : "/goals");
  }, [goals, isLoading, profile?.primary_goal_id, redirected, router]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <h1 className="flex items-center gap-2 text-2xl font-semibold">
        <SidebarToggleButton />
        <GitBranch className="h-6 w-6 text-brand-500" />
        {t("scenarios.title")}
      </h1>
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("dashboard.redirecting")}
        </CardContent>
      </Card>
    </div>
  );
}
