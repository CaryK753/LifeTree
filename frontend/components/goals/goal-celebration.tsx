"use client";

/**
 * Goal achievement celebration + graceful-exit guidance.
 *
 * Renders when a goal transitions to ``achieved`` or ``abandoned``.
 * Shows a confetti burst (CSS-only, no deps) for ``achieved``, then
 * a summary dialog with:
 *   - What was accomplished (milestone tally)
 *   - Next-step recommendations (graceful exit)
 *   - Links to create a new goal or revisit scenarios
 *
 * Per Phase 3 §5: milestone celebration + graceful exit guidance.
 */

import { useEffect, useState } from "react";
import { Award, CheckCircle2, Sparkles, Target, TrendingUp, X } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

interface Milestone {
  label?: string;
  status?: string;
  due?: string;
}

interface GoalCelebrationProps {
  /** Triggered when the user dismisses the overlay. */
  onClose: () => void;
  /** Goal title — shown in the headline. */
  goalTitle: string;
  /** Final status: "achieved" triggers confetti; "abandoned" skips it. */
  status: "achieved" | "abandoned";
  /** Milestones list — used to compute the completion tally. */
  milestones?: Milestone[];
  /** Optional scenario count — shown in the "what's next" section. */
  scenarioCount?: number;
}

const CONFETTI_COUNT = 24;

export function GoalCelebration({
  onClose,
  goalTitle,
  status,
  milestones = [],
  scenarioCount = 0,
}: GoalCelebrationProps) {
  const t = useT();
  const [confettiVisible, setConfettiVisible] = useState(status === "achieved");

  // Auto-hide confetti after the animation finishes (~3.5s).
  useEffect(() => {
    if (!confettiVisible) return;
    const timer = setTimeout(() => setConfettiVisible(false), 3500);
    return () => clearTimeout(timer);
  }, [confettiVisible]);

  // Close on Escape.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const completed = milestones.filter(
    (m) => m.status && /done|complete|met/i.test(m.status)
  ).length;
  const total = milestones.length;
  const pct = total ? Math.round((completed / total) * 100) : 0;

  const isAchieved = status === "achieved";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Confetti layer — pure CSS, pointer-events: none. */}
      {confettiVisible && (
        <div aria-hidden className="pointer-events-none">
          {Array.from({ length: CONFETTI_COUNT }, (_, i) => (
            <span key={i} className="confetti-piece" />
          ))}
        </div>
      )}

      <div
        className="relative w-full max-w-md rounded-2xl border border-black/5 dark:border-white/10 bg-white dark:bg-zinc-900 shadow-2xl animate-celebrate-pop"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          type="button"
          onClick={onClose}
          className="absolute top-3 right-3 p-1.5 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-black/5 dark:hover:bg-white/5"
          aria-label={t("common.close")}
        >
          <X className="h-4 w-4" />
        </button>

        <div className="px-6 pt-8 pb-6 text-center space-y-4">
          {/* Icon */}
          <div className="flex justify-center">
            {isAchieved ? (
              <div className="relative">
                <Award className="h-16 w-16 text-amber-500" />
                <Sparkles className="h-5 w-5 text-amber-400 absolute -top-1 -right-1" />
              </div>
            ) : (
              <Target className="h-14 w-14 text-zinc-400 dark:text-zinc-500" />
            )}
          </div>

          {/* Headline */}
          <div>
            <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">
              {isAchieved ? t("celebration.title") : t("celebration.exitTitle")}
            </h2>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
              {isAchieved
                ? t("celebration.subtitle", { goal: goalTitle })
                : t("celebration.exitSubtitle", { goal: goalTitle })}
            </p>
          </div>

          {/* Summary stats — milestone completion. */}
          {total > 0 && (
            <div className="grid grid-cols-3 gap-2 py-3 border-y border-black/5 dark:border-white/10">
              <Stat
                icon={<CheckCircle2 className="h-4 w-4 text-brand-500" />}
                value={`${completed}/${total}`}
                label={t("celebration.milestonesDone")}
              />
              <Stat
                icon={<TrendingUp className="h-4 w-4 text-blue-500" />}
                value={`${pct}%`}
                label={t("celebration.completion")}
              />
              <Stat
                icon={<Target className="h-4 w-4 text-amber-500" />}
                value={String(scenarioCount)}
                label={t("celebration.scenarios")}
              />
            </div>
          )}

          {/* Message */}
          <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">
            {isAchieved
              ? t("celebration.message")
              : t("celebration.exitMessage")}
          </p>

          {/* Next-step guidance — graceful exit. */}
          <div className="space-y-2 text-left">
            <div className="text-[11px] uppercase tracking-wider text-zinc-400 font-medium">
              {t("celebration.nextSteps")}
            </div>
            {isAchieved ? (
              <>
                <NextStep
                  href="/goals"
                  label={t("celebration.createNewGoal")}
                  hint={t("celebration.createNewGoalHint")}
                />
                {scenarioCount > 0 && (
                  <NextStep
                    href="/scenarios"
                    label={t("celebration.reviewScenarios")}
                    hint={t("celebration.reviewScenariosHint")}
                  />
                )}
                <NextStep
                  href="/dashboard"
                  label={t("celebration.viewDashboard")}
                  hint={t("celebration.viewDashboardHint")}
                />
              </>
            ) : (
              <>
                <NextStep
                  href="/goals"
                  label={t("celebration.exploreAlternatives")}
                  hint={t("celebration.exploreAlternativesHint")}
                />
                <NextStep
                  href="/sources"
                  label={t("celebration.reviewSources")}
                  hint={t("celebration.reviewSourcesHint")}
                />
              </>
            )}
          </div>

          {/* Dismiss button */}
          <Button onClick={onClose} className="w-full mt-2">
            {t("celebration.dismiss")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Stat({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: string;
  label: string;
}) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <div className="flex items-center gap-1">
        {icon}
        <span className="text-base font-semibold text-zinc-800 dark:text-zinc-200">
          {value}
        </span>
      </div>
      <span className="text-[10px] text-zinc-500 dark:text-zinc-400">{label}</span>
    </div>
  );
}

function NextStep({
  href,
  label,
  hint,
}: {
  href: string;
  label: string;
  hint: string;
}) {
  return (
    <Link
      href={href}
      className="block rounded-lg border border-black/5 dark:border-white/10 px-3 py-2 hover:bg-black/[0.02] dark:hover:bg-white/[0.03] transition-colors"
    >
      <div className="text-xs font-medium text-brand-700 dark:text-brand-300">
        {label}
      </div>
      <div className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5">
        {hint}
      </div>
    </Link>
  );
}
