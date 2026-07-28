"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CalendarRange } from "lucide-react";
import { useMemo } from "react";
import { useT } from "@/lib/i18n/provider";
import { EChart } from "@/components/charts/echart";

/**
 * §5 时间线/甘特图主视图 — Timeline Gantt.
 *
 * Renders milestones across a horizontal time axis so the user can see the
 * full path-to-goal at a glance: which milestones are done, which are in
 * progress, and which are upcoming. Pathways appear as swim-lanes (one bar
 * per pathway row); the goal's target date is drawn as a vertical deadline
 * line and "today" is marked with a contrasting now-line.
 *
 * Per project plan §5: "目标罗盘仪表盘——单一时间线视图上呈现关键里程
 * 碑、进度、风险热区与近期事件流". This component is the timeline half.
 */
interface GanttMilestone {
  label?: string;
  date?: string;
  due?: string;
  status?: string;
  pathway?: string;
  [k: string]: unknown;
}

interface Props {
  milestones: GanttMilestone[];
  targetDate?: string;
}

const STATUS_COLOR: Record<string, string> = {
  done: "#5eab7f",
  complete: "#5eab7f",
  completed: "#5eab7f",
  met: "#5eab7f",
  in_progress: "#fbbf24",
  pending: "#8b9389",
  not_started: "#5a6159",
};

function statusColor(status?: string): string {
  if (!status) return "#8b9389";
  const k = status.toLowerCase();
  return STATUS_COLOR[k] ?? "#8b9389";
}

function isDone(status?: string): boolean {
  return Boolean(status?.toLowerCase().match(/done|complete|met/i));
}

function milestoneDate(m: GanttMilestone): Date | null {
  const raw = m.date ?? m.due;
  if (!raw) return null;
  const d = new Date(raw);
  return isNaN(d.getTime()) ? null : d;
}

