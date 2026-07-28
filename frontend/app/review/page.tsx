"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePendingReview } from "@/lib/hooks";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { useToast } from "@/components/ui/toast";
import { api, type EventRead } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { cn, formatDate } from "@/lib/utils";
import {
  useConfirm,
} from "@/components/ui/confirm-dialog";
import {
  Inbox,
  Loader2,
  Check,
  Archive,
  Anchor,
  AlertTriangle,
  ExternalLink,
  GitBranch,
  Layers,
  Filter,
  Keyboard,
} from "lucide-react";

/**
 * §4.9 Review Inbox — 待审核信源事件收件箱.
 *
 * Lists events with status='pending_review' (low-confidence + high-impact
 * extractions) and lets the user triage each one with three actions:
 *   采纳 (approve)    — event joins the active graph
 *   忽略 (sink)       — event is excluded from reasoning
 *   保持沉降 (keep)   — confirms sunk state (audit ack)
 *
 * Per project plan §4.9: this is the human-in-the-loop gate that keeps
 * noisy LLM extractions from polluting the knowledge graph while still
 * letting high-impact signals surface for review.
 *
 * UX principles applied:
 * - Semantic theme tokens (no hard-coded dark colors) so light/dark both work
 * - Filter tabs by impact level so users can focus on what matters
 * - Batch actions (approve all / sink all) with confirmation for efficiency
 * - Approve confirmation dialog explains side effects (branch spawn, risk propagation)
 * - Keyboard shortcuts (A/S/K) for power users
 * - Helper text under each button clarifies what it does
 * - Empty state CTA guides users to scenario comparison page
 */

type RiskFilter = "all" | "high" | "medium" | "low";
type Action = "approve" | "sink" | "keep_sunk";

