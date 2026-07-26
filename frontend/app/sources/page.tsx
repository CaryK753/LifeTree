"use client";

import { useState } from "react";
import { useSources, useCredibility } from "@/lib/hooks";
import { CredibilityMeter } from "@/components/dashboard/credibility-meter";
import { LifecyclePanel } from "@/components/sources/lifecycle-panel";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { Loader2, ThumbsUp, ThumbsDown, Upload, Trash2 } from "lucide-react";
import Link from "next/link";

// Credibility enum values returned by the backend. Rendered via i18n
// so users see localized labels instead of snake_case identifiers.
const CREDIBILITY_KEYS = [
  "high",
  "medium",
  "low",
  "user_marked_reliable",
  "user_marked_questionable",
  "unknown",
] as const;

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
  const { data: sources, mutate, isLoading } = useSources();
  const { data: credibility, mutate: mutateCred } = useCredibility();

  // Track which source is currently being marked so we can disable its
  // buttons and show a spinner. Keyed by source id.
  const [markingId, setMarkingId] = useState<string | null>(null);
  // Track which source is being deleted (separate state so marking and
  // deleting can't collide on the same row).
  const [deletingId, setDeletingId] = useState<string | null>(null);

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
    if (!confirm(t("sources.deleteConfirm", { title }))) return;
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
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">{t("sources.title")}</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">{t("sources.subtitle")}</p>
      </header>

      <CredibilityMeter credibility={credibility} />

      <LifecyclePanel />

      <Card>
        <CardHeader>
          <CardTitle>{t("sources.list.title")}</CardTitle>
          <CardDescription>{t("sources.list.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {isLoading ? (
              <div className="text-xs text-zinc-500 dark:text-zinc-400 text-center py-6 flex items-center justify-center gap-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t("common.loading")}
              </div>
            ) : (
              (sources as any[])?.map((s) => (
                <div key={s.id} className="grid grid-cols-[1fr_auto_auto_auto] gap-3 items-start py-3 border-b border-black/5 dark:border-white/5 last:border-0">
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
            {!isLoading && (!sources || (sources as any[]).length === 0) && (
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
    </div>
  );
}
