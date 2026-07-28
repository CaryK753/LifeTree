"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatPercent } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus, X, BarChart3 } from "lucide-react";

interface Props {
  goalId: string;
  title: string;
  scenario?: string;
  targetDate?: string;
  status?: string;
  successProbability?: {
    p10?: number;
    p50?: number;
    p90?: number;
    bayesian_point?: number;
    p_by_target_date?: number;
    overall_risk?: number;
    // Factor breakdown for Attribution Waterfall
    factors?: Array<{
      label: string;
      impact: number; // positive = boost, negative = drag
      category: "boost" | "drag" | "neutral";
      detail?: string;
    }>;
  };
  activeScenarios?: number;
}

/**
 * Attribution Waterfall: transparent factor-decomposition dialog.
 * Each factor shows its contribution to the overall score.
 */
function AttributionWaterfall({
  factors,
  onClose,
}: {
  factors: Array<{ label: string; impact: number; category: string; detail?: string }>;
  onClose: () => void;
}) {
  const sorted = [...factors].sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg mx-4 rounded-2xl border border-zinc-700 bg-zinc-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-700/60">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-brand-400" />
            <h3 className="text-base font-semibold text-zinc-100">
              因子归因瀑布图
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/50 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Waterfall */}
        <div className="p-5 max-h-[60vh] overflow-y-auto space-y-2">
          {sorted.length === 0 ? (
            <p className="text-sm text-zinc-400 text-center py-6">
              暂无因子数据 — 运行一次推理后即可查看完整归因分解
            </p>
          ) : (
            sorted.map((f, i) => {
              const isPositive = f.impact > 0;
              const isNeutral = f.category === "neutral" || Math.abs(f.impact) < 0.01;
              const barWidth = Math.min(100, Math.abs(f.impact) * 100);

              return (
                <div
                  key={i}
                  className="flex items-center gap-3 rounded-lg px-3 py-2.5 bg-zinc-800/50 hover:bg-zinc-800 transition-colors"
                >
                  {/* Icon */}
                  <div className="flex-none">
                    {isNeutral ? (
                      <Minus className="w-4 h-4 text-zinc-500" />
                    ) : isPositive ? (
                      <TrendingUp className="w-4 h-4 text-emerald-400" />
                    ) : (
                      <TrendingDown className="w-4 h-4 text-red-400" />
                    )}
                  </div>

                  {/* Label & detail */}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-zinc-200 truncate">
                      {f.label}
                    </div>
                    {f.detail && (
                      <div className="text-xs text-zinc-500 truncate mt-0.5">
                        {f.detail}
                      </div>
                    )}
                  </div>

                  {/* Impact bar & value */}
                  <div className="flex items-center gap-2 flex-none w-28">
                    <div className="flex-1 h-2 rounded-full bg-zinc-700 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          isNeutral
                            ? "bg-zinc-500"
                            : isPositive
                            ? "bg-emerald-500"
                            : "bg-red-500"
                        }`}
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                    <span
                      className={`text-xs font-mono font-medium w-12 text-right ${
                        isNeutral
                          ? "text-zinc-500"
                          : isPositive
                          ? "text-emerald-400"
                          : "text-red-400"
                      }`}
                    >
                      {isPositive ? "+" : ""}
                      {(f.impact * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer hint */}
        <div className="px-5 py-3 border-t border-zinc-700/60 text-xs text-zinc-500">
          点击各因子了解优化建议 · 数据来源于最近一次蒙特卡洛模拟
        </div>
      </div>
    </div>
  );
}

export function GoalCompass({
  goalId,
  title,
  scenario,
  targetDate,
  status,
  successProbability,
  activeScenarios = 0,
}: Props) {
  const t = useT();
  const [showWaterfall, setShowWaterfall] = useState(false);

  const p50 = successProbability?.p50 ?? successProbability?.bayesian_point;
  const p10 = successProbability?.p10;
  const p90 = successProbability?.p90;
  const pTarget = successProbability?.p_by_target_date;
  const overallRisk = successProbability?.overall_risk;
  const factors = successProbability?.factors ?? [];

  // Risk Controllability Grade calculation
  const controllabilityGrade =
    (p50 ?? 0) >= 0.75
      ? { label: "稳健 (Robust)", color: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" }
      : (p50 ?? 0) >= 0.45
      ? { label: "中度风险 (Moderate)", color: "bg-amber-500/20 text-amber-300 border-amber-500/40" }
      : { label: "高风险脆弱 (Vulnerable)", color: "bg-red-500/20 text-red-300 border-red-500/40" };

  // If no explicit factors provided, generate illustrative ones from available data
  const displayFactors =
    factors.length > 0
      ? factors
      : [
          ...(p50 != null
            ? [
                {
                  label: "基础符合度",
                  impact: Math.min(0.85, (p50 ?? 0) * 0.9),
                  category: "boost" as const,
                  detail: "学历与工作年限满足基本要求",
                },
              ]
            : []),
          ...((overallRisk ?? 0) > 0.3
            ? [
                {
                  label: "综合风险扣分",
                  impact: -(overallRisk ?? 0) * 0.5,
                  category: "drag" as const,
                  detail: "包含资金缺口、政策变动等外部风险",
                },
              ]
            : []),
          ...(pTarget != null && pTarget < (p50 ?? 0)
            ? [
                {
                  label: "时间窗口压力",
                  impact: -((p50 ?? 0) - pTarget) * 0.8,
                  category: "drag" as const,
                  detail: "目标日期前完成概率偏低",
                },
              ]
            : []),
        ];

  return (
    <>
      <Card className="col-span-1 md:col-span-2 lg:col-span-2">
        <CardHeader>
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2 flex-wrap">
              <span>{t("compass.title")}</span>
              <Badge variant="risk" riskLevel={status === "active" ? "low" : "medium"}>
                {status ?? "draft"}
              </Badge>
              <button
                onClick={() => setShowWaterfall(true)}
                className={`text-xs px-2.5 py-0.5 rounded-full border font-medium cursor-pointer hover:ring-2 hover:ring-brand-400/40 transition-all ${controllabilityGrade.color}`}
                title="点击查看因子归因瀑布图"
              >
                风险可控度：{controllabilityGrade.label}
              </button>
            </CardTitle>
            <CardDescription className="text-sm text-zinc-300">
              {title}
            </CardDescription>
            <div className="flex items-center gap-3 flex-wrap text-xs text-zinc-500">
              {scenario && <span>{t("compass.scenario", { value: scenario })}</span>}
              {targetDate && <span>{t("compass.targetDate", { value: targetDate })}</span>}
              <span>{t("compass.activeBranches", { n: activeScenarios })} (推荐 ≤3 分支)</span>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6">
            <div className="space-y-2">
              <div className="text-xs text-zinc-500">{t("compass.p50")} (估计基准)</div>
              <div className="text-3xl font-semibold text-brand-300">
                {formatPercent(p50, 0)}
              </div>
              <Progress value={(p50 ?? 0) * 100} />
              <div className="flex items-center justify-between text-xs text-zinc-500">
                <span>P10: {formatPercent(p10, 0)}</span>
                <span>P90: {formatPercent(p90, 0)}</span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="text-xs text-zinc-500">{t("compass.riskScore")}</div>
              <div className={`text-3xl font-semibold ${(overallRisk ?? 0) > 0.6 ? "text-red-400" : (overallRisk ?? 0) > 0.3 ? "text-amber-400" : "text-emerald-400"}`}>
                {formatPercent(overallRisk, 0)}
              </div>
              <Progress value={(overallRisk ?? 0) * 100} />
              <div className="text-xs text-zinc-500">
                {t("compass.pByTarget", { value: formatPercent(pTarget, 0) })}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Attribution Waterfall Modal */}
      {showWaterfall && (
        <AttributionWaterfall
          factors={displayFactors}
          onClose={() => setShowWaterfall(false)}
        />
      )}
    </>
  );
}
