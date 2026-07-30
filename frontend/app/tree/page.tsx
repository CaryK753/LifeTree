"use client";

/**
 * Decision Tree index page — goal picker.
 *
 * The decision tree visualization lives at `/tree/[goalId]` and requires a
 * goal to scope the pathway tree. This index page lists all of the user's
 * goals as tappable cards so they can pick one to open its self-growing
 * decision tree. Mirrors the layout of `/goals` but links to `/tree/[id]`.
 */

import Link from "next/link";
import { Calendar, Tag, ArrowRight, TreePine, Compass } from "lucide-react";
import { useGoals } from "@/lib/hooks";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { useT } from "@/lib/i18n/provider";
import { formatDate } from "@/lib/utils";

export default function DecisionTreeIndexPage() {
  const t = useT();
  const { data: goals, isLoading } = useGoals();
  const allGoals = (goals ?? []) as any[];

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header>
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
          <SidebarToggleButton />
          <TreePine className="h-6 w-6 text-brand-600 dark:text-brand-400" />
          {t("tree.title")}
        </h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
          {t("tree.pickGoalHint")}
        </p>
      </header>

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Card key={i} className="opacity-80">
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-5 w-16 rounded-full" />
                </div>
                <Skeleton className="h-3 w-full mt-2" />
                <Skeleton className="h-3 w-1/2 mt-1" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-3/4 mt-2" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {allGoals.map((g: any) => {
          const statusRisk: "low" | "medium" | "high" =
            g.status === "active" ? "low"
            : g.status === "achieved" ? "low"
            : g.status === "paused" ? "medium"
            : g.status === "draft" ? "medium"
            : "high";
          return (
            <Link key={g.id} href={`/tree/${g.id}`} className="block group">
              <Card className="hover:border-brand-500/40 transition-colors h-full">
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="truncate">{g.title}</CardTitle>
                    {g.status && (
                      <Badge variant="risk" riskLevel={statusRisk} className="shrink-0">
                        {t(`status.${g.status}`)}
                      </Badge>
                    )}
                  </div>
                  <CardDescription className="mt-1 flex items-center gap-2 flex-wrap">
                    <span className="inline-flex items-center gap-1">
                      <Tag className="h-3 w-3" />
                      {g.scenario}
                    </span>
                    {g.target_date && (
                      <span className="inline-flex items-center gap-1">
                        <Calendar className="h-3 w-3" />
                        {g.target_date}
                      </span>
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-zinc-600 dark:text-zinc-400 line-clamp-2 min-h-[2rem]">
                    {g.description ?? t("goals.list.noDesc")}
                  </p>
                  <div className="mt-3 flex items-center justify-between text-[10px] text-zinc-500 dark:text-zinc-600">
                    <span>{t("goals.list.updatedAt", { date: formatDate(g.updated_at) })}</span>
                    <span className="inline-flex items-center gap-1 text-brand-600 dark:text-brand-400 group-hover:translate-x-0.5 transition-transform">
                      {t("goals.list.open")} <ArrowRight className="h-3 w-3" />
                    </span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}

        {allGoals.length === 0 && !isLoading && (
          <Card className="col-span-full">
            <CardContent className="py-12 text-center space-y-3">
              <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center">
                <Compass className="h-6 w-6 text-brand-600 dark:text-brand-400" />
              </div>
              <div className="text-sm text-zinc-700 dark:text-zinc-300">{t("tree.noGoals")}</div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-sm mx-auto">
                {t("tree.noGoalsHint")}
              </p>
              <Link
                href="/goals"
                className="inline-flex items-center gap-1.5 text-sm text-brand-600 dark:text-brand-400 hover:underline"
              >
                {t("nav.goals")}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
