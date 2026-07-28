"use client";

import { useState } from "react";
import { useSources, useCredibility } from "@/lib/hooks";
import { CredibilityMeter } from "@/components/dashboard/credibility-meter";
import { LifecyclePanel } from "@/components/sources/lifecycle-panel";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn, formatDate } from "@/lib/utils";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { Loader2, ThumbsUp, ThumbsDown, Upload, Trash2, Clock } from "lucide-react";
import Link from "next/link";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { SourceScheduleDialog } from "@/components/sources/source-schedule-dialog";

// Credibility enum values returned by the backend. Rendered via i18n
// so users see localized labels instead of snake_case identifiers.
const CREDIBILITY_KEYS = [
  "high",
  "medium",
  "low",
  "pending",
  "user_marked_reliable",
  "user_marked_questionable",
  "unknown",
] as const;

// Sources in these states are considered "reviewed" — the user has
// either explicitly marked them or the system has auto-classified them.
const REVIEWED_STATES = new Set([
  "high",
  "medium",
  "low",
  "user_marked_reliable",
  "user_marked_questionable",
]);

type CredibilityFilter = "all" | "pending" | "reviewed";

function credibilityLabel(t: (k: string) => string, value: string): string {
  if ((CREDIBILITY_KEYS as readonly string[]).includes(value)) {
    const label = t(`sources.credibility.${value}`);
    // Fall back to the raw value if the key is missing (defensive — should
    // never happen since we add keys for all known values below).
    return label === `sources.credibility.${value}` ? value : label;
  }
  return value;
}

