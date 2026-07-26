"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { formatPercent } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

interface Credibility {
  high: number;
  medium: number;
  low: number;
  pending: number;
  user_marked_reliable: number;
  user_marked_questionable: number;
  total: number;
  private_share: number;
}

export function CredibilityMeter({ credibility }: { credibility?: Credibility }) {
  const t = useT();
  const c = credibility ?? {
    high: 0, medium: 0, low: 0, pending: 0,
    user_marked_reliable: 0, user_marked_questionable: 0,
    total: 0, private_share: 0,
  };
  const total = c.total || 1;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("credibility.title")}</CardTitle>
        <CardDescription>
          {t("credibility.summary", {
            total: c.total,
            share: formatPercent(c.private_share, 0),
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Bar label={t("credibility.high")} value={c.high} total={total} color="bg-emerald-500" />
        <Bar label={t("credibility.medium")} value={c.medium} total={total} color="bg-amber-500" />
        <Bar label={t("credibility.low")} value={c.low} total={total} color="bg-red-500" />
        <Bar label={t("credibility.pending")} value={c.pending} total={total} color="bg-zinc-500" />
        <Bar label={t("credibility.userReliable")} value={c.user_marked_reliable} total={total} color="bg-brand-500" />
        <Bar label={t("credibility.userQuestionable")} value={c.user_marked_questionable} total={total} color="bg-orange-500" />

        {c.private_share > 0.4 && (
          <div className="mt-3 rounded-md bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-200">
            {t("credibility.privateWarn")}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Bar({
  label, value, total, color,
}: { label: string; value: number; total: number; color: string }) {
  const pct = (value / total) * 100;
  return (
    <div>
      <div className="flex justify-between text-xs text-zinc-600 dark:text-zinc-400 mb-1">
        <span>{label}</span>
        <span>{value}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-black/5 dark:bg-white/5 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
