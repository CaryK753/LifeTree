"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { formatPercent } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

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
  };
  activeScenarios?: number;
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
  const p50 = successProbability?.p50 ?? successProbability?.bayesian_point;
  const p10 = successProbability?.p10;
  const p90 = successProbability?.p90;
  const pTarget = successProbability?.p_by_target_date;
  const overallRisk = successProbability?.overall_risk;

  return (
    <Card className="col-span-2">
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <span>{t("compass.title")}</span>
            <Badge variant="risk" riskLevel={status === "active" ? "low" : "medium"}>
              {status ?? "draft"}
            </Badge>
          </CardTitle>
          <CardDescription className="mt-1.5 text-sm text-zinc-300">
            {title}
          </CardDescription>
        </div>
        <div className="text-right text-xs text-zinc-500">
          {scenario && <div>{t("compass.scenario", { value: scenario })}</div>}
          {targetDate && <div>{t("compass.targetDate", { value: targetDate })}</div>}
          <div>{t("compass.activeBranches", { n: activeScenarios })}</div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-6">
          <div className="space-y-2">
            <div className="text-xs text-zinc-500">{t("compass.p50")}</div>
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
  );
}