export default function ReviewInboxPage() {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data, mutate, isLoading } = usePendingReview();
  const [actingId, setActingId] = useState<string | null>(null);
  const [filter, setFilter] = useState<RiskFilter>("all");
  const [batchRunning, setBatchRunning] = useState(false);

  const items = (data as EventRead[] | undefined) ?? [];

  // Filter by risk level — "all" shows everything.
  const filteredItems = useMemo(() => {
    if (filter === "all") return items;
    return items.filter((ev) => {
      const level = (ev.risk_flag_level as string | null) ?? "low";
      return level === filter;
    });
  }, [items, filter]);

  // Counts per risk level for the filter tabs.
  const counts = useMemo(() => {
    const c = { all: items.length, high: 0, medium: 0, low: 0 };
    for (const ev of items) {
      const level = (ev.risk_flag_level as string | null) ?? "low";
      if (level === "high" || level === "medium" || level === "low") {
        c[level]++;
      }
    }
    return c;
  }, [items]);

  const pendingCount = items.length;

  /**
   * Single-event action handler. Approve goes through a confirmation
   * dialog first to make sure the user understands the side effects
   * (risk propagation, branch spawn, notifications).
   */
  const handleAction = useCallback(
    async (eventId: string, action: Action) => {
      if (actingId) return;

      // Approve triggers significant side effects — confirm first.
      if (action === "approve") {
        const ok = await confirm({
          title: t("review.approveConfirm.title"),
          description: t("review.approveConfirm.body"),
          confirmLabel: t("review.approve"),
          cancelLabel: t("common.cancel"),
          variant: "default",
        });
        if (!ok) return;
      }

      setActingId(eventId);
      try {
        await api.updateEventStatus(eventId, action);
        await mutate();
        const toastKey =
          action === "approve" ? "review.toast.approveWithBranch" : `review.toast.${action}`;
        toast({
          title: t(toastKey),
          variant: "success",
          ...(action === "approve" && {
            description: t("review.emptyBranchesHint"),
          }),
        });
      } catch (err: any) {
        toast({
          title: t("review.toast.failed"),
          description: err?.message,
          variant: "error",
        });
      } finally {
        setActingId(null);
      }
    },
    [actingId, confirm, t, toast, mutate]
  );

  /**
   * Batch action — applies the same action to all filtered items.
   * Uses sequential calls (not Promise.all) to avoid overwhelming the
   * backend with concurrent risk-propagation runs.
   */
  const handleBatch = useCallback(
    async (action: Action) => {
      if (batchRunning || filteredItems.length === 0) return;

      const confirmKey =
        action === "approve" ? "review.batch.approveConfirm" : "review.batch.sinkConfirm";
      const ok = await confirm({
        title: t("review.batch.title"),
        description: t(confirmKey, { n: filteredItems.length }),
        confirmLabel:
          action === "approve" ? t("review.batch.approveAll") : t("review.batch.sinkAll"),
        cancelLabel: t("common.cancel"),
        variant: action === "approve" ? "default" : "danger",
      });
      if (!ok) return;

      setBatchRunning(true);
      let success = 0;
      let fail = 0;
      for (const ev of filteredItems) {
        try {
          await api.updateEventStatus(ev.id, action);
          success++;
        } catch {
          fail++;
        }
      }
      await mutate();
      setBatchRunning(false);
      toast({
        title: t("review.batch.done", { success, fail }),
        variant: fail > 0 ? "warning" : "success",
        ...(action === "approve" && success > 0 && {
          description: t("review.emptyBranchesHint"),
        }),
      });
    },
    [batchRunning, filteredItems, confirm, t, toast, mutate]
  );

  // Keyboard shortcuts: A=approve, S=sink, K=keep_sunk on the first visible item.
  useEffect(() => {
    if (filteredItems.length === 0 || actingId || batchRunning) return;
    const handler = (e: KeyboardEvent) => {
      // Ignore when typing in inputs / dialogs.
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable ||
        target.closest("[role=dialog]")
      ) {
        return;
      }
      const key = e.key.toLowerCase();
      if (key === "a" || key === "s" || key === "k") {
        e.preventDefault();
        const action: Action = key === "a" ? "approve" : key === "s" ? "sink" : "keep_sunk";
        handleAction(filteredItems[0].id, action);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [filteredItems, actingId, batchRunning, handleAction]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      {ConfirmRoot}

      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
            <SidebarToggleButton />
            <Inbox className="h-6 w-6 text-brand-500" />
            {t("review.title")}
          </h1>
          <p className="text-sm text-muted mt-1">{t("review.subtitle")}</p>
        </div>
        <Badge variant="risk" riskLevel={pendingCount > 0 ? "high" : "low"}>
          {t("review.queueCount", { n: pendingCount })}
        </Badge>
      </header>

      {/* Filter tabs + batch actions */}
      {pendingCount > 0 && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1 p-1 rounded-lg bg-surface-2/60 border border-border/10">
            <Filter className="h-3.5 w-3.5 text-muted mx-1.5" />
            <FilterTab
              active={filter === "all"}
              onClick={() => setFilter("all")}
              label={t("review.filter.all")}
              count={counts.all}
            />
            <FilterTab
              active={filter === "high"}
              onClick={() => setFilter("high")}
              label={t("review.filter.high")}
              count={counts.high}
            />
            <FilterTab
              active={filter === "medium"}
              onClick={() => setFilter("medium")}
              label={t("review.filter.medium")}
              count={counts.medium}
            />
            <FilterTab
              active={filter === "low"}
              onClick={() => setFilter("low")}
              label={t("review.filter.low")}
              count={counts.low}
            />
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleBatch("sink")}
              disabled={batchRunning || filteredItems.length === 0}
              className="gap-1.5"
            >
              {batchRunning ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Layers className="h-3.5 w-3.5" />
              )}
              {t("review.batch.sinkAll")}
            </Button>
            <Button
              size="sm"
              variant="default"
              onClick={() => handleBatch("approve")}
              disabled={batchRunning || filteredItems.length === 0}
              className="gap-1.5"
            >
              {batchRunning ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              {t("review.batch.approveAll")}
            </Button>
          </div>
        </div>
      )}

      {isLoading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted flex items-center justify-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("review.loading")}
          </CardContent>
        </Card>
      ) : items.length === 0 ? (
        <EmptyReviewState />
      ) : filteredItems.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted">
            {t("review.noFiltered")}
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Keyboard shortcut hint — only shows when there are items */}
          <div className="flex items-center gap-1.5 text-[11px] text-muted">
            <Keyboard className="h-3 w-3" />
            <span>{t("review.shortcut.hint")}</span>
          </div>
          <div className="space-y-3">
            {filteredItems.map((ev, idx) => (
              <ReviewCard
                key={ev.id}
                event={ev}
                acting={actingId === ev.id}
                onAction={(a) => handleAction(ev.id, a)}
                highlight={idx === 0 && !actingId && !batchRunning}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Filter tab pill with count badge. */
function FilterTab({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-surface text-foreground shadow-sm"
          : "text-muted hover:text-foreground hover:bg-surface/60"
      )}
    >
      {label}
      <span
        className={cn(
          "tabular-nums rounded-full px-1.5 py-0.5 text-[10px]",
          active ? "bg-brand-500/15 text-brand-600 dark:text-brand-400" : "bg-border/10 text-muted"
        )}
      >
        {count}
      </span>
    </button>
  );
}

function EmptyReviewState() {
  const t = useT();
  return (
    <Card>
      <CardContent className="py-12 text-center space-y-3">
        <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center">
          <Check className="h-6 w-6 text-brand-500" />
        </div>
        <div className="text-sm text-foreground">{t("review.empty")}</div>
        <p className="text-xs text-muted">{t("review.emptyHint")}</p>
        <div className="flex items-center justify-center gap-2 pt-2">
          <Button asChild variant="outline" size="sm">
            <Link href="/ingest">
              <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
              {t("review.goIngest")}
            </Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link href="/scenarios">
              <GitBranch className="h-3.5 w-3.5 mr-1.5" />
              {t("review.viewBranches")}
            </Link>
          </Button>
        </div>
        <p className="text-[11px] text-muted/70 pt-1">{t("review.emptyBranchesHint")}</p>
      </CardContent>
    </Card>
  );
}

function ReviewCard({
  event,
  acting,
  onAction,
  highlight,
}: {
  event: EventRead;
  acting: boolean;
  onAction: (action: Action) => void;
  highlight?: boolean;
}) {
  const t = useT();
  const level = (event.risk_flag_level as string | null) ?? "low";
  const riskType = (event.risk_flag_type as string | null) ?? null;
  const confidence = (event.extraction_confidence as number | undefined) ?? null;
  const sourceId = event.source_id as string | undefined;
  const occurredAt = event.occurred_at as string | null;

  // Confidence meter color: red < 0.5, amber 0.5-0.7, green >= 0.7
  const confidenceColor =
    confidence == null
      ? "bg-border/20"
      : confidence < 0.5
        ? "bg-risk-high"
        : confidence < 0.7
          ? "bg-risk-medium"
          : "bg-risk-low";

  return (
    <Card
      className={cn(
        "transition-all",
        acting && "opacity-60 pointer-events-none",
        highlight && "ring-2 ring-brand-500/30 ring-offset-2 ring-offset-bg"
      )}
    >
      <CardContent className="p-4 space-y-3">
        {/* Header: subject + action + risk badge */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              {level === "high" && (
                <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
              )}
              <span className="text-sm font-medium text-foreground truncate">
                {event.subject ?? t("review.unlabeled")}
              </span>
              <Badge variant="risk" riskLevel={level === "high" ? "high" : level === "medium" ? "medium" : "low"}>
                {t(`review.riskLevel.${level}`)}
              </Badge>
            </div>
            <div className="text-xs text-muted mt-1">
              <span className="text-foreground/80">{event.action}</span>
              {event.object && (
                <>
                  <span className="text-muted/60"> · </span>
                  <span>{event.object}</span>
                </>
              )}
            </div>
          </div>
          <div className="text-[10px] text-muted text-right shrink-0 space-y-0.5">
            <div>{formatDate(event.created_at)}</div>
            {occurredAt && (
              <div className="opacity-70">{t("review.occurred", { date: formatDate(occurredAt) })}</div>
            )}
          </div>
        </div>

        {/* Meta: risk type + confidence meter */}
        <div className="flex items-center gap-3 text-[10px] text-muted flex-wrap">
          {riskType && (
            <span>
              <span className="opacity-70">{t("review.riskType")}:</span>{" "}
              <span className="text-foreground/80">{riskType}</span>
            </span>
          )}
          {confidence != null && (
            <span className="inline-flex items-center gap-1.5">
              <span className="opacity-70">{t("review.confidence")}:</span>
              <span className="inline-flex items-center gap-1">
                <span className="relative h-1.5 w-12 rounded-full bg-border/15 overflow-hidden">
                  <span
                    className={cn("absolute inset-y-0 left-0 rounded-full", confidenceColor)}
                    style={{ width: `${Math.round(confidence * 100)}%` }}
                  />
                </span>
                <span className="tabular-nums text-foreground/80">
                  {(confidence * 100).toFixed(0)}%
                </span>
              </span>
            </span>
          )}
          {sourceId && (
            <Link
              href="/sources"
              className="inline-flex items-center gap-1 text-brand-600 dark:text-brand-400 hover:opacity-80"
            >
              <ExternalLink className="h-3 w-3" />
              {t("review.viewSource")}
            </Link>
          )}
        </div>

        {/* Actions: 采纳 / 忽略 / 保持沉降 — with helper text */}
        <div className="pt-2 border-t border-border/8 space-y-1.5">
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="default"
              onClick={() => onAction("approve")}
              disabled={acting}
              className="gap-1.5"
              title={t("review.actionHint.approve")}
            >
              {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              {t("review.approve")}
              <kbd className="ml-1 hidden sm:inline-flex items-center rounded border border-white/20 bg-white/10 px-1 text-[9px] font-mono">
                A
              </kbd>
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onAction("sink")}
              disabled={acting}
              className="gap-1.5"
              title={t("review.actionHint.sink")}
            >
              <Archive className="h-3.5 w-3.5" />
              {t("review.sink")}
              <kbd className="ml-1 hidden sm:inline-flex items-center rounded border border-border/30 bg-border/10 px-1 text-[9px] font-mono text-muted">
                S
              </kbd>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onAction("keep_sunk")}
              disabled={acting}
              className="gap-1.5"
              title={t("review.actionHint.keepSunk")}
            >
              <Anchor className="h-3.5 w-3.5" />
              {t("review.keepSunk")}
              <kbd className="ml-1 hidden sm:inline-flex items-center rounded border border-border/30 bg-border/10 px-1 text-[9px] font-mono text-muted">
                K
              </kbd>
            </Button>
          </div>
          {/* Helper text — explains what each action does, one line each */}
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-muted/80">
            <span>· {t("review.actionHint.approve")}</span>
            <span>· {t("review.actionHint.sink")}</span>
            <span>· {t("review.actionHint.keepSunk")}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