export default function SourcesPage() {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data: sources, mutate, isLoading } = useSources();
  const { data: credibility, mutate: mutateCred } = useCredibility();

  // Track which source is currently being marked so we can disable its
  // buttons and show a spinner. Keyed by source id.
  const [markingId, setMarkingId] = useState<string | null>(null);
  // Track which source is being deleted (separate state so marking and
  // deleting can't collide on the same row).
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Credibility filter for the source list.
  const [credFilter, setCredFilter] = useState<CredibilityFilter>("all");
  // Source whose schedule dialog is open (null = closed).
  const [scheduleSource, setScheduleSource] = useState<any | null>(null);

  const allSources = (sources as any[]) ?? [];
  const pendingSources = allSources.filter(
    (s) => !REVIEWED_STATES.has(s.credibility)
  );
  const reviewedCount = allSources.length - pendingSources.length;

  const visibleSources =
    credFilter === "pending"
      ? pendingSources
      : credFilter === "reviewed"
        ? allSources.filter((s) => REVIEWED_STATES.has(s.credibility))
        : allSources;

  async function handleMark(id: string, level: string) {
    if (markingId) return; // prevent concurrent marks
    setMarkingId(id);
    try {
      await api.markCredibility(id, level);
      await Promise.all([mutate(), mutateCred()]);
      toast({
        title:
          level === "user_marked_reliable"
            ? t("sources.toast.markedReliable")
            : t("sources.toast.markedQuestionable"),
        variant: "success",
      });
    } catch (err: any) {
      toast({
        title: t("sources.toast.markFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setMarkingId(null);
    }
  }

  async function handleDelete(id: string, title: string) {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("sources.deleteConfirm", { title }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setDeletingId(id);
    try {
      await api.deleteSource(id);
      await Promise.all([mutate(), mutateCred()]);
      toast({
        title: t("sources.toast.deleted"),
        description: title,
        variant: "success",
      });
    } catch (err: any) {
      toast({
        title: t("sources.toast.deleteFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
          <SidebarToggleButton />
          {t("sources.title")}
        </h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">{t("sources.subtitle")}</p>
      </header>

      <CredibilityMeter credibility={credibility} />

      <LifecyclePanel />

      {/* Review Queue — highlights pending sources needing review.
          Shows a progress indicator and quick mark buttons so the user
          can cycle through the queue without scrolling the full list. */}
      {!isLoading && pendingSources.length > 0 && (
        <Card className="border-amber-500/30 bg-amber-500/[0.03]">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <span className="inline-block h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                  {t("sources.review.title")}
                </CardTitle>
                <CardDescription>{t("sources.review.subtitle")}</CardDescription>
              </div>
              <div className="text-right shrink-0">
                <div className="text-xs text-zinc-500 dark:text-zinc-400">
                  {t("sources.review.progress", {
                    reviewed: reviewedCount,
                    total: allSources.length,
                  })}
                </div>
                <div className="mt-1 h-1.5 w-24 rounded-full bg-black/5 dark:bg-white/5 overflow-hidden">
                  <div
                    className="h-full bg-brand-500 transition-all"
                    style={{
                      width: `${allSources.length ? (reviewedCount / allSources.length) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {pendingSources.map((s) => (
                <div
                  key={s.id}
                  className="grid grid-cols-[1fr_auto_auto] gap-3 items-center py-2 border-b border-amber-500/10 last:border-0"
                >
                  <div className="min-w-0">
                    <div className="text-sm text-zinc-800 dark:text-zinc-200 truncate">{s.title}</div>
                    <div className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {t(`kind.${s.kind}`)} · {s.publisher ?? "—"} · {formatDate(s.published_at)}
                    </div>
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noopener noreferrer"
                        className="text-[10px] text-brand-600 dark:text-brand-400 hover:underline">
                        {s.url}
                      </a>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-emerald-500/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/10"
                    onClick={() => handleMark(s.id, "user_marked_reliable")}
                    disabled={markingId === s.id}
                  >
                    {markingId === s.id ? (
                      <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                    ) : (
                      <ThumbsUp className="h-3 w-3 mr-1" />
                    )}
                    {t("sources.mark.reliable")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-600 dark:text-red-300 hover:bg-red-500/10"
                    onClick={() => handleMark(s.id, "user_marked_questionable")}
                    disabled={markingId === s.id}
                  >
                    <ThumbsDown className="h-3 w-3 mr-1" />
                    {t("sources.mark.questionable")}
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
      {!isLoading && pendingSources.length === 0 && allSources.length > 0 && (
        <div className="rounded-md border border-emerald-500/20 bg-emerald-500/[0.04] px-4 py-3 text-xs text-emerald-700 dark:text-emerald-300">
          {t("sources.review.empty")}
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <div>
              <CardTitle>{t("sources.list.title")}</CardTitle>
              <CardDescription>{t("sources.list.subtitle")}</CardDescription>
            </div>
            {/* Credibility filter — lets the user focus on pending or
                reviewed sources in the full list below the queue. */}
            <div className="flex gap-1 text-[11px]">
              {(["all", "pending", "reviewed"] as CredibilityFilter[]).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setCredFilter(f)}
                  className={
                    "px-2.5 py-1 rounded-md border transition-colors " +
                    (credFilter === f
                      ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-300"
                      : "border-black/5 dark:border-white/5 text-zinc-500 dark:text-zinc-400 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]")
                  }
                >
                  {t(`sources.filter.${f}`)}
                  {f === "pending" && pendingSources.length > 0 && (
                    <span className="ml-1 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-amber-500 text-white text-[9px] font-medium">
                      {pendingSources.length}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {isLoading ? (
              <div className="space-y-3">
                {[0, 1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="grid grid-cols-[1fr_auto_auto_auto] gap-3 items-start py-3 border-b border-black/5 dark:border-white/5 last:border-0"
                  >
                    <div className="min-w-0 space-y-1.5">
                      <Skeleton className="h-3.5 w-2/3" />
                      <Skeleton className="h-2.5 w-1/2" />
                      <Skeleton className="h-2.5 w-1/3" />
                    </div>
                    <Skeleton className="h-5 w-14 rounded-full" />
                    <Skeleton className="h-6 w-6 rounded" />
                    <Skeleton className="h-6 w-6 rounded" />
                  </div>
                ))}
              </div>
            ) : (
              visibleSources.map((s) => (
                <div key={s.id} className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-3 items-start py-3 border-b border-black/5 dark:border-white/5 last:border-0">
                  <div className="min-w-0">
                    <div className="text-sm text-zinc-800 dark:text-zinc-200 truncate">{s.title}</div>
                    <div className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {t(`kind.${s.kind}`)} · {s.publisher ?? "—"} · {formatDate(s.published_at)}
                    </div>
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noopener noreferrer"
                        className="text-[10px] text-brand-600 dark:text-brand-400 hover:underline">
                        {s.url}
                      </a>
                    )}
                    {s.auto_refresh && (
                      <span className="inline-flex items-center gap-0.5 mt-0.5 text-[9px] text-brand-600 dark:text-brand-400">
                        <Clock className="h-2.5 w-2.5" />
                        {t("sources.schedule.autoRefreshOn")}
                        {s.refresh_interval_minutes >= 1440
                          ? ` ${Math.round(s.refresh_interval_minutes / 1440)}d`
                          : s.refresh_interval_minutes >= 60
                            ? ` ${Math.round(s.refresh_interval_minutes / 60)}h`
                            : ` ${s.refresh_interval_minutes}m`}
                      </span>
                    )}
                  </div>
                  <Badge variant="risk" riskLevel={
                    s.credibility === "high" || s.credibility === "user_marked_reliable" ? "low"
                    : s.credibility === "low" || s.credibility === "user_marked_questionable" ? "high"
                    : "medium"
                  }>
                    {credibilityLabel(t, s.credibility)}
                  </Badge>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleMark(s.id, "user_marked_reliable")}
                      disabled={markingId === s.id || deletingId === s.id}
                    >
                      {markingId === s.id ? (
                        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                      ) : (
                        <ThumbsUp className="h-3 w-3 mr-1" />
                      )}
                      {t("sources.mark.reliable")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleMark(s.id, "user_marked_questionable")}
                      disabled={markingId === s.id || deletingId === s.id}
                    >
                      <ThumbsDown className="h-3 w-3 mr-1" />
                      {t("sources.mark.questionable")}
                    </Button>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className={cn(
                      "h-7 w-7 p-0",
                      s.auto_refresh
                        ? "text-brand-600 dark:text-brand-400"
                        : "text-zinc-500 hover:text-brand-600 dark:hover:text-brand-300"
                    )}
                    onClick={() => setScheduleSource(s)}
                    title={t("sources.schedule.title")}
                  >
                    <Clock className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 w-7 p-0 text-zinc-500 hover:text-red-600 dark:hover:text-red-300"
                    onClick={() => handleDelete(s.id, s.title)}
                    disabled={markingId === s.id || deletingId === s.id}
                    title={t("sources.delete")}
                  >
                    {deletingId === s.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </div>
              ))
            )}
            {!isLoading && visibleSources.length === 0 && (
              <div className="text-center py-8 space-y-2">
                <div className="text-sm text-zinc-500 dark:text-zinc-400">{t("sources.empty")}</div>
                <div className="text-xs text-zinc-500 dark:text-zinc-400">{t("sources.emptyHint")}</div>
                <Link
                  href="/ingest"
                  className="inline-flex items-center gap-1.5 text-xs text-brand-600 dark:text-brand-400 hover:underline pt-1"
                >
                  <Upload className="h-3.5 w-3.5" />
                  {t("sources.goIngest")}
                </Link>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
      {ConfirmRoot}
      <SourceScheduleDialog
        sourceId={scheduleSource?.id}
        sourceTitle={scheduleSource?.title}
        sourceUrl={scheduleSource?.url}
        open={!!scheduleSource}
        onOpenChange={(open) => !open && setScheduleSource(null)}
        onUpdated={() => mutate()}
      />
    </div>
  );
}
