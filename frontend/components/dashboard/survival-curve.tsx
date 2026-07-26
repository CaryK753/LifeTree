"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { TrendingDown } from "lucide-react";
import { EChart } from "@/components/charts/echart";
import { useT } from "@/lib/i18n/provider";
import type { SurvivalPoint, KeyRiskTime } from "@/lib/api";

interface Props {
  curve?: SurvivalPoint[];
  keyRiskTimes?: KeyRiskTime[];
  medianTimeMonths?: number | null;
}

/**
 * §5 透明化 — visualizes the survival curve (probability of still being
 * "on track" as a function of months elapsed) and overlays key risk times
 * as vertical markers.
 *
 * The chart is rendered with ECharts so it animates on mount and stays
 * responsive across container sizes.
 */
export function SurvivalCurve({ curve, keyRiskTimes, medianTimeMonths }: Props) {
  const t = useT();

  if (!curve || curve.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-amber-400" />
            {t("survivalCurve.title")}
          </CardTitle>
          <CardDescription>{t("survivalCurve.empty")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const months = curve.map((p) => p.month ?? p.t ?? 0);
  const probs = curve.map((p) => {
    const v = p.p;
    return typeof v === "number" ? v * 100 : null;
  });

  const markLines: any[] = [];
  if (medianTimeMonths != null) {
    markLines.push({
      xAxis: medianTimeMonths,
      label: {
        formatter: `${t("survivalCurve.median")} ${medianTimeMonths}m`,
        position: "insideEndTop",
        color: "#fbbf24",
        fontSize: 10,
      },
      lineStyle: { color: "#fbbf24", type: "dashed", width: 1.5 },
    });
  }
  for (const kr of keyRiskTimes ?? []) {
    if (kr.month == null) continue;
    markLines.push({
      xAxis: kr.month,
      label: {
        formatter: kr.label ?? `Risk ${kr.month}m`,
        position: "insideEndTop",
        color: "#f87171",
        fontSize: 10,
      },
      lineStyle: { color: "#f87171", type: "dotted", width: 1.2 },
    });
  }

  const option = {
    grid: { left: 36, right: 18, top: 18, bottom: 28, containLabel: true },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        const m = params?.[0]?.axisValueLabel ?? "";
        const v = params?.[0]?.data;
        return `${m}m<br/>P=${v != null ? v.toFixed(1) : "—"}%`;
      },
    },
    xAxis: {
      type: "category",
      data: months,
      name: t("survivalCurve.xAxis"),
      nameLocation: "middle",
      nameGap: 22,
      nameTextStyle: { color: "#a1a8a3", fontSize: 10 },
      axisLabel: { color: "#a1a8a3", fontSize: 10 },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      axisLabel: {
        color: "#a1a8a3",
        fontSize: 10,
        formatter: "{value}%",
      },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } },
    },
    series: [
      {
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 4,
        data: probs,
        lineStyle: { width: 2.5, color: "#5eab7f" },
        itemStyle: { color: "#5eab7f" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(94, 171, 127, 0.32)" },
              { offset: 1, color: "rgba(94, 171, 127, 0.02)" },
            ],
          },
        },
        markLine: {
          symbol: ["none", "none"],
          silent: true,
          data: markLines,
        },
      },
    ],
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <TrendingDown className="h-4 w-4 text-amber-400" />
          {t("survivalCurve.title")}
        </CardTitle>
        {medianTimeMonths != null && (
          <CardDescription>
            {t("survivalCurve.subtitle", { n: medianTimeMonths })}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <EChart option={option} height={260} />
      </CardContent>
    </Card>
  );
}
