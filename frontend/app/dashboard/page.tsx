"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useDashboard, useGoals, useUserProfile } from "@/lib/hooks";
import { GoalCompass } from "@/components/dashboard/goal-compass";
import { RiskHeatmap } from "@/components/dashboard/risk-heatmap";
import { EventFeed } from "@/components/dashboard/event-feed";
import { Milestones } from "@/components/dashboard/milestones";
import { CredibilityMeter } from "@/components/dashboard/credibility-meter";
import { RegretFreeActions } from "@/components/dashboard/regret-free-actions";
import { FactorBreakdown } from "@/components/dashboard/factor-breakdown";
import { SurvivalCurve } from "@/components/dashboard/survival-curve";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Gauge,
  Loader2,
  Target,
  CalendarDays,
  Flame,
  ArrowRight,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import type { DashboardSummary } from "@/lib/api";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

export default function DashboardPage() {
  const t = useT();
  const { data: profile } = useUserProfile();
  const { data: goals, isLoading: goalsLoading, error: goalsError } = useGoals();

  const statusLabel = (s?: string) => (s ? t(`status.${s}`) : "—");

  // Pick the active goal: explicit selection > primary_goal_id > first goal.
  const [selectedId, setSelectedId] = useState<string | undefined>();
  useEffect(() => {
    if (selectedId) return;
    if (profile?.primary_goal_id) {
      setSelectedId(profile.primary_goal_id);
    } else if ((goals as any[])?.length) {
      setSelectedId((goals as any[])[0].id);
    }
  }, [profile, goals, selectedId]);

  const goalId = selectedId;
  const { data: dashboard, isLoading, error: dashboardError } = useDashboard(goalId);

  const goalList = (goals ?? []) as any[];
  const activeGoal = goalList.find((g) => g.id === goalId);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <Gauge className="h-6 w-6 text-brand-400" />
            {t("dashboard.title")}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">
            {t("dashboard.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={goalId ?? "__none__"}
            onValueChange={(v) => setSelectedId(v === "__none__" ? undefined : v)}
          >
            <SelectTrigger className="h-9 w-56 text-sm">
              <SelectValue placeholder={t("dashboard.selectGoal")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{t("dashboard.notSelected")}</SelectItem>
              {goalList.map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {goalId && (
            <Button asChild variant="outline" size="sm">
              <Link href={`/goals/${goalId}`}>
                {t("dashboard.viewDetail")}
                <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
              </Link>
            </Button>
          )}
        </div>
      </header>

      {goalsLoading && !goalList.length ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-zinc-500 flex items-center justify-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("dashboard.loading")}
          </CardContent>
        </Card>
      ) : goalsError && !goalList.length ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-red-500 dark:text-red-400 space-y-2">
            <p>{t("dashboard.loadFailed")}</p>
            <p className="text-xs text-zinc-400 dark:text-zinc-500">{String(goalsError?.message ?? goalsError)}</p>
          </CardContent>
        </Card>
      ) : !goalList.length ? (
        <EmptyGoalState />
      ) : !goalId ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-zinc-500 flex items-center justify-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("dashboard.loading")}
          </CardContent>
        </Card>
      ) : isLoading && !dashboard ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-zinc-500 flex items-center justify-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("dashboard.loadingDashboard")}
          </CardContent>
        </Card>
      ) : dashboardError && !dashboard ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-red-500 dark:text-red-400 space-y-2">
            <p>{t("dashboard.loadFailed")}</p>
            <p className="text-xs text-zinc-400 dark:text-zinc-500">{String(dashboardError?.message ?? dashboardError)}</p>
          </CardContent>
        </Card>
      ) : dashboard ? (
        <DashboardBody
          dashboard={dashboard}
          goalTitle={activeGoal?.title ?? dashboard.goal_title ?? "—"}
          statusLabel={statusLabel}
        />
      ) : null}
    </div>
  );
}

