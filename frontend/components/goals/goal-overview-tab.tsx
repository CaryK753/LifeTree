"use client";

import { ChangesSummaryBanner } from "@/components/dashboard/changes-summary-banner";
import { DashboardBody } from "@/components/dashboard/dashboard-body";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n/provider";
import type { DashboardSummary } from "@/lib/api";

export function GoalOverviewTab({
  dashboard,
  goalTitle,
  isLoading,
}: {
  dashboard?: DashboardSummary;
  goalTitle: string;
  isLoading: boolean;
}) {
  const t = useT();
  return (
    <div className="space-y-4">
      <ErrorBoundary title={t("changes.errorTitle")}>
        <ChangesSummaryBanner />
      </ErrorBoundary>
      {isLoading && !dashboard ? (
        <div className="space-y-4">
          <Card>
            <CardContent className="p-6 flex items-center gap-6">
              <Skeleton className="h-32 w-32 rounded-full shrink-0" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-5 w-1/3" />
                <Skeleton className="h-3 w-1/2" />
                <Skeleton className="h-2 w-2/3" />
                <Skeleton className="h-2 w-1/2" />
              </div>
            </CardContent>
          </Card>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {[0, 1, 2, 3, 4, 5].map((index) => (
              <Card key={index}>
                <CardContent className="p-4 space-y-3">
                  <Skeleton className="h-3.5 w-1/3" />
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-2 w-2/3" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ) : dashboard ? (
        <ErrorBoundary>
          <DashboardBody
            dashboard={dashboard}
            goalTitle={goalTitle}
            statusLabel={(status) => (status ? t(`status.${status}`) : "—")}
          />
        </ErrorBoundary>
      ) : null}
    </div>
  );
}
