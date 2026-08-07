"use client";

/**
 * ConflictsTab — Assertion-level cross-source conflict review (§B.6).
 *
 * Enhanced to display:
 * - Severity badge (high/medium/low) with high-severity conflicts pinned to top.
 * - Per-value engine tags and cross-engine consensus info.
 * - Temporal validity (valid_from → valid_to) from Assertion timestamps.
 * - Collapsible source excerpt for each assertion.
 * - Auto-merged badge for consensus-resolved groups.
 */

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { api, type ReviewConflict, type ReviewConflictAssertion } from "@/lib/api";
import { useUnifiedReview } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

function severityColor(severity: string): string {
  if (severity === "high") return "bg-red-500/15 text-red-500 border-red-500/20";
  if (severity === "medium") return "bg-amber-500/15 text-amber-500 border-amber-500/20";
  return "bg-zinc-500/15 text-zinc-400 border-zinc-500/20";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatTemporal(a: ReviewConflictAssertion): string {
  const fmt = (iso: string | null) => {
    if (!iso) return null;
    try {
      return new Date(iso).toLocaleDateString();
    } catch {
      return iso;
    }
  };
  const from = fmt(a.valid_from);
  const to = fmt(a.valid_to);
  if (from && to) return `${from} → ${to}`;
  if (from) return `${from} → …`;
  if (a.observed_at) return fmt(a.observed_at) ?? "";
  return "";
}

function AssertionExcerpt({ assertion }: { assertion: ReviewConflictAssertion }) {
  const [open, setOpen] = useState(false);
  if (!assertion.source_excerpt) return null;
  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span>{useT_safe("review.conflicts.source_excerpt", "原文摘录")}</span>
      </button>
      {open && (
        <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-muted-foreground italic">
          {assertion.source_excerpt}
        </blockquote>
      )}
    </div>
  );
}

// Lightweight i18n fallback so we don't need to add keys to all 6 locales
// just for these labels. Uses the real useT() when a key exists.
function useT_safe(key: string, fallback: string): string {
  const t = useT();
  const val = t(key);
  return val === key ? fallback : val;
}

export function ConflictsTab() {
  const t = useT();
  const toast = useToast();
  const { data, mutate, isLoading } = useUnifiedReview();
  const [working, setWorking] = useState<string | null>(null);

  async function run(id: string, operation: () => Promise<unknown>) {
    setWorking(id);
    try {
      await operation();
      await mutate();
      toast({ title: t("review.intelligence.saved"), variant: "success" });
    } catch (error: any) {
      toast({
        title: t("review.intelligence.failed"),
        description: error?.message,
        variant: "error",
      });
    } finally {
      setWorking(null);
    }
  }

  if (isLoading) {
    return <Skeleton className="h-28 w-full" />;
  }

  const conflicts = data?.conflicts ?? [];

  if (conflicts.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center space-y-3">
          <div className="mx-auto h-12 w-12 rounded-full bg-emerald-500/10 flex items-center justify-center">
            <Check className="h-6 w-6 text-emerald-500" />
          </div>
          <div className="text-sm text-foreground">{t("review.conflicts.empty")}</div>
        </CardContent>
      </Card>
    );
  }

  // Sort: high severity first, then medium, then low.
  const sorted = [...conflicts].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3)
  );

  return (
    <div className="space-y-2">
      {sorted.map((conflict) => {
        const id = `${conflict.subject}:${conflict.predicate}`;
        return (
          <Card key={id} className={conflict.severity === "high" ? "border-red-500/30" : ""}>
            <CardContent className="p-4 space-y-3">
              {/* Header: severity + subject + predicate */}
              <div className="flex items-start justify-between gap-2">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium ${severityColor(conflict.severity)}`}
                    >
                      {conflict.severity === "high" && (
                        <AlertTriangle className="h-3 w-3" />
                      )}
                      {conflict.severity.toUpperCase()}
                    </span>
                    {conflict.auto_merged && (
                      <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/20 bg-emerald-500/15 px-1.5 py-0.5 text-xs font-medium text-emerald-500">
                        <ShieldCheck className="h-3 w-3" />
                        {useT_safe("review.conflicts.auto_merged", "已自动合并")}
                      </span>
                    )}
                    {conflict.affected_goal_count > 0 && (
                      <span className="text-xs text-muted-foreground">
                        · {conflict.affected_goal_count} goals
                      </span>
                    )}
                  </div>
                  <div className="text-sm font-medium text-foreground">
                    {conflict.subject}{" "}
                    <span className="text-muted-foreground">· {conflict.predicate}</span>
                  </div>
                </div>
              </div>

              {/* Cross-engine consensus summary */}
              {conflict.cross_engine_consensus && (
                <div className="flex items-center gap-2 rounded-md bg-primary/5 px-2 py-1 text-xs text-muted-foreground">
                  <Zap className="h-3 w-3 text-primary" />
                  <span>
                    {useT_safe("review.conflicts.cross_engine_consensus", "跨引擎一致性")}:{" "}
                    {conflict.cross_engine_consensus.supporting_engines.join(", ")}{" "}
                    (bonus ×{conflict.cross_engine_consensus.engine_diversity_bonus})
                  </span>
                </div>
              )}

              {/* Values */}
              <div className="space-y-2">
                {conflict.values.map((val, vi) => {
                  const resolveId = val.source_ids[0];
                  const valAsserts = conflict.assertions.filter((a) =>
                    val.assertion_ids.includes(a.id)
                  );
                  return (
                    <div
                      key={`${id}:v${vi}`}
                      className="rounded-md border border-border p-2 space-y-1.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 flex-wrap min-w-0">
                          <span className="text-sm font-medium text-foreground truncate">
                            {formatValue(val.value)}
                          </span>
                          {val.engines.map((eng) => (
                            <span
                              key={eng}
                              className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-mono text-primary"
                            >
                              {eng}
                            </span>
                          ))}
                          <span className="text-xs text-muted-foreground">
                            · {val.supporting_count}{" "}
                            {useT_safe("review.conflicts.supporting", "支持")} ·{" "}
                            {val.min_source_credibility}
                          </span>
                        </div>
                        {resolveId && !conflict.auto_merged && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={working === id}
                            onClick={() =>
                              run(id, () =>
                                api.resolveSourceConflict(conflict, resolveId)
                              )
                            }
                          >
                            {working === id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Check className="h-3.5 w-3.5" />
                            )}
                            <span className="ml-1.5 text-xs">
                              {useT_safe("review.conflicts.resolve", "采纳")}
                            </span>
                          </Button>
                        )}
                      </div>

                      {/* Per-assertion temporal + excerpt */}
                      {valAsserts.map((a) => {
                        const temporal = formatTemporal(a);
                        return (
                          <div key={a.id} className="pl-2 border-l border-border/50">
                            {temporal && (
                              <div className="text-xs text-muted-foreground">
                                {temporal}
                                {a.engine && ` · ${a.engine}`}
                                {a.source_title && ` · ${a.source_title}`}
                              </div>
                            )}
                            <AssertionExcerpt assertion={a} />
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