function DashboardBody({
  dashboard,
  goalTitle,
  statusLabel,
}: {
  dashboard: DashboardSummary;
  goalTitle: string;
  statusLabel: (s?: string) => string;
}) {
  const t = useT();
  const successProb = dashboard.success_probability ?? {};
  const milestones = dashboard.milestones ?? [];
  const recentEvents = (dashboard.recent_events ?? []) as any[];
  const riskHeatmap = dashboard.risk_heatmap ?? [];
  const credibility = dashboard.credibility;
  const streak = dashboard.consecutive_planning_days ?? 0;

  const computedAt = successProb.computed_at as string | undefined;
  const hasProbability =
    successProb.p50 != null ||
    successProb.bayesian_point != null ||
    successProb.overall_risk != null;

  return (
    <div className="space-y-4">
      {/* Streak strip — positive-progress signal per §6 */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatChip
          icon={Flame}
          label={t("dashboard.streak.label")}
          value={`${streak}`}
          hint={streak > 0 ? t("dashboard.streak.keepGoing") : t("dashboard.streak.firstStep")}
          tone={streak > 0 ? "warm" : "muted"}
        />
        <StatChip
          icon={CalendarDays}
          label={t("dashboard.targetDate.label")}
          value={
            dashboard.goal_target_date
              ? new Date(dashboard.goal_target_date).toLocaleDateString(undefined)
              : t("dashboard.targetDate.notSet")
          }
          hint={dashboard.goal_status ? statusLabel(dashboard.goal_status) : "—"}
          tone="brand"
        />
        <StatChip
          icon={Sparkles}
          label={t("dashboard.inference.label")}
          value={hasProbability ? t("dashboard.inference.generated") : t("dashboard.inference.none")}
          hint={computedAt ? t("dashboard.inference.updatedAt", { time: new Date(computedAt).toLocaleString() }) : t("dashboard.inference.goRun")}
          tone={hasProbability ? "good" : "muted"}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GoalCompass
          goalId={dashboard.goal_id}
          title={goalTitle}
          scenario={dashboard.goal_scenario}
          targetDate={dashboard.goal_target_date ?? undefined}
          status={dashboard.goal_status}
          successProbability={successProb as any}
          activeScenarios={dashboard.active_scenarios}
        />
        <RegretFreeActions
          actions={dashboard.regret_free_actions ?? []}
          explanation={dashboard.reasoning_explanation}
          iterations={dashboard.reasoning_iterations}
          medianTimeMonths={dashboard.median_time_months}
        />
        <FactorBreakdown
          factors={dashboard.factor_contributions ?? []}
        />
        <SurvivalCurve
          curve={dashboard.survival_curve}
          keyRiskTimes={dashboard.key_risk_times}
          medianTimeMonths={dashboard.median_time_months}
        />
        <RiskHeatmap risks={riskHeatmap as any} />
        <Milestones milestones={milestones} />
        <EventFeed events={recentEvents} />
        <CredibilityMeter credibility={credibility} />
      </div>
    </div>
  );
}

function StatChip({
  icon: Icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: typeof Flame;
  label: string;
  value: string;
  hint?: string;
  tone: "brand" | "warm" | "good" | "muted";
}) {
  const toneCls = {
    // Light mode: -700/-800 colors read well on pale tinted backgrounds.
    // Dark mode (default): -200/-300 colors keep the original look.
    brand: "border-brand-500/30 bg-brand-500/[0.07] text-brand-700 dark:text-brand-200",
    warm: "border-amber-500/30 bg-amber-500/[0.07] text-amber-700 dark:text-amber-200",
    good: "border-emerald-500/30 bg-emerald-500/[0.07] text-emerald-700 dark:text-emerald-200",
    muted: "border-black/10 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.03] text-zinc-700 dark:text-zinc-300",
  }[tone];
  return (
    <div className={cn("rounded-md border px-3 py-2.5 flex items-center gap-3", toneCls)}>
      <Icon className="h-4 w-4 shrink-0 opacity-80" />
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wide opacity-70">{label}</div>
        <div className="text-sm font-semibold truncate">{value}</div>
        {hint && <div className="text-[10px] opacity-60 truncate">{hint}</div>}
      </div>
    </div>
  );
}

function EmptyGoalState() {
  const t = useT();
  return (
    <Card>
      <CardContent className="py-12 text-center space-y-3">
        <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center">
          <Target className="h-6 w-6 text-brand-400" />
        </div>
        <div className="text-sm text-zinc-300">{t("dashboard.empty.title")}</div>
        <p className="text-xs text-zinc-500 max-w-sm mx-auto">
          {t("dashboard.empty.hint")}
        </p>
        <Button asChild className="mt-2">
          <Link href="/goals">
            <Target className="h-4 w-4 mr-1.5" /> {t("dashboard.empty.create")}
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
