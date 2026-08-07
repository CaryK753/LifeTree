"use client";

import {
  ExternalLink,
  AlertTriangle,
  ShieldAlert,
  TrendingUp,
  FileText,
  Layers,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  ResearchReport,
  ResearchKeyFinding,
  ResearchConflictSummary,
  ResearchTrendSummary,
  ResearchSourceSummary,
} from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { cn, formatDate, formatPercent } from "@/lib/utils";

function confidenceLabel(
  t: (k: string) => string,
  level?: string
): string {
  if (level === "high" || level === "medium" || level === "low") {
    return t(`research.report.confidence.${level}`);
  }
  return t("research.report.confidence.unknown");
}

function confidenceColor(level?: string): string {
  if (level === "high")
    return "border-green-500/30 bg-green-500/5 text-green-700 dark:text-green-300";
  if (level === "medium")
    return "border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300";
  if (level === "low")
    return "border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300";
  return "border-black/5 dark:border-white/10 text-zinc-500";
}

function trendLabel(
  t: (k: string) => string,
  direction?: string
): string {
  if (
    direction === "stable" ||
    direction === "changing" ||
    direction === "divergent"
  ) {
    return t(`research.report.trend${direction.charAt(0).toUpperCase() + direction.slice(1)}`);
  }
  return t("research.report.trendNull");
}

function engineLabel(
  t: (k: string) => string,
  name?: string | null
): string {
  if (!name) return "—";
  const key = `research.engine.${name}`;
  const label = t(key);
  return label === key ? name : label;
}

/**
 * ResearchReportView — renders the full research report produced by
 * the deep research LangGraph pipeline.
 *
 * Sections: summary → key findings → conflicts → trends → sources →
 * metadata → honesty disclaimer.
 *
 * Confidence levels and cross-engine consensus are computed by the
 * backend (not the LLM) to prevent overconfidence. The single-domain
 * warning is shown when only one domain is covered by the collected
 * sources, signalling limited reliability.
 */
