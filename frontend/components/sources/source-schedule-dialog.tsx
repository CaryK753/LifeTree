"use client";

import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Loader2, RefreshCw, Clock } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

interface SourceScheduleDialogProps {
  sourceId: string;
  sourceTitle: string;
  sourceUrl: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated?: () => void;
}

// Preset intervals (in minutes) shown as quick-select buttons.
const PRESETS: Array<{ label: string; minutes: number }> = [
  { label: "1m", minutes: 1 },
  { label: "5m", minutes: 5 },
  { label: "30m", minutes: 30 },
  { label: "1h", minutes: 60 },
  { label: "6h", minutes: 360 },
  { label: "12h", minutes: 720 },
  { label: "24h", minutes: 1440 },
  { label: "7d", minutes: 10080 },
];

export function SourceScheduleDialog({
  sourceId,
  sourceTitle,
  sourceUrl,
  open,
  onOpenChange,
  onUpdated,
}: SourceScheduleDialogProps) {
  const t = useT();
  const toast = useToast();
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [intervalMin, setIntervalMin] = useState(1440);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Load current schedule state when dialog opens
  useEffect(() => {
    if (!open) return;
    // Fetch the current source to get existing schedule fields
    api.listSources().then((all) => {
      const src = (all as any[])?.find((s) => s.id === sourceId);
      if (src) {
        setAutoRefresh(!!src.auto_refresh);
        setIntervalMin(src.refresh_interval_minutes ?? 1440);
      }
    });
  }, [open, sourceId]);

  const hasUrl = !!sourceUrl;

  async function handleSave() {
    setSaving(true);
    try {
      await api.updateSourceSchedule(sourceId, {
        auto_refresh: autoRefresh,
        refresh_interval_minutes: intervalMin,
      });
      toast({ title: t("sources.schedule.saved"), variant: "success" });
      onUpdated?.();
      onOpenChange(false);
    } catch (err: any) {
      toast({
        title: t("sources.schedule.saveFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleRefreshNow() {
    setRefreshing(true);
    try {
      await api.refreshSourceNow(sourceId);
      toast({ title: t("sources.schedule.refreshTriggered"), variant: "default" });
    } catch (err: any) {
      toast({
        title: t("sources.schedule.refreshFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("sources.schedule.title")}
          </DialogTitle>
          <DialogDescription className="truncate">
            {sourceTitle}
          </DialogDescription>
        </DialogHeader>

        {!hasUrl && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            {t("sources.schedule.noUrlWarning")}
          </div>
        )}

        <div className="space-y-4">
          {/* Auto-refresh toggle */}
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-0.5">
              <Label className="text-sm">{t("sources.schedule.autoRefresh")}</Label>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {t("sources.schedule.autoRefreshDesc")}
              </p>
            </div>
            <Switch
              checked={autoRefresh}
              onCheckedChange={setAutoRefresh}
              disabled={!hasUrl}
            />
          </div>

          {/* Interval presets */}
          {autoRefresh && hasUrl && (
            <div className="space-y-2">
              <Label className="text-xs">{t("sources.schedule.interval")}</Label>
              <div className="flex flex-wrap gap-1.5">
                {PRESETS.map((p) => (
                  <button
                    key={p.minutes}
                    type="button"
                    onClick={() => setIntervalMin(p.minutes)}
                    className={cn(
                      "px-2.5 py-1 rounded-md border text-xs font-medium transition-colors",
                      intervalMin === p.minutes
                        ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-300"
                        : "border-black/5 dark:border-white/5 text-zinc-500 dark:text-zinc-400 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]"
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              {/* Custom interval input */}
              <div className="flex items-center gap-2 mt-2">
                <Label className="text-xs whitespace-nowrap">{t("sources.schedule.custom")}</Label>
                <Input
                  type="number"
                  min={1}
                  max={525600}
                  value={intervalMin}
                  onChange={(e) => setIntervalMin(Math.max(1, parseInt(e.target.value) || 1))}
                  className="h-8 w-24 text-xs"
                />
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  {t("sources.schedule.minutes")}
                </span>
              </div>
            </div>
          )}

          {/* Manual refresh button */}
          {hasUrl && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefreshNow}
              disabled={refreshing}
              className="w-full"
            >
              {refreshing ? (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
              )}
              {t("sources.schedule.refreshNow")}
            </Button>
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button size="sm" variant="ghost">{t("common.cancel")}</Button>
          </DialogClose>
          <Button size="sm" onClick={handleSave} disabled={saving || (autoRefresh && !hasUrl)}>
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
            ) : null}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
