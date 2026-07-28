"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { useSystemComponents } from "@/lib/hooks";
import { type SystemComponentView } from "@/lib/api";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  HardDrive,
  Layers,
  Loader2,
  Network,
  RefreshCw,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

/**
 * SystemComponentsCard — read-only docker services status.
 *
 * Moved from /settings to /admin per the multi-user mode separation:
 * system-level info belongs on the admin page alongside PlatformConfig,
 * UseModeCard, and other admin-only configuration cards.
 */

const KIND_ICON: Record<string, React.ReactNode> = {
  database: <Database className="h-3.5 w-3.5" />,
  graph: <Network className="h-3.5 w-3.5" />,
  cache: <Zap className="h-3.5 w-3.5" />,
  storage: <HardDrive className="h-3.5 w-3.5" />,
};

export function SystemComponentsCard() {
  const t = useT();
  const toast = useToast();
  const { data, error, isLoading, isValidating, mutate } = useSystemComponents();

  const components = data?.components ?? [];
  const availableCount = components.filter((c) => c.available).length;

  const handleRefresh = async () => {
    try {
      await mutate();
      toast({
        title: t("settings.systemComponents.title"),
        description: t("settings.systemComponents.refreshed"),
      });
    } catch {
      toast({
        title: t("settings.systemComponents.title"),
        description: t("settings.systemComponents.refreshFailed"),
        variant: "error",
      });
    }
  };

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.systemComponents.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.systemComponents.subtitle")}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-zinc-500 shrink-0">
          {components.length > 0 && (
            <Badge
              className={cn(
                "text-[10px]",
                availableCount === components.length
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
                  : availableCount === 0
                    ? "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-200"
                    : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200"
              )}
            >
              {t("settings.systemComponents.availableCount", {
                n: availableCount,
                total: components.length,
              })}
            </Badge>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-[11px] text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100 px-2"
            onClick={handleRefresh}
            disabled={isValidating}
            title={t("settings.systemComponents.refresh")}
          >
            <RefreshCw
              className={cn("h-3 w-3 mr-1", isValidating && "animate-spin")}
            />
            {t("settings.systemComponents.refresh")}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-zinc-500 leading-snug">
          {t("settings.systemComponents.hint")}
        </p>

        {isLoading ? (
          <div className="flex items-center gap-2 text-[11px] text-zinc-500 py-4 justify-center">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("settings.systemComponents.loading")}
          </div>
        ) : error ? (
          <div className="text-[11px] text-red-600 dark:text-red-300 py-3 px-3 rounded-md bg-red-500/5 border border-red-500/20">
            {(error as Error).message}
          </div>
        ) : components.length === 0 ? (
          <div className="text-[11px] text-zinc-500 py-3 text-center">—</div>
        ) : (
          <div className="space-y-2">
            {components.map((c) => (
              <ServiceRow key={c.key} component={c} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ServiceRow({ component }: { component: SystemComponentView }) {
  const t = useT();
  const kindLabel = t(`settings.systemComponents.kind.${component.kind}`);
  return (
    <div
      className={cn(
        "rounded-lg border bg-surface/30 overflow-hidden",
        component.available
          ? "border-black/10 dark:border-white/10"
          : "border-red-500/30"
      )}
    >
      <div className="flex items-center gap-3 p-3">
        {/* Icon */}
        <div
          className={cn(
            "h-9 w-9 shrink-0 rounded-md flex items-center justify-center",
            component.available
              ? "bg-brand-500/15 text-brand-700 dark:text-brand-300"
              : "bg-red-500/15 text-red-600 dark:text-red-300"
          )}
        >
          {KIND_ICON[component.kind] ?? <Layers className="h-3.5 w-3.5" />}
        </div>

        {/* Name + endpoint */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {component.name}
            </span>
            <Badge variant="default" className="text-[10px]">
              {kindLabel}
            </Badge>
            {component.enabled ? (
              <Badge className="text-[10px] border-zinc-500/30 bg-zinc-500/10 text-zinc-700 dark:text-zinc-300">
                {t("settings.systemComponents.enabled")}
              </Badge>
            ) : (
              <Badge className="text-[10px] border-zinc-400/30 dark:border-zinc-700/50 bg-zinc-200/50 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400">
                {t("settings.systemComponents.disabled")}
              </Badge>
            )}
          </div>
          <div className="mt-1 flex items-center gap-1 text-[10px] text-zinc-500 min-w-0">
            <span className="text-zinc-600 shrink-0">
              {t("settings.systemComponents.endpoint")}:
            </span>
            <span className="font-mono text-zinc-500 dark:text-zinc-400 truncate">
              {component.endpoint || "—"}
            </span>
          </div>
          {component.detail && (
            <div className="mt-0.5 flex items-center gap-1 text-[10px] text-zinc-500 min-w-0">
              <span className="text-zinc-600 shrink-0">
                {t("settings.systemComponents.detail")}:
              </span>
              <span className="text-zinc-500 dark:text-zinc-400 truncate">
                {component.detail}
              </span>
            </div>
          )}
          {!component.available && component.error && (
            <div className="mt-0.5 flex items-start gap-1 text-[10px] text-red-600 dark:text-red-300 min-w-0">
              <span className="text-red-500 shrink-0">
                {t("settings.systemComponents.error")}:
              </span>
              <span className="font-mono break-all line-clamp-2">
                {component.error}
              </span>
            </div>
          )}
        </div>

        {/* Status badge */}
        <div className="shrink-0">
          {component.available ? (
            <Badge className="text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200">
              <CheckCircle2 className="h-2.5 w-2.5 mr-0.5" />
              {t("settings.systemComponents.available")}
            </Badge>
          ) : (
            <Badge className="text-[10px] border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-200">
              <AlertTriangle className="h-2.5 w-2.5 mr-0.5" />
              {t("settings.systemComponents.unavailable")}
            </Badge>
          )}
        </div>
      </div>
    </div>
  );
}
