"use client";

import { useEffect, useRef, useState, memo } from "react";
import dynamic from "next/dynamic";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

/**
 * ECharts is a large client-side library, so we load it lazily via dynamic
 * import (SSR-disabled). The wrapper below is what consumers import directly.
 */
const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => <ChartSkeleton />,
});

interface EChartProps {
  option: Record<string, unknown>;
  height?: number | string;
  className?: string;
  /** Force a re-render of the chart when this value changes. */
  refreshKey?: string | number;
}

/**
 * Thin wrapper around echarts-for-react that:
 *   - merges a dark, brand-aligned theme
 *   - enables enter animations (animationDuration / animationEasing)
 *   - shows a fade-in skeleton while the lib loads
 *   - resizes the chart on container resize (ResizeObserver)
 */
function EChartImpl({ option, height = 280, className, refreshKey }: EChartProps) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const [instance, setInstance] = useState<any>(null);
  const [visible, setVisible] = useState(false);

  // Trigger fade-in once mounted.
  useEffect(() => {
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, []);

  // Resize observer — keeps the chart responsive.
  useEffect(() => {
    if (!ref.current || !instance) return;
    const ro = new ResizeObserver(() => {
      instance.resize();
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [instance]);

  const merged = mergeTheme(option);

  return (
    <div
      ref={ref}
      className={cn(
        "relative rounded-md overflow-hidden transition-opacity duration-300",
        visible ? "opacity-100" : "opacity-0",
        className
      )}
      style={{ height: typeof height === "number" ? `${height}px` : height }}
      role="img"
      aria-label={t("chart.render")}
    >
      <ReactECharts
        // echarts-for-react exposes the instance via onChartReady
        onChartReady={(inst: any) => setInstance(inst)}
        option={merged}
        notMerge={true}
        lazyUpdate={true}
        style={{ width: "100%", height: "100%" }}
        opts={{ renderer: "svg" }}
      />
    </div>
  );
}

export const EChart = memo(EChartImpl);

// ---------- Theme ----------

function mergeTheme(option: Record<string, unknown>): Record<string, unknown> {
  const base = {
    animation: true,
    animationDuration: 800,
    animationDurationUpdate: 400,
    animationEasing: "cubicOut",
    animationEasingUpdate: "cubicOut",
    textStyle: {
      color: "#cbd5cb",
      fontFamily:
        'var(--font-inter), system-ui, -apple-system, sans-serif',
    },
    backgroundColor: "transparent",
    grid: {
      left: 36,
      right: 16,
      top: 28,
      bottom: 28,
      containLabel: true,
    },
    legend: {
      textStyle: { color: "#a1a8a3" },
      inactiveColor: "#3f463e",
    },
    tooltip: {
      backgroundColor: "rgba(15, 20, 16, 0.95)",
      borderColor: "rgba(255, 255, 255, 0.1)",
      borderWidth: 1,
      textStyle: { color: "#e6e9e6", fontSize: 12 },
      extraCssText: "backdrop-filter: blur(6px); border-radius: 8px;",
    },
    xAxis: {
      axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
      axisLabel: { color: "#a1a8a3", fontSize: 11 },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.04)" } },
    },
    yAxis: {
      axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
      axisLabel: { color: "#a1a8a3", fontSize: 11 },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } },
    },
    color: [
      "#5eab7f",
      "#8fcaa6",
      "#3b8d61",
      "#bbe1c9",
      "#fbbf24",
      "#f87171",
      "#60a5fa",
      "#c084fc",
    ],
  };
  return { ...base, ...option, ...mergeDeep(base, option) };
}

function mergeDeep(a: any, b: any): any {
  if (!b) return a;
  const out: any = { ...a };
  for (const k of Object.keys(b)) {
    if (
      a &&
      typeof a[k] === "object" &&
      !Array.isArray(a[k]) &&
      typeof b[k] === "object" &&
      !Array.isArray(b[k])
    ) {
      out[k] = mergeDeep(a[k], b[k]);
    }
  }
  return out;
}

function ChartSkeleton() {
  return (
    <div className="h-full w-full flex items-center justify-center text-xs text-zinc-600">
      <span className="animate-pulse">Loading chart…</span>
    </div>
  );
}

// ---------- Animated table ----------

interface TableColumn {
  key: string;
  label: string;
  align?: "left" | "right" | "center";
}

interface AnimatedTableProps {
  columns: TableColumn[];
  rows: Array<Record<string, unknown>>;
  className?: string;
  /** Per-row stagger delay in ms. */
  stagger?: number;
}

/**
 * Stagger-animated table for use inside chat bubbles and dashboard cards.
 * Each row fades in with a tiny upward translate, creating a "data unfolding"
 * effect that draws the eye without being distracting.
 */
export function AnimatedTable({
  columns,
  rows,
  className,
  stagger = 40,
}: AnimatedTableProps) {
  const [visibleCount, setVisibleCount] = useState(0);

  useEffect(() => {
    setVisibleCount(0);
    let raf = 0;
    let i = 0;
    const tick = () => {
      i += 1;
      setVisibleCount(i);
      if (i < rows.length) {
        raf = window.setTimeout(tick, stagger) as unknown as number;
      }
    };
    raf = window.setTimeout(tick, stagger) as unknown as number;
    return () => window.clearTimeout(raf);
  }, [rows, stagger]);

  return (
    <div className={cn("overflow-x-auto rounded-md border border-white/5", className)}>
      <table className="min-w-full text-xs">
        <thead className="bg-white/[0.03]">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "px-2.5 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-zinc-400 border-b border-white/5",
                  c.align === "right"
                    ? "text-right"
                    : c.align === "center"
                    ? "text-center"
                    : "text-left"
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, visibleCount).map((row, i) => (
            <tr
              key={i}
              className="border-b border-white/[0.03] last:border-b-0 animate-fade-in"
              style={{ animationDuration: "240ms" }}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "px-2.5 py-1.5 text-zinc-200",
                    c.align === "right"
                      ? "text-right tabular-nums"
                      : c.align === "center"
                      ? "text-center"
                      : "text-left"
                  )}
                >
                  {formatCell(row[c.key])}
                </td>
              ))}
            </tr>
          ))}
          {visibleCount < rows.length && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-2.5 py-2 text-center text-[10px] text-zinc-600"
              >
                <span className="inline-flex gap-1">
                  <span className="h-1 w-1 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="h-1 w-1 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: "120ms" }} />
                  <span className="h-1 w-1 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: "240ms" }} />
                </span>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : v.toFixed(2);
  }
  if (typeof v === "boolean") return v ? "✓" : "✗";
  return String(v);
}

// ---------- Inline numeric badge ----------

interface TrendBadgeProps {
  value: number;
  threshold?: number;
}

/**
 * Tiny inline badge for percentage / score values. Color shifts with the
 * threshold so it works as a "good / warn / bad" indicator inside chat text.
 */
export function TrendBadge({ value, threshold = 0.5 }: TrendBadgeProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const tone =
    value >= threshold + 0.15
      ? "text-emerald-300 bg-emerald-500/10 border-emerald-500/30"
      : value >= threshold - 0.1
      ? "text-amber-300 bg-amber-500/10 border-amber-500/30"
      : "text-red-300 bg-red-500/10 border-red-500/30";
  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border tabular-nums",
        tone
      )}
    >
      {pct.toFixed(0)}%
    </span>
  );
}
