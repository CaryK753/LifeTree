"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

interface RiskItem {
  type: string;
  level: "low" | "medium" | "high";
  count: number;
}

interface Props {
  risks: RiskItem[];
}

const RISK_COLORS: Record<string, string> = {
  high: "bg-red-500/70",
  medium: "bg-amber-500/70",
  low: "bg-emerald-500/70",
};

export function RiskHeatmap({ risks }: Props) {
  const t = useT();
  const types = Array.from(new Set(risks.map((r) => r.type)));
  if (types.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("riskHeatmap.title")}</CardTitle>
          <CardDescription>{t("riskHeatmap.empty")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("riskHeatmap.title")}</CardTitle>
        <CardDescription>{t("riskHeatmap.subtitle")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {types.map((type) => {
            const items = risks.filter((r) => r.type === type);
            const total = items.reduce((s, r) => s + r.count, 0);
            return (
              <div key={type} className="grid grid-cols-[120px_1fr_60px] items-center gap-3 text-xs">
                <span className="text-zinc-400 capitalize">{type}</span>
                <div className="flex gap-1 h-6">
                  {items.map((r) => (
                    <div
                      key={r.level}
                      title={`${type} · ${r.level}: ${r.count}`}
                      className={cn(
                        "flex-1 rounded-sm flex items-center justify-center text-[10px] font-semibold text-white",
                        RISK_COLORS[r.level] || "bg-white/10"
                      )}
                      style={{ flexGrow: r.count }}
                    >
                      {r.count > 0 ? r.count : ""}
                    </div>
                  ))}
                </div>
                <span className="text-zinc-500 text-right">{total}</span>
              </div>
            );
          })}
        </div>
        <div className="mt-4 flex items-center gap-3 text-[10px] text-zinc-500">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-red-500/70" />{t("riskHeatmap.high")}</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-amber-500/70" />{t("riskHeatmap.medium")}</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-emerald-500/70" />{t("riskHeatmap.low")}</span>
        </div>
      </CardContent>
    </Card>
  );
}
