"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useGoals } from "@/lib/hooks";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Compass,
  ArrowRight,
  Calendar,
  Tag,
  CheckCircle2,
  CircleDot,
  Pause,
  AlertTriangle,
  Clock,
  User,
  Upload,
} from "lucide-react";
import { formatDate } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

const SCENARIO_KEYS = ["fsw", "uk-study", "job-switch", "house", "generic"] as const;

function daysBetween(from: Date, to: Date): number {
  // Round to calendar days (ignores DST/time-of-day differences).
  const ms = 1000 * 60 * 60 * 24;
  const a = Date.UTC(from.getFullYear(), from.getMonth(), from.getDate());
  const b = Date.UTC(to.getFullYear(), to.getMonth(), to.getDate());
  return Math.round((b - a) / ms);
}

export default function HomePage() {
  const { data: goals, isLoading } = useGoals();
  const t = useT();

  const statusLabel = (s?: string) => (s ? t(`status.${s}`) : "—");

  const statusRisk = (s?: string): "low" | "medium" | "high" =>
    s === "active" ? "low"
    : s === "achieved" ? "low"
    : s === "paused" ? "medium"
    : s === "draft" ? "medium"
    : s === "abandoned" ? "high"
    : "high";

  const scenarioLabel = (s?: string) => {
    if (!s) return "—";
    return SCENARIO_KEYS.includes(s as any) ? t(`scenario.${s}`) : s;
  };

  const allGoals = (goals ?? []) as any[];

  // Aggregate stats — counts by status, plus upcoming/overdue by target_date.
  const stats = useMemo(() => {
    const today = new Date();
    const counts = {
      total: allGoals.length,
      active: 0,
      achieved: 0,
      paused: 0,
      draft: 0,
      abandoned: 0,
      upcoming: 0, // due within 30 days, status active
      overdue: 0,  // past target_date, status still active/paused
    };
    for (const g of allGoals) {
      switch (g.status) {
        case "active": counts.active++; break;
        case "achieved": counts.achieved++; break;
        case "paused": counts.paused++; break;
        case "draft": counts.draft++; break;
        case "abandoned": counts.abandoned++; break;
      }
      if (g.target_date && (g.status === "active" || g.status === "paused")) {
        const d = new Date(String(g.target_date));
        if (!isNaN(d.getTime())) {
          const days = daysBetween(today, d);
          if (days < 0) counts.overdue++;
          else if (days <= 30) counts.upcoming++;
        }
      }
    }
    return counts;
  }, [allGoals]);

  // Most recently updated goals first — keep the card grid deterministic.
  const recentGoals = useMemo(
    () =>
      [...allGoals].sort(
        (a, b) =>
          (b.updated_at ?? 0) - (a.updated_at ?? 0) ||
          (b.created_at ?? 0) - (a.created_at ?? 0)
      ),
    [allGoals]
  );

  const statCards = [
    {
      key: "total",
      label: t("home.stats.total"),
      value: stats.total,
      icon: Compass,
      color: "text-brand-600 dark:text-brand-400",
      ring: "bg-brand-500/10",
    },
    {
      key: "active",
      label: t("home.stats.active"),
      value: stats.active,
      icon: CircleDot,
      color: "text-emerald-600 dark:text-emerald-400",
      ring: "bg-emerald-500/10",
    },
    {
      key: "achieved",
      label: t("home.stats.achieved"),
      value: stats.achieved,
      icon: CheckCircle2,
      color: "text-sky-600 dark:text-sky-400",
      ring: "bg-sky-500/10",
    },
    {
      key: "upcoming",
      label: t("home.stats.upcoming"),
      value: stats.upcoming,
      icon: Clock,
      color: "text-amber-600 dark:text-amber-400",
      ring: "bg-amber-500/10",
      hint: t("home.stats.upcomingHint"),
    },
    {
      key: "overdue",
      label: t("home.stats.overdue"),
      value: stats.overdue,
      icon: AlertTriangle,
      color: "text-red-600 dark:text-red-400",
      ring: "bg-red-500/10",
    },
    {
      key: "paused",
      label: t("home.stats.paused"),
      value: stats.paused,
      icon: Pause,
      color: "text-zinc-500 dark:text-zinc-400",
      ring: "bg-zinc-500/10",
    },
  ] as const;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8 animate-fade-in">
      <header className="space-y-4">
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
              <SidebarToggleButton />
              <Compass className="h-6 w-6 text-brand-600 dark:text-brand-400" />
              {t("home.title")}
            </h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
              {t("home.subtitle")}
            </p>
          </div>
          {/* Replaced the "New Goal" button with a lighter "view all" link
              so the overview stays informational — goal creation lives on
              the /goals page where the dialog form already exists. */}
          <Button asChild size="sm" variant="outline">
            <Link href="/goals">
              {t("home.viewAll")}
              <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
            </Link>
          </Button>
        </div>
      </header>

      {isLoading && (
        <div className="text-sm text-zinc-500 dark:text-zinc-400">{t("common.loading")}</div>
      )}

      {/* Stats summary — only meaningful once we have at least one goal. */}
      {!isLoading && allGoals.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {statCards.map((s) => {
            const Icon = s.icon;
            return (
              <Card key={s.key} className="py-3">
                <CardContent className="px-4 py-0 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                      {s.label}
                    </span>
                    <span className={`h-7 w-7 rounded-md ${s.ring} flex items-center justify-center`}>
                      <Icon className={`h-3.5 w-3.5 ${s.color}`} />
                    </span>
                  </div>
                  <div className={`text-2xl font-semibold ${s.color}`}>{s.value}</div>
                  {s.key === "upcoming" && s.hint ? (
                    <div className="text-[10px] text-zinc-500 dark:text-zinc-500">{s.hint}</div>
                  ) : null}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Recently-updated goals */}
      {!isLoading && allGoals.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <div>
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                {t("home.recentTitle")}
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                {t("home.recentHint")}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {recentGoals.map((g) => {
              const status = g.status as string | undefined;
              const risk = statusRisk(status);
              const hasDate = !!g.target_date;
              let daysText: string | null = null;
              let daysTone: "default" | "warning" | "danger" = "default";
              if (hasDate) {
                const d = new Date(String(g.target_date));
                if (!isNaN(d.getTime())) {
                  const days = daysBetween(new Date(), d);
                  if (days < 0) {
                    daysText = t("home.overdue", { n: Math.abs(days) });
                    daysTone = "danger";
                  } else if (days <= 30) {
                    daysText = t("home.dueIn", { n: days });
                    daysTone = days <= 7 ? "warning" : "default";
                  } else {
                    daysText = t("home.dueIn", { n: days });
                  }
                }
              }

              return (
                <Link key={g.id} href={`/goals/${g.id}`} className="block group">
                  <Card className="hover:border-brand-500/40 transition-colors h-full">
                    <CardHeader>
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="truncate text-zinc-900 dark:text-zinc-100">
                          {g.title}
                        </CardTitle>
                        {status && (
                          <Badge variant="risk" riskLevel={risk} className="shrink-0">
                            {statusLabel(status)}
                          </Badge>
                        )}
                      </div>
                      <CardDescription className="mt-1 flex items-center gap-3 flex-wrap">
                        <span className="inline-flex items-center gap-1">
                          <Tag className="h-3 w-3" />
                          {scenarioLabel(g.scenario)}
                        </span>
                        {hasDate && (
                          <span className="inline-flex items-center gap-1">
                            <Calendar className="h-3 w-3" />
                            {g.target_date}
                          </span>
                        )}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {g.description ? (
                        <p className="text-xs text-zinc-600 dark:text-zinc-400 line-clamp-2 min-h-[2rem]">
                          {g.description}
                        </p>
                      ) : (
                        <p className="text-xs text-zinc-400 dark:text-zinc-600 italic min-h-[2rem]">
                          {t("home.noDate")}
                        </p>
                      )}

                      {/* Due-date chip — color-coded by urgency. */}
                      {hasDate && daysText ? (
                        <div
                          className={
                            "inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border " +
                            (daysTone === "danger"
                              ? "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/20"
                              : daysTone === "warning"
                              ? "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20"
                              : "text-zinc-500 dark:text-zinc-400 bg-black/[0.03] dark:bg-white/[0.03] border-black/5 dark:border-white/5")
                          }
                        >
                          <Clock className="h-3 w-3" />
                          {daysText}
                        </div>
                      ) : !hasDate ? (
                        <div className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border text-zinc-500 dark:text-zinc-500 bg-black/[0.03] dark:bg-white/[0.03] border-black/5 dark:border-white/5">
                          <Calendar className="h-3 w-3" />
                          {t("home.noDate")}
                        </div>
                      ) : null}

                      <div className="flex items-center justify-between text-[10px] text-zinc-500 dark:text-zinc-500 pt-1 border-t border-black/5 dark:border-white/5">
                        <span>
                          {t("home.createdAt")} {formatDate(g.created_at)}
                        </span>
                        <span className="inline-flex items-center gap-1 text-brand-600 dark:text-brand-400 group-hover:translate-x-0.5 transition-transform">
                          {t("home.updatedAt")} {formatDate(g.updated_at)}
                          <ArrowRight className="h-3 w-3 ml-0.5" />
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {/* Empty state — 3-step onboarding card so first-time users know
          exactly what to do instead of staring at a blank page with a
          single CTA. Each step links to the relevant page. */}
      {!isLoading && allGoals.length === 0 && (
        <Card>
          <CardContent className="py-10 space-y-6">
            <div className="text-center space-y-2">
              <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center">
                <Compass className="h-6 w-6 text-brand-600 dark:text-brand-400" />
              </div>
              <div className="text-sm text-zinc-700 dark:text-zinc-300">{t("home.noGoals")}</div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-sm mx-auto">
                {t("home.noGoalsHint")}
              </p>
            </div>
            {/* Onboarding steps — 3 cards linking to the key first-time
                actions. Uses a grid so it stacks on mobile. */}
            <div className="space-y-2">
              <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold px-1">
                {t("home.onboarding.steps.title")}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <Link href="/profile" className="block group">
                  <div className="rounded-md border border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] p-3 hover:border-brand-500/30 hover:bg-brand-500/[0.03] transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <div className="h-7 w-7 rounded-md bg-brand-500/10 flex items-center justify-center">
                        <User className="h-3.5 w-3.5 text-brand-600 dark:text-brand-400" />
                      </div>
                      <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
                        {t("home.onboarding.step1.title")}
                      </span>
                    </div>
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
                      {t("home.onboarding.step1.desc")}
                    </p>
                  </div>
                </Link>
                <Link href="/goals" className="block group">
                  <div className="rounded-md border border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] p-3 hover:border-brand-500/30 hover:bg-brand-500/[0.03] transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <div className="h-7 w-7 rounded-md bg-brand-500/10 flex items-center justify-center">
                        <Compass className="h-3.5 w-3.5 text-brand-600 dark:text-brand-400" />
                      </div>
                      <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
                        {t("home.onboarding.step2.title")}
                      </span>
                    </div>
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
                      {t("home.onboarding.step2.desc")}
                    </p>
                  </div>
                </Link>
                <Link href="/ingest" className="block group">
                  <div className="rounded-md border border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] p-3 hover:border-brand-500/30 hover:bg-brand-500/[0.03] transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <div className="h-7 w-7 rounded-md bg-brand-500/10 flex items-center justify-center">
                        <Upload className="h-3.5 w-3.5 text-brand-600 dark:text-brand-400" />
                      </div>
                      <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
                        {t("home.onboarding.step3.title")}
                      </span>
                    </div>
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
                      {t("home.onboarding.step3.desc")}
                    </p>
                  </div>
                </Link>
              </div>
            </div>
            <div className="text-center">
              <Button asChild>
                <Link href="/goals">
                  <Compass className="h-4 w-4 mr-1.5" /> {t("home.createFirst")}
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
