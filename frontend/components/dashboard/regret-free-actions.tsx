"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Compass,
  ShieldCheck,
  AlertTriangle,
  ArrowRightCircle,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import type { RegretFreeAction } from "@/lib/api";

/**
 * §5 收敛性建议 — 在复杂概率分析之上，始终给出一个明确的"无悔行动"序列。
 *
 * Shows the heuristic optimal_action_sequence from the Monte Carlo simulator
 * (address highest-impact missing requirements first, then mitigate top
 * high-level risk factors), plus a plain-language explanation from the
 * Bayesian estimator.
 */
export function RegretFreeActions({
  actions,
  explanation,
  iterations,
  medianTimeMonths,
}: {
  actions: RegretFreeAction[];
  explanation?: string | null;
  iterations?: number | null;
  medianTimeMonths?: number | null;
}) {
  const t = useT();
  const hasActions = actions.length > 0;
  const hasExplanation = !!explanation;

  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Compass className="h-4 w-4 text-brand-400" />
              {t("regretFree.title")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("regretFree.subtitle")}
            </CardDescription>
          </div>
          {iterations != null && (
            <Badge variant="default" className="text-[10px] shrink-0">
              {t("regretFree.simulations", { n: iterations.toLocaleString() })}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {medianTimeMonths != null && (
          <div className="text-[11px] text-zinc-500 flex items-center gap-1.5">
            <Info className="h-3 w-3" />
            {t("regretFree.medianTime")}
            <span className="text-zinc-300 font-medium">
              {t("regretFree.months", { n: medianTimeMonths.toFixed(1) })}
            </span>
          </div>
        )}

        {hasActions ? (
          <ol className="space-y-2">
            {actions.map((a, i) => (
              <ActionRow key={`${i}-${a.name}`} index={i} action={a} />
            ))}
          </ol>
        ) : (
          <div className="text-xs text-zinc-500 py-3 text-center">
            {t("regretFree.empty")}
          </div>
        )}

        {hasExplanation && (
          <div className="mt-3 pt-3 border-t border-white/5">
            <div className="text-[10px] text-zinc-600 uppercase tracking-wide mb-1">
              {t("regretFree.reasoning")}
            </div>
            <p className="text-[11px] text-zinc-400 leading-relaxed">
              {explanation}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ActionRow({
  index,
  action,
}: {
  index: number;
  action: RegretFreeAction;
}) {
  const isRisk = !!action.risk_factor_id;
  const Icon = isRisk ? AlertTriangle : ShieldCheck;
  const toneCls = isRisk
    ? "border-amber-500/30 bg-amber-500/[0.07] text-amber-300"
    : "border-brand-500/30 bg-brand-500/[0.07] text-brand-300";

  return (
    <li className="flex items-start gap-2.5">
      <span
        className={cn(
          "shrink-0 mt-0.5 h-6 w-6 rounded-md flex items-center justify-center border text-[11px] font-semibold",
          toneCls
        )}
      >
        {index + 1}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <Icon
            className={cn(
              "h-3 w-3 shrink-0",
              isRisk ? "text-amber-400" : "text-brand-400"
            )}
          />
          <span className="text-sm font-medium text-zinc-200 truncate">
            {action.name}
          </span>
        </div>
        <p className="text-[11px] text-zinc-500 mt-0.5 leading-relaxed">
          {action.action}
        </p>
      </div>
      <ArrowRightCircle className="h-3.5 w-3.5 text-zinc-600 shrink-0 mt-1" />
    </li>
  );
}
