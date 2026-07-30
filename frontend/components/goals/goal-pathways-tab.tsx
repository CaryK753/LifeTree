"use client";

import { CheckCircle2, ListTodo } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

export function GoalPathwaysTab({
  pathways,
  activePathway,
  requirements,
  onSelect,
}: {
  pathways: any[];
  activePathway?: string;
  requirements: any[];
  onSelect: (id: string) => void;
}) {
  const t = useT();
  const statusLabel = (status?: string) => (status ? t(`status.${status}`) : "—");
  const gapLabel = (gap?: string) => (gap ? t(`gap.${gap}`) : "—");

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 min-h-[60vh]">
      <div className="space-y-3">
        <span className="text-xs text-zinc-500 dark:text-zinc-400">
          {t("scenarios.pathwayCount", { n: pathways.length })}
        </span>
        <div className="space-y-2 lg:max-h-[70vh] lg:overflow-y-auto lg:pr-1">
          {pathways.map((pathway) => {
            const selected = activePathway === pathway.id;
            return (
              <Card
                key={pathway.id}
                className={cn(
                  "cursor-pointer transition-colors",
                  selected
                    ? "border-brand-500/50 ring-1 ring-brand-500/20"
                    : "hover:border-brand-500/30"
                )}
                onClick={() => onSelect(pathway.id)}
              >
                <CardHeader className="p-3">
                  <CardTitle className="text-sm flex items-center gap-1.5">
                    {selected && <CheckCircle2 className="h-3.5 w-3.5 text-brand-500" />}
                    <span className="truncate">{pathway.name}</span>
                  </CardTitle>
                  <CardDescription>
                    {pathway.region || "—"} · {statusLabel(pathway.status)}
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-3 pt-0 text-xs text-zinc-500 dark:text-zinc-400">
                  {t("goalDetail.requirements.count", {
                    n: pathway.requirements?.length ?? "?",
                  })}
                </CardContent>
              </Card>
            );
          })}
          {pathways.length === 0 && <EmptyRequirements />}
        </div>
      </div>

      <Card className="min-h-[60vh]">
        <CardHeader>
          <CardTitle className="text-base">{t("goalDetail.requirements.title")}</CardTitle>
          <CardDescription>{t("goalDetail.requirements.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          {activePathway ? (
            <div className="space-y-2">
              {requirements.map((requirement) => (
                <div
                  key={requirement.id}
                  className="flex flex-col sm:grid sm:grid-cols-[1fr_auto_auto] gap-2 sm:gap-3 sm:items-center py-2 border-b border-black/5 dark:border-white/5 last:border-0"
                >
                  <div>
                    <div className="text-sm text-zinc-800 dark:text-zinc-200">{requirement.name}</div>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {requirement.type}{requirement.description ? ` · ${requirement.description}` : ""}
                    </div>
                  </div>
                  <Badge variant="risk" riskLevel={gapRisk(requirement.gap_status)}>
                    {gapLabel(requirement.gap_status)}
                  </Badge>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 sm:text-right min-w-[60px]">
                    <div>{t("goalDetail.requirements.weight")} {requirement.weight ?? "—"}</div>
                    {requirement.gap_delta != null && (
                      <div className={requirement.gap_delta < 0 ? "text-red-500" : "text-emerald-500"}>
                        {t("goalDetail.requirements.gap")} {requirement.gap_delta > 0 ? "+" : ""}{requirement.gap_delta}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {requirements.length === 0 && <EmptyRequirements />}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
              <ListTodo className="h-8 w-8 text-zinc-400 opacity-50" />
              <p className="text-sm font-medium">{t("scenarios.noPathwaySelected")}</p>
              <p className="text-xs text-zinc-500 max-w-sm">{t("scenarios.noPathwaySelectedHint")}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function gapRisk(status?: string): "low" | "medium" | "high" {
  if (status === "met") return "low";
  if (status === "missing") return "high";
  return "medium";
}

function EmptyRequirements() {
  const t = useT();
  return <div className="py-8 text-center text-xs text-zinc-500">{t("goalDetail.requirements.empty")}</div>;
}
