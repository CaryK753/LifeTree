"use client";

/**
 * ScenarioCurveOverlay — multi-scenario survival-curve overlay chart.
 *
 * §5 情景对比面板: "并列展示不同分支的概率曲线、里程碑差异、风险因子清单"
 *
 * Renders every scenario's survival curve on the same time axis so the user
 * can visually compare how each branch's probability of success evolves over
 * time. Each scenario gets its own colored line; hovering shows the exact
 * probability at that month for every branch.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { LineChart } from "lucide-react";
import { EChart } from "@/components/charts/echart";
import { useT } from "@/lib/i18n/provider";
import type { ScenarioNodeData } from "./scenario-tree";

interface Props {
  scenarios: ScenarioNodeData[];
}

// Distinguishable palette for up to 8 overlapping series. After 8 we cycle.
const SERIES_COLORS = [
  "#5eab7f", // brand green (baseline)
  "#60a5fa", // blue
  "#f59e0b", // amber
  "#a78bfa", // violet
  "#f472b6", // pink
  "#34d399", // emerald
  "#fb923c", // orange
  "#22d3ee", // cyan
];

export function ScenarioCurveOverlay({ scenarios }: Props) {
  const t = useT();

  // Build a sorted, de-duplicated union of all month values across scenarios
  // so each series shares the same x-axis. Use month if present, else t.
  const allMonths = Array.from(
    new Set(
      scenarios.flatMap(
        (s) => (s.survival_curve ?? []).map((p) => p.month ?? p.t ?? 0)
      )
    )
  ).sort((a, b) => a - b);

  const hasAnyCurve = scenarios.some(
    (s) => s.survival_curve && s.survival_curve.length > 0
  );

  if (!hasAnyCurve) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <LineChart className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("scenarioComparison.overlayTitle")}
          </CardTitle>
          <CardDescription>{t("scenarioComparison.overlayEmpty")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  // Build one ECharts series per scenario that has a curve.
  const series = scenarios
    .map((s, i) => {
      const curve = s.survival_curve ?? [];
      if (curve.length === 0) return null;
      const color = SERIES_COLORS[i % SERIES_COLORS.length];
      // Map month -> probability for O(1) lookup
      const lookup = new Map<number, number | null>();
      for (const p of curve) {
        const m = p.month ?? p.t ?? 0;
        const v = typeof p.p === "number" ? p.p * 100 : null;
        lookup.set(m, v);
      }
      // Sample at every month in the union; null where this scenario has no data.
      const data = allMonths.map((m) => lookup.get(m) ?? null);
      return {
        type: "line" as const,
        name: s.name,
        smooth: true,
        symbol: "circle",
        symbolSize: 4,
        showSymbol: false,
        data,
        lineStyle: { width: 2.5, color },
        itemStyle: { color },
        connectNulls: true,
      };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);

  // Median-time markers per scenario (vertical dashed lines, color-matched).
  const markLines: any[] = [];
  scenarios.forEach((s, i) => {
    if (s.median_time_months == null) return;
    const color = SERIES_COLORS[i % SERIES_COLORS.length];
    markLines.push({
      xAxis: s.median_time_months,
      label: {
        formatter: `${s.name}: ${s.median_time_months}m`,
        position: "insideEndTop",
        color,
        fontSize: 9,
      },
      lineStyle: { color, type: "dashed", width: 1 },
    });
  });

  const option = {
    grid: { left: 40, right: 24, top: 50, bottom: 36, containLabel: true },
    legend: {
      type: "scroll" as const,
      top: 8,
      textStyle: { fontSize: 11 },
      pageTextStyle: { fontSize: 10 },
    },
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return "";
        const m = params[0]?.axisValueLabel ?? "";
        const lines = params
          .filter((p: any) => p.data != null)
          .map(
            (p: any) =>
              `${p.marker} ${p.seriesName}: <b>${(p.data as number).toFixed(1)}%</b>`
          );
        return [`${m}m`, ...lines].join("<br/>");
      },
    },
    xAxis: {
      type: "category" as const,
      data: allMonths,
      name: t("survivalCurve.xAxis"),
      nameLocation: "middle" as const,
      nameGap: 26,
      nameTextStyle: { fontSize: 10 },
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: "value" as const,
      min: 0,
      max: 100,
      axisLabel: { fontSize: 10, formatter: "{value}%" },
      splitLine: { lineStyle: { color: "rgba(127,127,127,0.15)" } },
    },
    series:
      markLines.length > 0
        ? series.map((s) => ({
            ...s,
            markLine: {
              symbol: ["none", "none"],
              silent: true,
              data: markLines,
            },
          }))
        : series,
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <LineChart className="h-4 w-4 text-brand-600 dark:text-brand-400" />
          {t("scenarioComparison.overlayTitle")}
        </CardTitle>
        <CardDescription>
          {t("scenarioComparison.overlaySubtitle")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <EChart option={option} height={420} />
      </CardContent>
    </Card>
  );
}
