"use client";

/**
 * Information half-life (decay) panel.
 *
 * Visualizes the decay status of all events and lets the user:
 *   - See the fresh/stale/expired/archived distribution at a glance
 *   - Filter the event list by decay status
 *   - Refresh an event (resets its decay clock)
 *   - Archive an event (excludes it from active reasoning)
 *   - Override the half-life per event
 *   - Manually trigger the auto-archive sweep
 *
 * Implements §4.8 of the project plan: knowledge half-life management.
 */

import { useState } from "react";
import {
  RefreshCw,
  Archive,
  Clock,
  Sparkles,
  AlertTriangle,
  Archive as ArchiveIcon,
  Wand2,
  Loader2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn, formatDate, formatPercent } from "@/lib/utils";
import { api, type DecayStatus, type LifecycleEvent } from "@/lib/api";
import {
  useDecayDistribution,
  useLifecycleEvents,
} from "@/lib/hooks";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

const STATUS_ORDER: DecayStatus[] = ["fresh", "stale", "expired", "archived"];

const STATUS_COLORS: Record<string, string> = {
  fresh: "bg-emerald-500",
  stale: "bg-amber-500",
  expired: "bg-red-500",
  archived: "bg-zinc-600",
};

const STATUS_ICON: Record<string, React.ElementType> = {
  fresh: Sparkles,
  stale: Clock,
  expired: AlertTriangle,
  archived: ArchiveIcon,
};

