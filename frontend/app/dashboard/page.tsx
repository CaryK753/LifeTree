"use client";

/**
 * /dashboard — compatibility redirect to the goal workspace.
 *
 * The standalone dashboard page has been merged into /goals/[id] (the
 * goal workspace). This route picks the user's primary goal (or the
 * first goal in their list) and redirects there. If the user has no
 * goals yet, they land on /goals where they can create one.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useGoals, useUserProfile } from "@/lib/hooks";
import { Card, CardContent } from "@/components/ui/card";
import { Loader2, Compass } from "lucide-react";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

export default function DashboardRedirectPage() {
  const t = useT();
  const router = useRouter();
  const { data: profile } = useUserProfile();
  const { data: goals, isLoading } = useGoals();
  const [redirected, setRedirected] = useState(false);

  useEffect(() => {
    if (redirected) return;
    const goalList = (goals ?? []) as any[];
    const primaryId =
      profile?.primary_goal_id ?? (goalList.length > 0 ? goalList[0].id : null);
    if (primaryId) {
      setRedirected(true);
      router.replace(`/goals/${primaryId}`);
    } else if (!isLoading && !profile) {
      // No profile and goals fetch finished without data — fall back to
      // the goals list page so the user can create one.
      setRedirected(true);
      router.replace("/goals");
    }
  }, [profile, goals, isLoading, router, redirected]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 animate-fade-in">
      <header className="space-y-2 mb-6">
        <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
          <SidebarToggleButton />
          {t("dashboard.title")}
        </h1>
      </header>
      <Card>
        <CardContent className="py-12 flex flex-col items-center justify-center gap-3 text-sm text-zinc-500 dark:text-zinc-400">
          <Compass className="h-8 w-8 text-brand-400 animate-pulse" />
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("dashboard.redirecting")}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
