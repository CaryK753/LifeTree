"use client";

import Link from "next/link";
import { Check, ExternalLink, Filter, GitBranch, Keyboard, Layers, Loader2 } from "lucide-react";
import { IntelligenceReviewSections } from "@/components/review/intelligence-review-sections";
import { ReviewEventCard } from "@/components/review/review-event-card";
import { useEventReviewQueue, type RiskFilter } from "@/components/review/use-event-review-queue";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

export function EventsReviewTab() {
  const t = useT();
  const queue = useEventReviewQueue();
  const filters: RiskFilter[] = ["all", "high", "medium", "low"];
  return (
    <>
      {queue.ConfirmRoot}
      <IntelligenceReviewSections />
      {queue.items.length > 0 && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1 p-1 rounded-lg bg-surface-2/60 border border-border/10">
            <Filter className="h-3.5 w-3.5 text-muted-foreground mx-1.5" />
            {filters.map((filter) => (
              <FilterButton
                key={filter}
                active={queue.filter === filter}
                label={t(`review.filter.${filter}`)}
                count={queue.counts[filter]}
                onClick={() => queue.setFilter(filter)}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => queue.handleBatch("sink")} disabled={queue.batchRunning || !queue.filteredItems.length}>
              {queue.batchRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Layers className="h-3.5 w-3.5" />}
              <span className="ml-1.5">{t("review.batch.sinkAll")}</span>
            </Button>
            <Button size="sm" onClick={() => queue.handleBatch("approve")} disabled={queue.batchRunning || !queue.filteredItems.length}>
              {queue.batchRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              <span className="ml-1.5">{t("review.batch.approveAll")}</span>
            </Button>
          </div>
        </div>
      )}

      {queue.isLoading ? (
        <ReviewSkeleton />
      ) : queue.items.length === 0 ? (
        <EmptyReviewState />
      ) : queue.filteredItems.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">{t("review.noFiltered")}</CardContent></Card>
      ) : (
        <>
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Keyboard className="h-3 w-3" />{t("review.shortcut.hint")}
          </div>
          <div className="space-y-3">
            {queue.filteredItems.map((event, index) => (
              <ReviewEventCard
                key={event.id}
                event={event}
                acting={queue.actingId === event.id}
                highlight={index === 0 && !queue.actingId && !queue.batchRunning}
                onAction={(action) => queue.handleAction(event.id, action)}
              />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function FilterButton({ active, label, count, onClick }: {
  active: boolean;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return <button type="button" onClick={onClick} className={cn("inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium", active ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}><span>{label}</span><span className="rounded-full bg-brand-500/15 px-1.5 py-0.5 text-[10px]">{count}</span></button>;
}

function ReviewSkeleton() {
  return <div className="space-y-3">{[0, 1, 2].map((index) => <Card key={index}><CardContent className="p-4 space-y-3"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-3 w-full" /><Skeleton className="h-7 w-40" /></CardContent></Card>)}</div>;
}

function EmptyReviewState() {
  const t = useT();
  return (
    <Card>
      <CardContent className="py-12 text-center space-y-3">
        <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center"><Check className="h-6 w-6 text-brand-500" /></div>
        <div className="text-sm">{t("review.empty")}</div>
        <p className="text-xs text-muted-foreground">{t("review.emptyHint")}</p>
        <div className="flex justify-center gap-2 pt-2">
          <Button asChild variant="outline" size="sm"><Link href="/ingest"><ExternalLink className="h-3.5 w-3.5 mr-1.5" />{t("review.goIngest")}</Link></Button>
          <Button asChild variant="ghost" size="sm"><Link href="/goals"><GitBranch className="h-3.5 w-3.5 mr-1.5" />{t("review.viewBranches")}</Link></Button>
        </div>
      </CardContent>
    </Card>
  );
}
