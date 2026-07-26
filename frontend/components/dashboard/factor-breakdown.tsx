"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ShieldCheck, AlertTriangle, ChevronDown } from "lucide-react";
import { useState } from "react";
import { cn, formatPercent } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import type { FactorContribution } from "@/lib/api";

/**
 * §5 透明化 — 所有概率和预测均附解释，可下钻到原始因子。
 *
 * Renders the per-factor contribution to failure from the Bayesian noise-OR
 * model. Each row shows:
 *   - factor name + type (requirement vs risk_factor)
 *   - P(success) for this factor
 *   - contribution to overall failure (bar)
 *
 * Sorted by contribution descending — the biggest drag rises to the top.
 */
export function FactorBreakdown({
  factors,
}: {
  factors: FactorContribution[];
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const sorted = [...factors].sort(
    (a, b) => (b.contribution ?? 0) - (a.contribution ?? 0)
  );
  const visible = expanded ? sorted : sorted.slice(0, 5);
  const hiddenCount = sorted.length - visible.length;
  const maxContribution = Math.max(
    ...sorted.map((f) => f.contribution ?? 0),
    0.001
  );

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
      <CardContent>
        {visible.length === 0 ? (
          <div className="text-xs text-zinc-500 py-3 text-center">
            {t("factorBreakdown.empty")}
          </div>
        ) : (
          <ul className="space-y-2.5">
            {visible.map((f, i) => {
              const isRisk = f.type === "risk_factor";
              const contribution = f.contribution ?? 0;
              const p = f.p ?? 0;
              const barWidth = Math.max(
                2,
                Math.round((contribution / maxContribution) * 100)
              );
              return (
                <li key={`${i}-${f.name}`} className="space-y-1">
                  <div className="flex items-center gap-2 text-xs">
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
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 rounded-full bg-white/[0.04] overflow-hidden">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all",
                          isRisk ? "bg-amber-500/60" : "bg-brand-500/50"
                        )}
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-zinc-500 w-10 text-right tabular-nums">
                      {(contribution * 100).toFixed(1)}%
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {hiddenCount > 0 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-3 w-full text-[11px] text-zinc-500 hover:text-zinc-300 flex items-center justify-center gap-1 transition-colors"
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
      </CardContent>
    </Card>
  );
}
