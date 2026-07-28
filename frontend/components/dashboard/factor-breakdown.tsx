"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ShieldCheck, AlertTriangle, ChevronDown, ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { cn, formatPercent } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { EChart } from "@/components/charts/echart";
import type { FactorContribution } from "@/lib/api";

/**
 * §5.3 白盒化推理 — Attribution Waterfall.
 *
 * Renders a true waterfall chart showing how each factor contributes to
 * the gap between the baseline (100% success) and the final overall
 * success probability. Each bar represents a factor's contribution:
 *   - Requirements (green, positive): drag down because they're unmet
 *   - Risk factors (amber): drag down by probability of materialization
 *
 * Below the chart, a sortable list shows the per-factor detail with
 * P(success) and contribution %. Clicking a factor row opens the source
 * drill-down dialog (§5.3 信源溯源下钻) when source info is available.
 */
export function FactorBreakdown({
  factors,
  overallP,
}: {
  factors: FactorContribution[];
  /** Overall success probability from the Bayesian model — used as the
   * terminal value of the waterfall. When absent, falls back to
   * 1 - sum(contributions). */
  overallP?: number;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<FactorContribution | null>(null);

  const sorted = useMemo(
    () =>
      [...factors].sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0)),
    [factors]
  );
  const visible = expanded ? sorted : sorted.slice(0, 5);
  const hiddenCount = sorted.length - visible.length;

  // Build the waterfall chart option. The chart shows:
  //   bar 1: baseline (100%)
  //   bar 2..n: each factor's contribution (downward, since they drag
  //             success probability below 100%)
  //   bar n+1: final overall P(success)
  const option = useMemo(() => {
    if (sorted.length === 0) return {};

    const totalDrag = sorted.reduce((s, f) => s + (f.contribution ?? 0), 0);
    const baseline = 1.0;
    const terminal = overallP != null ? overallP : Math.max(0, 1 - totalDrag);

    // Build the "stacked" data for ECharts waterfall. Each factor is a
    // floating bar from its start to start+contribution. We use a
    // transparent placeholder + visible bar to create the float effect.
    const placeholders: (number | null)[] = [0]; // baseline starts at 0
    const values: (number | null)[] = [baseline];
    const colors: string[] = ["#5eab7f"]; // baseline = green
    const xLabels: string[] = [t("factorBreakdown.baseline")];

    let cursor = baseline;
    for (const f of sorted.slice(0, 8)) {
      // top 8 to keep chart readable
      const drag = f.contribution ?? 0;
      const isRisk = f.type === "risk_factor";
      placeholders.push(cursor - drag); // bottom of the floating bar
      values.push(drag);
      colors.push(isRisk ? "#fbbf24" : "#60a5fa");
      // Truncate long names for the x-axis label
      const shortName =
        f.name.length > 12 ? f.name.slice(0, 11) + "…" : f.name;
      xLabels.push(shortName);
      cursor -= drag;
    }

    // Terminal bar
    placeholders.push(0);
    values.push(terminal);
    colors.push(terminal >= 0.75 ? "#5eab7f" : terminal >= 0.45 ? "#fbbf24" : "#f87171");
    xLabels.push(t("factorBreakdown.final"));

    return {
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
          const idx = params[0]?.dataIndex ?? 0;
          const label = xLabels[idx] ?? "";
          const val = values[idx];
          if (val == null) return label;
          // Baseline and final show absolute %, middle bars show drag
          if (idx === 0 || idx === xLabels.length - 1) {
            return `${label}<br/><b>${(val * 100).toFixed(1)}%</b>`;
          }
          return `${label}<br/>${t("factorBreakdown.drag")}: <b>-${(val * 100).toFixed(1)}%</b>`;
        },
      },
      grid: {
        left: 40,
        right: 16,
        top: 16,
        bottom: 56,
        containLabel: true,
      },
      xAxis: {
        type: "category",
        data: xLabels,
        axisLabel: {
          color: "#a1a8a3",
          fontSize: 10,
          rotate: 35,
          interval: 0,
        },
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
      },
      yAxis: {
        type: "value",
        max: 1,
        min: 0,
        axisLabel: {
          color: "#a1a8a3",
          fontSize: 11,
          formatter: (v: number) => `${Math.round(v * 100)}%`,
        },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } },
      },
      series: [
        // Transparent placeholder (creates the floating effect)
        {
          type: "bar",
          stack: "waterfall",
          itemStyle: { color: "transparent" },
          data: placeholders,
          barWidth: "60%",
          silent: true,
        },
        // Visible bars
        {
          type: "bar",
          stack: "waterfall",
          itemStyle: {
            color: (params: any) => colors[params.dataIndex] ?? "#5eab7f",
            borderRadius: [2, 2, 0, 0],
          },
          data: values,
          barWidth: "60%",
          label: {
            show: true,
            position: "top",
            color: "#cbd5cb",
            fontSize: 10,
            formatter: (params: any) => {
              const v = params.value;
              if (v == null) return "";
              return `${(v * 100).toFixed(0)}%`;
            },
          },
        },
      ],
    };
  }, [sorted, overallP, t]);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          {t("factorBreakdown.title")}
        </CardTitle>
        <CardDescription className="mt-1">
          {t("factorBreakdown.subtitle")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {sorted.length === 0 ? (
          <div className="text-xs text-zinc-500 py-3 text-center">
            {t("factorBreakdown.empty")}
          </div>
        ) : (
          <>
            {/* Waterfall chart */}
            <EChart
              option={option}
              height={220}
              refreshKey={sorted.map((f) => `${f.name}:${f.contribution}`).join("|")}
              aria-label={t("factorBreakdown.title")}
            />

            {/* Factor list — sortable, click to drill down */}
            <ul className="space-y-1.5">
              {visible.map((f, i) => {
                const isRisk = f.type === "risk_factor";
                const contribution = f.contribution ?? 0;
                const p = f.p ?? 0;
                const hasSource = !!f.source_url || !!f.source_title;
                return (
                  <li
                    key={`${i}-${f.name}`}
                    className={cn(
                      "flex items-center gap-2 text-xs px-2 py-1.5 rounded-md transition-colors",
                      hasSource
                        ? "cursor-pointer hover:bg-white/[0.04]"
                        : "cursor-default"
                    )}
                    onClick={() => hasSource && setSelected(f)}
                    title={hasSource ? t("factorBreakdown.clickToDrill") : undefined}
                  >
                    {isRisk ? (
                      <AlertTriangle className="h-3 w-3 text-amber-400 shrink-0" />
                    ) : (
                      <ShieldCheck className="h-3 w-3 text-brand-400 shrink-0" />
                    )}
                    <span className="text-zinc-200 truncate flex-1" title={f.name}>
                      {f.name}
                    </span>
                    <span className="text-[10px] text-zinc-500 shrink-0">
                      P={formatPercent(p, 0)}
                    </span>
                    <span className="text-[10px] text-amber-400/80 w-12 text-right tabular-nums shrink-0">
                      -{(contribution * 100).toFixed(1)}%
                    </span>
                    {hasSource && (
                      <ExternalLink className="h-3 w-3 text-zinc-600 shrink-0" />
                    )}
                  </li>
                );
              })}
            </ul>

            {hiddenCount > 0 && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="mt-1 w-full text-[11px] text-zinc-500 hover:text-zinc-300 flex items-center justify-center gap-1 transition-colors"
              >
                <ChevronDown
                  className={cn(
                    "h-3 w-3 transition-transform",
                    expanded && "rotate-180"
                  )}
                />
                {expanded
                  ? t("factorBreakdown.collapse")
                  : t("factorBreakdown.expandMore", { n: hiddenCount })}
              </button>
            )}
          </>
        )}
      </CardContent>

      {/* Source drill-down dialog (§5.3 信源溯源下钻) */}
      {selected && (
        <SourceDrillDown
          factor={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </Card>
  );
}

// ============== Source Drill-Down Dialog ==============

/**
 * SourceDrillDown — shows the original source behind a factor so the
 * user can verify the data (§5.3 "信源溯源下钻：任何扣分因子均可一键
 * 下钻查看原始文件或新闻网页").
 *
 * Currently displays source_title + source_url when the backend
 * provides them. When the backend doesn't yet attach source info,
 * the list row won't be clickable and this dialog won't open.
 */
function SourceDrillDown({
  factor,
  onClose,
}: {
  factor: FactorContribution;
  onClose: () => void;
}) {
  const t = useT();
  const sourceTitle = factor.source_title;
  const sourceUrl = factor.source_url;
  const sourceKind = factor.source_kind;
  const sourceCredibility = factor.source_credibility;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-lg border border-white/10 bg-zinc-900 shadow-xl p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs text-zinc-500 mb-1">
              {t("factorBreakdown.sourceOf")}
            </div>
            <div className="text-sm font-medium text-zinc-100 truncate">
              {factor.name}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-200 shrink-0"
          >
            ✕
          </button>
        </div>

        <div className="space-y-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 w-16 shrink-0">
              {t("factorBreakdown.type")}:
            </span>
            <span className="text-zinc-200">
              {factor.type === "risk_factor"
                ? t("factorBreakdown.riskFactor")
                : t("factorBreakdown.requirement")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 w-16 shrink-0">
              {t("factorBreakdown.contribution")}:
            </span>
            <span className="text-amber-400">
              -{((factor.contribution ?? 0) * 100).toFixed(1)}%
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 w-16 shrink-0">
              {t("factorBreakdown.pSuccess")}:
            </span>
            <span className="text-zinc-200">
              {formatPercent(factor.p ?? 0, 0)}
            </span>
          </div>

          {sourceTitle && (
            <div className="pt-2 border-t border-white/5 space-y-1.5">
              <div className="text-zinc-500 text-[11px] uppercase tracking-wider">
                {t("factorBreakdown.source")}
              </div>
              <div className="text-zinc-200">{sourceTitle}</div>
              <div className="flex items-center gap-2 text-[10px] text-zinc-500">
                {sourceKind && <span>{sourceKind}</span>}
                {sourceCredibility && (
                  <span
                    className={cn(
                      "px-1.5 py-0.5 rounded-sm",
                      sourceCredibility === "high" || sourceCredibility === "user_marked_reliable"
                        ? "bg-emerald-500/15 text-emerald-400"
                        : sourceCredibility === "low" || sourceCredibility === "user_marked_questionable"
                          ? "bg-red-500/15 text-red-400"
                          : "bg-zinc-500/15 text-zinc-400"
                    )}
                  >
                    {t(`factorBreakdown.credibility.${sourceCredibility}`)}
                  </span>
                )}
              </div>
              {sourceUrl && (
                <a
                  href={sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-brand-400 hover:text-brand-300 text-[11px] mt-1"
                >
                  <ExternalLink className="h-3 w-3" />
                  {t("factorBreakdown.openSource")}
                </a>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
