"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { useT } from "@/lib/i18n/provider";

interface Milestone {
  label?: string;
  due?: string;
  status?: string;
  pathway?: string;
}

interface Props {
  milestones: Milestone[];
}

const STATUS_TO_PCT: Record<string, number> = {
  done: 100,
  complete: 100,
  completed: 100,
  met: 100,
  in_progress: 50,
  pending: 10,
  not_started: 0,
};

export function Milestones({ milestones }: Props) {
  const t = useT();
  const completed = milestones.filter((m) => (m.status ?? "").match(/done|complete|met/i)).length;
  const pct = milestones.length > 0 ? (completed / milestones.length) * 100 : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("milestones.title")}</CardTitle>
        <CardDescription>
          {t("milestones.completed", { done: completed, total: milestones.length })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Progress value={pct} className="mb-4" />
        <div className="space-y-2">
          {milestones.map((m, i) => {
            const sp = STATUS_TO_PCT[(m.status ?? "pending").toLowerCase()] ?? 10;
            return (
              <div
                key={i}
                className="grid grid-cols-[1fr_auto] items-center gap-3 text-xs"
              >
                <div className="min-w-0">
                  <div className="text-zinc-200 truncate">{m.label}</div>
                  <div className="text-[10px] text-zinc-500 mt-0.5">
                    {m.pathway && <span>{m.pathway} · </span>}
                    {m.due && <span>{t("milestones.due", { date: m.due })}</span>}
                  </div>
                </div>
                <Badge
                  variant="risk"
                  riskLevel={
                    m.status?.match(/done|complete|met/i) ? "low"
                    : m.status?.match(/in_progress/i) ? "medium"
                    : "high"
                  }
                >
                  {m.status ?? "pending"}
                </Badge>
              </div>
            );
          })}
          {milestones.length === 0 && (
            <div className="text-xs text-zinc-500 text-center py-4">
              {t("milestones.empty")}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