export function TimelineGantt({ milestones, targetDate }: Props) {
  const t = useT();

  const { option, hasData } = useMemo(() => {
    // Gather valid milestones with parseable dates.
    const items = milestones
      .map((m) => {
        const d = milestoneDate(m);
        if (!d) return null;
        return { ...m, _date: d };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null)
      .sort((a, b) => a._date.getTime() - b._date.getTime());

    if (items.length === 0) return { option: {}, hasData: false };

    // Determine time range.
    const now = new Date();
    const dates = items.map((m) => m._date.getTime());
    if (targetDate) {
      const td = new Date(targetDate);
      if (!isNaN(td.getTime())) dates.push(td.getTime());
    }
    dates.push(now.getTime());

    const minTime = Math.min(...dates);
    const maxTime = Math.max(...dates);
    // Pad the range by 5% on each side so bars don't hug the edges.
    const span = Math.max(maxTime - minTime, 24 * 3600 * 1000); // min 1 day
    const pad = span * 0.05;
    const xMin = minTime - pad;
    const xMax = maxTime + pad;

    // Group by pathway → swim-lane row index.
    const pathways = Array.from(
      new Set(items.map((m) => m.pathway || t("timelineGantt.defaultLane")))
    );
    const laneIndex: Record<string, number> = {};
    pathways.forEach((p, i) => {
      laneIndex[p] = i;
    });

    // Build scatter data: [timestamp, lane, milestone].
    // We use a custom-rendered scatter so each milestone is a diamond/marker
    // on its date, with a connecting bar back to the lane's start (today or
    // the first milestone) to convey elapsed time.
    const scatterData: any[] = [];
    const barData: any[] = []; // bars from "now" (or lane start) to milestone

    for (const m of items) {
      const lane = laneIndex[m.pathway || t("timelineGantt.defaultLane")];
      const ts = m._date.getTime();
      const color = statusColor(m.status);

      scatterData.push({
        value: [ts, lane],
        itemStyle: { color },
        _m: m,
      });

      // Bar from now to the milestone date — represents the "runway" to it.
      // If the milestone is in the past, the bar is fully "elapsed" (drawn
      // from the lane start to the milestone).
      const barStart = ts < now.getTime() ? Math.max(xMin, ts - span * 0.08) : now.getTime();
      if (ts >= now.getTime()) {
        barData.push({
          value: [barStart, ts - barStart, lane],
          itemStyle: {
            color: isDone(m.status) ? "rgba(94,171,127,0.15)" : "rgba(251,191,36,0.12)",
          },
        });
      }
    }

    // Custom series for the Gantt bars (horizontal bars on the time axis).
    const customRender = {
      type: "custom",
      renderItem: (params: any, api: any) => {
        const start = api.coord([api.value(0), api.value(2)]);
        const end = api.coord([api.value(0) + api.value(1), api.value(2)]);
        const height = api.size([0, 1])[1] * 0.45;
        const y = start[1] - height / 2;
        const width = Math.max(2, end[0] - start[0]);
        return {
          type: "rect",
          shape: { x: start[0], y, width, height: height, r: 2 },
          style: api.visual("style"),
        };
      },
      data: barData,
      encode: { x: [0, 1], y: 2 },
    };

    const option = {
      tooltip: {
        trigger: "item",
        formatter: (p: any) => {
          const m = p.data?._m;
          if (!m) return "";
          const d = new Date(p.data.value[0]);
          const dateStr = d.toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          });
          const status = m.status ?? "pending";
          return `<div style="font-weight:600;margin-bottom:4px">${m.label ?? t("timelineGantt.unlabeled")}</div>` +
            `<div style="font-size:11px;opacity:0.8">${m.pathway ?? ""}</div>` +
            `<div style="font-size:11px;opacity:0.8">${dateStr}</div>` +
            `<div style="font-size:11px;opacity:0.8">${t("timelineGantt.status")}: ${status}</div>`;
        },
      },
      grid: {
        left: 8,
        right: 16,
        top: 16,
        bottom: 40,
        containLabel: true,
      },
      xAxis: {
        type: "time",
        min: xMin,
        max: xMax,
        axisLabel: {
          color: "#a1a8a3",
          fontSize: 10,
          formatter: (v: number) => {
            const d = new Date(v);
            return d.toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
            });
          },
        },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.04)" } },
      },
      yAxis: {
        type: "category",
        data: pathways,
        inverse: true,
        axisLabel: {
          color: "#a1a8a3",
          fontSize: 10,
          width: 80,
          overflow: "truncate",
        },
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
        axisTick: { show: false },
      },
      series: [
        customRender,
        {
          type: "scatter",
          symbolSize: 14,
          symbol: "diamond",
          data: scatterData,
          label: {
            show: true,
            position: "top",
            color: "#cbd5cb",
            fontSize: 10,
            formatter: (p: any) => {
              const label = p.data?._m?.label ?? "";
              return label.length > 14 ? label.slice(0, 13) + "…" : label;
            },
          },
          emphasis: {
            scale: 1.4,
            itemStyle: { shadowBlur: 8, shadowColor: "rgba(0,0,0,0.4)" },
          },
          z: 10,
        },
        // Today marker — a vertical line at "now".
        {
          type: "line",
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: {
              color: "#60a5fa",
              type: "dashed",
              width: 1.5,
            },
            label: {
              formatter: t("timelineGantt.today"),
              color: "#60a5fa",
              fontSize: 10,
              position: "insideEndTop",
            },
            data: [{ xAxis: now.getTime() }],
          },
          data: [],
        },
        // Target date marker — a vertical line at the goal's deadline.
        ...(targetDate
          ? [{
              type: "line" as const,
              markLine: {
                silent: true,
                symbol: "none",
                lineStyle: {
                  color: "#f87171",
                  type: "solid",
                  width: 1.5,
                },
                label: {
                  formatter: t("timelineGantt.deadline"),
                  color: "#f87171",
                  fontSize: 10,
                  position: "insideEndBottom",
                },
                data: [{ xAxis: new Date(targetDate).getTime() }],
              },
              data: [],
            }]
          : []),
      ],
    };

    return { option, hasData: true };
  }, [milestones, targetDate, t]);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <CalendarRange className="h-4 w-4 text-brand-400" />
          {t("timelineGantt.title")}
        </CardTitle>
        <CardDescription className="mt-1">
          {t("timelineGantt.subtitle")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!hasData ? (
          <div className="text-xs text-zinc-500 py-6 text-center">
            {t("timelineGantt.empty")}
          </div>
        ) : (
          <EChart
            option={option}
            height={260}
            refreshKey={`${milestones.length}-${targetDate ?? ""}`}
            aria-label={t("timelineGantt.title")}
          />
        )}
      </CardContent>
    </Card>
  );
}
