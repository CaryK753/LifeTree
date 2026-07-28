"use client";

/**
 * UseModeCard — toggle between single-user and multi-user mode.
 *
 * In single-user mode anyone (including the default-user fallback) can
 * switch — there's only one user, so they're effectively the admin. In
 * multi-user mode only admins can switch.
 *
 * Lives on the /admin page alongside other platform-level configuration
 * (providers, models, SMTP, OAuth providers, auth settings).
 */

import { useState } from "react";
import { useAuth, useAuthConfig } from "@/lib/hooks";
import { api } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Loader2, UserCog } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

export function UseModeCard() {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { isAdmin } = useAuth();
  const { data: authConfig, mutate } = useAuthConfig();
  const [switching, setSwitching] = useState<"single" | "multi" | null>(null);

  const currentMode = authConfig?.use_mode ?? "single";
  const canSwitch = isAdmin || currentMode === "single";

  async function handleSwitch(target: "single" | "multi") {
    if (target === currentMode) return;
    if (!canSwitch) {
      toast({
        title: t("settings.useMode.adminOnly"),
        variant: "error",
      });
      return;
    }
    const ok = await confirm({
      title: t("settings.useMode.confirmTitle"),
      description:
        target === "single"
          ? t("settings.useMode.confirmSingle")
          : t("settings.useMode.confirmMulti"),
      confirmLabel: t("settings.useMode.switch", {
        mode: target === "single" ? t("settings.useMode.single.label") : t("settings.useMode.multi.label"),
      }),
      cancelLabel: t("common.cancel"),
      variant: "default",
    });
    if (!ok) return;

    setSwitching(target);
    try {
      await api.setUseMode(target);
      await mutate();
      toast({
        title: t("settings.useMode.switched", {
          mode: target === "single" ? t("settings.useMode.single.label") : t("settings.useMode.multi.label"),
        }),
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSwitching(null);
    }
  }

  const currentLabel =
    currentMode === "single"
      ? t("settings.useMode.single.label")
      : t("settings.useMode.multi.label");

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <UserCog className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.useMode.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.useMode.hint")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-zinc-500 dark:text-zinc-400">
            {t("settings.useMode.current", { mode: currentLabel })}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(["single", "multi"] as const).map((mode) => {
            const active = mode === currentMode;
            const label =
              mode === "single"
                ? t("settings.useMode.single.label")
                : t("settings.useMode.multi.label");
            const desc =
              mode === "single"
                ? t("settings.useMode.single.desc")
                : t("settings.useMode.multi.desc");
            const loading = switching === mode;
            return (
              <button
                key={mode}
                type="button"
                disabled={!canSwitch || loading || active}
                onClick={() => handleSwitch(mode)}
                className={cn(
                  "flex flex-col items-start gap-1.5 px-4 py-3 rounded-md border text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  active
                    ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-200"
                    : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-700 dark:text-zinc-300 hover:border-black/20 dark:hover:border-white/20 hover:text-zinc-900 dark:hover:text-zinc-100"
                )}
              >
                <div className="flex items-center gap-2 w-full">
                  <span className="font-medium">{label}</span>
                  {active && (
                    <Badge
                      variant="default"
                      className="ml-auto text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
                    >
                      <CheckCircle2 className="h-3 w-3" />
                    </Badge>
                  )}
                  {loading && <Loader2 className="h-3.5 w-3.5 animate-spin ml-auto" />}
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-snug">
                  {desc}
                </p>
              </button>
            );
          })}
        </div>

        {!canSwitch && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            {t("settings.useMode.adminOnly")}
          </p>
        )}
      </CardContent>
      {ConfirmRoot}
    </Card>
  );
}

export default UseModeCard;