export function ResearchReportView({
  report,
}: {
  report: ResearchReport;
}) {
  const t = useT();
  const meta = report.research_metadata;
  const domainCoverage = meta?.engine_domain_coverage;
  const coveredDomains = domainCoverage
    ? Object.values(domainCoverage).filter(Boolean).length
    : 0;
  const totalDomains = domainCoverage
    ? Object.keys(domainCoverage).length
    : 0;
  const singleDomain = totalDomains > 0 && coveredDomains <= 1;

  return (
    <div className="space-y-4">
      {/* Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <FileText className="h-4 w-4 text-brand-500" />
            {t("research.report.summary")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-foreground whitespace-pre-wrap">
            {report.summary}
          </p>
        </CardContent>
      </Card>

      {/* Key findings */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Layers className="h-4 w-4 text-brand-500" />
            {t("research.report.keyFindings")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {report.key_findings.length === 0 ? (
            <p className="text-sm text-muted-foreground">—</p>
          ) : (
            report.key_findings.map((kf, i) => (
              <KeyFindingCard key={i} kf={kf} t={t} />
            ))
          )}
        </CardContent>
      </Card>

      {/* Conflicts */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            {t("research.report.conflicts")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {report.conflicts.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("research.report.noConflicts")}
            </p>
          ) : (
            report.conflicts.map((c, i) => (
              <ConflictRow key={i} conflict={c} t={t} />
            ))
          )}
        </CardContent>
      </Card>

      {/* Trends */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-brand-500" />
            {t("research.report.trends")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {report.trends.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("research.report.noTrends")}
            </p>
          ) : (
            report.trends.map((tr, i) => (
              <TrendRow key={i} trend={tr} t={t} />
            ))
          )}
        </CardContent>
      </Card>

      {/* Sources */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <ExternalLink className="h-4 w-4 text-brand-500" />
            {t("research.report.sources")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5">
          {report.sources.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("research.report.noSources")}
            </p>
          ) : (
            report.sources.map((s, i) => (
              <SourceRow key={i} source={s} t={t} />
            ))
          )}
        </CardContent>
      </Card>

      {/* Metadata */}
      {meta && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">
              {t("research.report.metadata")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {singleDomain && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                {t("research.report.singleDomainWarning")}
              </div>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
              <MetaItem
                label={t("research.report.totalSources")}
                value={meta.total_sources_collected}
              />
              <MetaItem
                label={t("research.report.totalAssertions")}
                value={meta.total_assertions_extracted}
              />
              <MetaItem
                label={t("research.report.totalConflicts")}
                value={meta.total_conflicts_detected}
              />
              <MetaItem
                label={t("research.report.totalTrends")}
                value={meta.total_trends_detected}
              />
              <MetaItem
                label={t("research.report.llmCalls")}
                value={meta.llm_calls}
              />
            </div>
            {domainCoverage && (
              <div className="text-xs">
                <span className="text-muted-foreground">
                  {t("research.report.engineCoverage")}:{" "}
                </span>
                <span>
                  {Object.entries(domainCoverage)
                    .map(([d, ok]) => `${d}: ${ok ? "✓" : "✗"}`)
                    .join(" · ")}
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Honesty disclaimer */}
      {meta?.honesty_disclaimer && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-4 py-3 flex items-start gap-3">
          <ShieldAlert className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
          <div>
            <div className="text-xs font-medium text-amber-800 dark:text-amber-200">
              {t("research.report.disclaimer")}
            </div>
            <div className="text-xs text-amber-700 dark:text-amber-300 mt-1">
              {meta.honesty_disclaimer}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function KeyFindingCard({
  kf,
  t,
}: {
  kf: ResearchKeyFinding;
  t: (k: string) => string;
}) {
  return (
    <div className="rounded-md border border-black/5 dark:border-white/10 p-3 space-y-2">
      <p className="text-sm text-foreground">{kf.finding}</p>
      <div className="flex items-center gap-1.5 flex-wrap">
        {kf.confidence && (
          <span
            className={cn(
              "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border",
              confidenceColor(kf.confidence)
            )}
          >
            {confidenceLabel(t, kf.confidence)}
          </span>
        )}
        {typeof kf.cross_engine_consensus === "number" && (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border border-black/5 dark:border-white/10 text-zinc-500">
            {t("research.report.crossEngineConsensus")}:{" "}
            {formatPercent(kf.cross_engine_consensus, 0)}
          </span>
        )}
        {kf.trend && kf.trend !== "null" && (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border border-brand-500/30 bg-brand-500/5 text-brand-700 dark:text-brand-300">
            {trendLabel(t, kf.trend)}
          </span>
        )}
      </div>
      {kf.trend_detail && (
        <p className="text-xs text-muted-foreground">{kf.trend_detail}</p>
      )}
      {kf.caveats && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          ⚠️ {kf.caveats}
        </p>
      )}
    </div>
  );
}

function ConflictRow({
  conflict,
  t,
}: {
  conflict: ResearchConflictSummary;
  t: (k: string) => string;
}) {
  // Map conflict severity to a color. High severity = red, medium = amber,
  // low = neutral. The confidenceColor helper uses the opposite mapping
  // (high confidence = green), so we invert: severity "high" → "low"
  // confidence color (red).
  const severityColor =
    conflict.severity === "high"
      ? confidenceColor("low")
      : conflict.severity === "medium"
        ? confidenceColor("medium")
        : confidenceColor("low");

  return (
    <div className="rounded-md border border-black/5 dark:border-white/10 p-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-muted-foreground">
          {t("research.report.conflictSubject")}:
        </span>
        <span className="font-medium">{conflict.subject ?? "—"}</span>
        <span className="text-muted-foreground ml-2">
          {t("research.report.conflictPredicate")}:
        </span>
        <span className="font-medium">{conflict.predicate ?? "—"}</span>
        {conflict.severity && (
          <span
            className={cn(
              "ml-auto inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border",
              severityColor
            )}
          >
            {t("research.report.conflictSeverity")}: {conflict.severity}
          </span>
        )}
      </div>
      <div className="text-xs">
        <span className="text-muted-foreground">
          {t("research.report.conflictValues")}:
        </span>
        <div className="mt-1 space-y-0.5">
          {conflict.values.map((v, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="font-mono text-foreground">
                {JSON.stringify(v.value)}
              </span>
              {v.engines && v.engines.length > 0 && (
                <span className="text-muted-foreground">
                  [{v.engines.map((e) => engineLabel(t, e)).join(", ")}]
                </span>
              )}
              {typeof v.supporting_count === "number" && (
                <span className="text-muted-foreground">
                  ×{v.supporting_count}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TrendRow({
  trend,
  t,
}: {
  trend: ResearchTrendSummary;
  t: (k: string) => string;
}) {
  return (
    <div className="rounded-md border border-black/5 dark:border-white/10 p-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-muted-foreground">
          {t("research.report.conflictSubject")}:
        </span>
        <span className="font-medium">{trend.subject ?? "—"}</span>
        <span className="text-muted-foreground ml-2">
          {t("research.report.conflictPredicate")}:
        </span>
        <span className="font-medium">{trend.predicate ?? "—"}</span>
        <span className="ml-auto inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border border-brand-500/30 bg-brand-500/5 text-brand-700 dark:text-brand-300">
          {trendLabel(t, trend.direction)}
        </span>
      </div>
      {trend.transition_point && (
        <div className="text-xs">
          <span className="text-muted-foreground">
            {t("research.report.trendTransition")}:
          </span>
          <span className="ml-1">{trend.transition_point}</span>
        </div>
      )}
      {trend.timeline && trend.timeline.length > 0 && (
        <div className="text-xs">
          <span className="text-muted-foreground">
            {t("research.report.trendTimeline")}:
          </span>
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            {trend.timeline.map((p, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-black/5 dark:border-white/10"
              >
                <span className="font-mono">{JSON.stringify(p.value)}</span>
                {p.observed_at && (
                  <span className="text-muted-foreground text-[10px]">
                    {formatDate(p.observed_at)}
                  </span>
                )}
                {p.engine && (
                  <span className="text-muted-foreground text-[10px]">
                    [{engineLabel(t, p.engine)}]
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SourceRow({
  source,
  t,
}: {
  source: ResearchSourceSummary;
  t: (k: string) => string;
}) {
  return (
    <div className="flex items-center gap-2 text-xs py-0.5">
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border border-black/5 dark:border-white/10 text-zinc-500 shrink-0">
        {engineLabel(t, source.engine)}
      </span>
      {source.url ? (
        <a
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-brand-600 dark:text-brand-400 hover:underline truncate flex items-center gap-0.5"
        >
          <span className="truncate">{source.title ?? source.url}</span>
          <ExternalLink className="h-3 w-3 shrink-0" />
        </a>
      ) : (
        <span className="truncate text-foreground">
          {source.title ?? "—"}
        </span>
      )}
      {typeof source.score === "number" && (
        <span className="text-muted-foreground shrink-0">
          {formatPercent(source.score, 0)}
        </span>
      )}
    </div>
  );
}

function MetaItem({
  label,
  value,
}: {
  label: string;
  value?: number | null;
}) {
  return (
    <div className="rounded-md border border-black/5 dark:border-white/10 px-2 py-1.5">
      <div className="text-muted-foreground text-[10px]">{label}</div>
      <div className="font-medium">{value ?? "—"}</div>
    </div>
  );
}
