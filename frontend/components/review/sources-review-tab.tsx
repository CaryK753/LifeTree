"use client";

/**
 * SourcesReviewTab — pending-credibility sources queue for the Review
 * Center. Mirrors the "Review Queue" card that used to live on /sources.
 *
 * Uses the unified review inbox so the page header, tab badge, and source
 * queue share one contract. The source library is revalidated after marking.
 */

import { useState } from "react";
import { mutate as mutateCache } from "swr";
import { useCredibility, useUnifiedReview } from "@/lib/hooks";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Loader2, ThumbsUp, ThumbsDown, ExternalLink } from "lucide-react";
import { formatDate } from "@/lib/utils";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";

export function SourcesReviewTab() {
  const t = useT();
  const toast = useToast();
  const { data, mutate, isLoading } = useUnifiedReview();
  const { mutate: mutateCred } = useCredibility();

  // Track which source is currently being marked so we can disable its
  // buttons and show a spinner. Keyed by source id.
  const [markingId, setMarkingId] = useState<string | null>(null);

  const pendingSources = data?.pending_sources ?? [];

  async function handleMark(id: string, level: string) {
    if (markingId) return; // prevent concurrent marks
    setMarkingId(id);
    try {
      await api.markCredibility(id, level);
      await Promise.all([mutate(), mutateCred(), mutateCache("sources")]);
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

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Card key={i} className="opacity-80">
            <CardContent className="p-4 space-y-3">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-2/3" />
              <div className="flex gap-2 pt-2">
                <Skeleton className="h-7 w-20" />
                <Skeleton className="h-7 w-20" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (pendingSources.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center space-y-3">
          <div className="mx-auto h-12 w-12 rounded-full bg-emerald-500/10 flex items-center justify-center">
            <ThumbsUp className="h-6 w-6 text-emerald-500" />
          </div>
          <div className="text-sm text-foreground">{t("review.sources.empty")}</div>
          <p className="text-xs text-muted-foreground">{t("review.sources.subtitle")}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Queue summary */}
      <Card className="border-amber-500/30 bg-amber-500/[0.03]">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <span className="inline-block h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                {t("sources.review.title")}
              </CardTitle>
              <CardDescription className="mt-1">
                {t("review.sources.subtitle")}
              </CardDescription>
            </div>
            <Badge variant="risk" riskLevel="medium">
              {pendingSources.length}
            </Badge>
          </div>
        </CardHeader>
      </Card>

      {/* Pending source list */}
      <div className="space-y-2">
        {pendingSources.map((s) => (
          <Card key={s.id}>
            <CardContent className="p-4">
              <div className="grid grid-cols-[1fr_auto_auto] gap-3 items-center">
                <div className="min-w-0">
                  <div className="text-sm text-zinc-800 dark:text-zinc-200 truncate">
                    {s.title}
                  </div>
                  <div className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                    {t(`kind.${s.kind}`)} · {s.publisher ?? "—"} · {formatDate(s.published_at)}
                  </div>
                  {s.url && (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[10px] text-brand-600 dark:text-brand-400 hover:underline mt-0.5"
                    >
                      <ExternalLink className="h-2.5 w-2.5" />
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
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
