"use client";

import { Activity, Calendar, CheckCircle2, Pencil, Play, Tag } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { useT } from "@/lib/i18n/provider";
import type { GoalStatus } from "@/lib/api";

export function GoalWorkspaceHeader({
  title,
  scenario,
  status,
  targetDate,
  busy,
  onStatusChange,
  onEdit,
}: {
  title: string;
  scenario?: string;
  status?: GoalStatus;
  targetDate?: string;
  busy: boolean;
  onStatusChange: (status: GoalStatus) => void;
  onEdit: () => void;
}) {
  const t = useT();
  const statusRisk =
    status === "active" || status === "achieved"
      ? "low"
      : status === "paused" || status === "draft"
        ? "medium"
        : "high";

  return (
    <header className="space-y-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
          <SidebarToggleButton />
          {title}
        </h1>
        <div className="flex items-center gap-2 shrink-0">
          {status && status !== "achieved" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onStatusChange("achieved")}
              disabled={busy}
              title={t("goal.edit.markAchieved")}
            >
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              {t("goal.edit.markAchieved")}
            </Button>
          )}
          {status === "achieved" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onStatusChange("active")}
              disabled={busy}
              title={t("goal.edit.markActive")}
            >
              <Play className="h-3.5 w-3.5 mr-1" />
              {t("goal.edit.markActive")}
            </Button>
          )}
          <Button size="sm" onClick={onEdit} disabled={!status}>
            <Pencil className="h-3.5 w-3.5 mr-1" />
            {t("goal.edit.title")}
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-3 flex-wrap text-xs text-zinc-500 dark:text-zinc-400">
        {scenario && (
          <span className="inline-flex items-center gap-1">
            <Tag className="h-3 w-3" />
            {scenario}
          </span>
        )}
        {status && (
          <Badge variant="risk" riskLevel={statusRisk} className="text-[10px]">
            <Activity className="h-2.5 w-2.5 mr-0.5" />
            {t(`status.${status}`)}
          </Badge>
        )}
        {targetDate && (
          <span className="inline-flex items-center gap-1">
            <Calendar className="h-3 w-3" />
            {targetDate}
          </span>
        )}
      </div>
    </header>
  );
}
