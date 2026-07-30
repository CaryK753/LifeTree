"use client";

/**
 * DashboardBody — the analytical cards grid used by the goal overview tab.
 *
 * Extracted from `app/dashboard/page.tsx` so the same set of cards
 * (GoalCompass + Streak strip + RegretFreeActions + FactorBreakdown +
 * SurvivalCurve + RiskHeatmap + TimelineGantt + Milestones + EventFeed +
 * CredibilityMeter) can be rendered inside `/goals/[id]` overview tab
 * without duplicating the layout.
 */

import { useState } from "react";
import { useUserProfile } from "@/lib/hooks";
import { GoalCompass } from "@/components/dashboard/goal-compass";
import { RiskHeatmap } from "@/components/dashboard/risk-heatmap";
import { EventFeed } from "@/components/dashboard/event-feed";
import { Milestones } from "@/components/dashboard/milestones";
import { CredibilityMeter } from "@/components/dashboard/credibility-meter";
import { RegretFreeActions } from "@/components/dashboard/regret-free-actions";
import { FactorBreakdown } from "@/components/dashboard/factor-breakdown";
import { SurvivalCurve } from "@/components/dashboard/survival-curve";
import { TimelineGantt } from "@/components/dashboard/timeline-gantt";
import {
  Anchor,
  CalendarDays,
  Flame,
  Loader2,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { api, type DashboardSummary } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

export function DashboardBody({
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
      {/* Streak & Cruising strip — positive-progress signal per §6 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
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
        <CruisingStatChip />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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
          overallP={successProb.p50 ?? successProb.bayesian_point}
        />
        <SurvivalCurve
          curve={dashboard.survival_curve}
          keyRiskTimes={dashboard.key_risk_times}
          medianTimeMonths={dashboard.median_time_months}
        />
        <RiskHeatmap risks={riskHeatmap as any} />
        <TimelineGantt
          milestones={milestones}
          targetDate={dashboard.goal_target_date ?? undefined}
        />
        <Milestones milestones={milestones} />
        <EventFeed events={recentEvents} />
        <CredibilityMeter credibility={credibility} />
      </div>
    </div>
  );
}

export function CruisingStatChip() {
  const t = useT();
  const toast = useToast();
  const { data: profile, mutate } = useUserProfile();
  const [updating, setUpdating] = useState(false);

  const isCruising = Boolean((profile?.demographics as any)?.cruising_mode);

  async function handleToggle() {
    if (!profile || updating) return;
    const nextState = !isCruising;
    setUpdating(true);
    try {
      const currentDemo = (profile.demographics as Record<string, unknown>) || {};
      const nextProfile = await api.updateUser(profile.id, {
        demographics: {
          ...currentDemo,
          cruising_mode: nextState,
        },
      });
      await mutate(nextProfile, { revalidate: false });
      toast({
        title: t("dashboard.cruising.updated"),
        description: nextState
          ? t("dashboard.cruising.active")
          : t("dashboard.cruising.inactive"),
        variant: "success",
      });
    } catch (err: any) {
      toast({
        title: t("dashboard.cruising.updateFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setUpdating(false);
    }
  }

  return (
    <div
      onClick={handleToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleToggle();
        }
      }}
      className={cn(
        "rounded-md border px-3 py-2.5 flex items-center justify-between gap-3 cursor-pointer select-none transition-all duration-200",
        isCruising
          ? "border-teal-500/40 bg-teal-500/[0.12] text-teal-700 dark:text-teal-200 hover:border-teal-500/60"
          : "border-black/10 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.03] text-zinc-700 dark:text-zinc-300 hover:border-black/20 dark:hover:border-white/20",
        updating && "opacity-70 pointer-events-none"
      )}
    >
      <div className="flex items-center gap-3 min-w-0">
        <Anchor
          className={cn(
            "h-4 w-4 shrink-0 transition-transform duration-300",
            isCruising ? "text-teal-600 dark:text-teal-300 scale-110 rotate-12" : "opacity-80"
          )}
        />
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wide opacity-70">
            {t("dashboard.cruising.label")}
          </div>
          <div className="text-sm font-semibold truncate">
            {isCruising ? t("dashboard.cruising.active") : t("dashboard.cruising.inactive")}
          </div>
        </div>
      </div>
      <div className="shrink-0 flex items-center">
        {updating ? (
          <Loader2 className="h-4 w-4 animate-spin opacity-70" />
        ) : (
          <Switch
            checked={isCruising}
            tabIndex={-1}
            aria-label={t("dashboard.cruising.label")}
            className="pointer-events-none data-[state=checked]:bg-teal-500"
          />
        )}
      </div>
    </div>
  );
}

export function StatChip({
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
