"use client";

/**
 * ChangesSummaryBanner — small "since last visit" digest shown at the top
 * of the dashboard. Renders counts ("3 条新事件、2 个新信源、1 个新行动")
 * plus, when present, a short list of recent high-risk events.
 *
 * The widget is intentionally minimal: it surfaces what changed, not the
 * full content of each change — clicking "查看详情" sends the user to the
 * relevant list pages. Errors are caught by the surrounding ErrorBoundary
 * so a failing summary never breaks the dashboard below it.
 */

import Link from "next/link";
import { AlertCircle, ArrowRight, Bell } from "lucide-react";
import { useChangesSummary } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";

interface CountItem {
  key: string;
  value: number;
}

export function ChangesSummaryBanner() {
  const t = useT();
  const { data, isLoading, error } = useChangesSummary();

  if (isLoading) {
    return (
      <div className="surface p-4">
        <div className="flex items-center gap-2 mb-3">
          <Bell className="h-4 w-4 text-brand-400" />
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-3.5 w-24" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    // Surface a small, non-blocking error chip — the surrounding
    // ErrorBoundary handles render-level failures, but a 4xx/5xx from
    // the API should just degrade gracefully without hiding the rest
    // of the dashboard.
    return (
      <div className="surface p-4 flex items-center gap-2 text-xs text-zinc-400">
        <AlertCircle className="h-4 w-4 text-amber-400 shrink-0" />
        <span>{t("changes.errorTitle")}</span>
      </div>
    );
  }

  if (!data) return null;

  const items: CountItem[] = [
    { key: "changes.newEvents", value: data.new_events },
    { key: "changes.newSources", value: data.new_sources },
    { key: "changes.newGoals", value: data.new_goals },
    { key: "changes.newActions", value: data.new_actions },
    { key: "changes.completedActions", value: data.completed_actions },
    { key: "changes.newRiskFactors", value: data.new_risk_factors },
    { key: "changes.updatedScenarios", value: data.updated_scenarios },
    { key: "changes.newSourceProposals", value: data.new_source_proposals },
  ];

  const nonZero = items.filter((i) => i.value > 0);
  const highRisk = data.recent_high_risk_events ?? [];
  const lastVisit = data.last_visit_at;

  const subtitle = lastVisit
    ? t("changes.lastVisit", { time: formatDate(lastVisit) })
    : t("changes.sinceFallback");

  if (nonZero.length === 0 && highRisk.length === 0) {
    return (
      <div className="surface p-4 flex items-center gap-2 text-xs text-zinc-400">
        <Bell className="h-4 w-4 text-zinc-500 shrink-0" />
        <span className="text-zinc-300">{t("changes.title")}</span>
        <span className="text-zinc-500">·</span>
        <span>{t("changes.empty")}</span>
      </div>
    );
  }

  return (
    <div className="surface p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <Bell className="h-4 w-4 text-brand-400 shrink-0" />
          <span className="text-sm font-semibold text-zinc-100 truncate">
            {t("changes.title")}
          </span>
          <span className="text-[11px] text-zinc-500 truncate">
            {subtitle}
          </span>
        </div>
        <Link
          href="/notifications"
          className="text-[11px] text-brand-400 hover:text-brand-300 inline-flex items-center gap-1 shrink-0"
        >
          {t("changes.viewDetails")}
          <ArrowRight className="h-3 w-3" />
        </Link>
      </div>

      {nonZero.length > 0 && (
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1.5 text-xs text-zinc-300">
          {nonZero.map((item) => (
            <span key={item.key} className="inline-flex items-baseline gap-1">
              <span className="text-sm font-semibold text-zinc-100">
                {item.value}
              </span>
              <span className="text-zinc-400">
                {t(item.key, { n: item.value })}
              </span>
            </span>
          ))}
        </div>
      )}

      {highRisk.length > 0 && (
        <div className="space-y-1 pt-2 border-t border-white/5">
          <div className="text-[10px] uppercase tracking-wide text-zinc-500">
            {t("changes.highRiskEvents")}
          </div>
          <ul className="space-y-1">
            {highRisk.slice(0, 5).map((ev, idx) => (
              <li
                key={`${ev.subject}-${ev.action}-${idx}`}
                className="flex items-start gap-2 text-xs text-zinc-300"
              >
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-red-400 shrink-0 mt-1.5" />
                <span className="min-w-0">
                  <span className="font-medium text-zinc-100 break-words">
                    {ev.subject}
                  </span>
                  <span className="text-zinc-400">
                    {" "}
                    {ev.action}
                  </span>
                  {ev.occurred_at && (
                    <span className="text-zinc-500 ml-1">
                      · {formatDate(ev.occurred_at)}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// Re-export so callers that want the raw API types can import from one place.
export type { CountItem };