export function LifecyclePanel() {
  const t = useT();
  const toast = useToast();
  const { data: dist, mutate: mutateDist } = useDecayDistribution();
  const [filter, setFilter] = useState<DecayStatus | "all">("all");
  const { data: events, mutate: mutateEvents, isValidating } = useLifecycleEvents(
    filter === "all" ? undefined : filter
  );

  const distribution = dist ?? {
    total: 0,
    fresh: 0,
    stale: 0,
    expired: 0,
    archived: 0,
    avg_score: 0,
  };

  const total = distribution.total || 1;

  async function handleRefresh(eventId: string) {
    try {
      await api.refreshLifecycleEvent(eventId);
      await Promise.all([mutateEvents(), mutateDist()]);
      toast({ title: t("lifecycle.refreshed"), variant: "success" });
    } catch (err) {
      toast({
        title: t("error.generic", { msg: (err as Error).message }),
        variant: "error",
      });
    }
  }

  async function handleArchive(eventId: string) {
    try {
      await api.archiveLifecycleEvent(eventId);
      await Promise.all([mutateEvents(), mutateDist()]);
      toast({ title: t("lifecycle.archived"), variant: "success" });
    } catch (err) {
      toast({
        title: t("error.generic", { msg: (err as Error).message }),
        variant: "error",
      });
    }
  }

  async function handleSweep() {
    try {
      const result = await api.sweepExpiredEvents();
      await Promise.all([mutateEvents(), mutateDist()]);
      toast({
        title: t("lifecycle.sweepDone", { count: result.archived }),
        variant: "success",
      });
    } catch (err) {
      toast({
        title: t("error.generic", { msg: (err as Error).message }),
        variant: "error",
      });
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle>{t("lifecycle.title")}</CardTitle>
            <CardDescription>{t("lifecycle.subtitle")}</CardDescription>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={handleSweep}
            disabled={isValidating}
            title={t("lifecycle.sweepHint")}
          >
            <Wand2 className="h-3.5 w-3.5 mr-1" />
            {t("lifecycle.sweep")}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Distribution bars */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs text-zinc-600 dark:text-zinc-400">
            <span>{t("lifecycle.avgScore")}</span>
            <span className="text-zinc-800 dark:text-zinc-200 font-medium">
              {formatPercent(distribution.avg_score)}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-black/5 dark:bg-white/5 overflow-hidden flex">
            {STATUS_ORDER.map((s) => {
              const v = (distribution as any)[s] as number;
              const pct = (v / total) * 100;
              if (pct === 0) return null;
              return (
                <div
                  key={s}
                  className={cn("h-full", STATUS_COLORS[s])}
                  style={{ width: `${pct}%` }}
                  title={`${t(`lifecycle.status.${s}`)}: ${v}`}
                />
              );
            })}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2">
            {STATUS_ORDER.map((s) => {
              const Icon = STATUS_ICON[s];
              const v = (distribution as any)[s] as number;
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => setFilter((cur) => (cur === s ? "all" : s))}
                  className={cn(
                    "flex flex-col items-start gap-0.5 rounded-md border px-2.5 py-2 text-left transition-colors",
                    filter === s
                      ? "border-brand-500/40 bg-brand-500/10"
                      : "border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] hover:bg-black/[0.04] dark:hover:bg-white/[0.04]"
                  )}
                >
                  <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    <Icon className="h-3 w-3" />
                    {t(`lifecycle.status.${s}`)}
                  </div>
                  <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">{v}</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Event list */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
            <span>
              {t("lifecycle.listTitle")}
              {filter !== "all" && (
                <>
                  {" · "}
                  <button
                    type="button"
                    onClick={() => setFilter("all")}
                    className="text-brand-600 dark:text-brand-300 hover:underline"
                  >
                    {t("lifecycle.clearFilter")}
                  </button>
                </>
              )}
            </span>
            {isValidating && (
              <Loader2 className="h-3 w-3 animate-spin" />
            )}
          </div>

          {(events ?? []).length === 0 ? (
            <div className="text-xs text-zinc-500 dark:text-zinc-400 text-center py-4">
              {t("lifecycle.empty")}
            </div>
          ) : (
            (events ?? []).map((row: LifecycleEvent) => (
              <LifecycleEventRow
                key={row.event.id}
                row={row}
                onRefresh={handleRefresh}
                onArchive={handleArchive}
              />
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function LifecycleEventRow({
  row,
  onRefresh,
  onArchive,
}: {
  row: LifecycleEvent;
  onRefresh: (id: string) => void;
  onArchive: (id: string) => void;
}) {
  const t = useT();
  const { event, decay } = row;
  const status = decay.status as DecayStatus;
  const Icon = STATUS_ICON[status] ?? Clock;
  const scorePct = Math.max(0, Math.min(1, decay.score)) * 100;

  const ev = event as any;
  const title =
    ev.subject || ev.title || event.id.slice(0, 8);
  const subtitle = [ev.action, ev.object].filter(Boolean).join(" · ");

  return (
    <div className="rounded-md border border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] px-3 py-2 hover:bg-black/[0.04] dark:hover:bg-white/[0.04] transition-colors">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-zinc-800 dark:text-zinc-200 truncate">{title}</span>
            <StatusBadge status={status} label={t(`lifecycle.status.${status}`)} />
          </div>
          {subtitle && (
            <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5 truncate">
              {subtitle}
            </div>
          )}
          <div className="flex items-center gap-3 mt-1 text-[10px] text-zinc-500 dark:text-zinc-400">
            <span>
              {t("lifecycle.age")}: {Math.round(decay.age_days)}d
            </span>
            <span>
              {t("lifecycle.halfLife")}: {decay.half_life_days}d
            </span>
            {decay.last_refreshed_at && (
              <span>
                {t("lifecycle.refreshedAt")}: {formatDate(decay.last_refreshed_at)}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11px]"
            onClick={() => onRefresh(event.id)}
            title={t("lifecycle.refreshHint")}
          >
            <RefreshCw className="h-3 w-3" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11px] hover:text-red-600 dark:hover:text-red-300 hover:bg-red-500/10"
            onClick={() => onArchive(event.id)}
            title={t("lifecycle.archiveHint")}
            disabled={status === "archived"}
          >
            <Archive className="h-3 w-3" />
          </Button>
        </div>
      </div>
      {/* Score bar */}
      <div className="mt-2 flex items-center gap-2">
        <div className="flex-1 h-1 rounded-full bg-black/5 dark:bg-white/5 overflow-hidden">
          <div
            className={cn("h-full", STATUS_COLORS[status])}
            style={{ width: `${scorePct}%` }}
          />
        </div>
        <span className="text-[10px] text-zinc-500 dark:text-zinc-400 font-mono w-9 text-right">
          {Math.round(scorePct)}%
        </span>
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  label,
}: {
  status: DecayStatus;
  label: string;
}) {
  const cls: Record<DecayStatus, string> = {
    fresh: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
    stale: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
    expired: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30",
    archived: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 border-zinc-500/30",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium",
        cls[status]
      )}
    >
      {label}
    </span>
  );
}
