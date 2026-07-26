"use client";

import { useEffect, useMemo, useState } from "react";
import { useAuth, useAuthConfig, useSettings, useSystemComponents } from "@/lib/hooks";
import {
  api,
  type AboutInfo,
  type SystemComponentView,
  type UpdateCheck,
  ALL_ROLES,
} from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { ThemeCard } from "@/components/theme/theme-card";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  Github,
  Globe,
  HardDrive,
  Info,
  Layers,
  Loader2,
  Network,
  RefreshCw,
  Sparkles,
  UserCog,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { LOCALES, LOCALE_LABELS, LOCALE_NAMES, type Locale } from "@/lib/i18n/messages";
import { useI18n } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { PlatformConfig } from "@/components/settings/platform-config";

export default function SettingsPage() {
  const { data: settings } = useSettings();
  const t = useT();
  const { isAdmin } = useAuth();

  const rolesConfigured = useMemo(() => {
    if (!settings) return 0;
    return ALL_ROLES.filter((r) => settings.roles_configured[r]).length;
  }, [settings]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 w-full max-w-[1600px] mx-auto">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <Sparkles className="h-6 w-6 text-brand-600 dark:text-brand-400" />
            {t("settings.title")}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">
            {t("settings.subtitle")}
          </p>
        </div>
        <Badge
          variant="default"
          className={
            rolesConfigured === ALL_ROLES.length
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
              : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200"
          }
        >
          {t("settings.rolesReady", { n: rolesConfigured, total: ALL_ROLES.length })}
        </Badge>
      </header>

      {isAdmin && <PlatformConfig />}

      {/* ---------- System Components (read-only docker services) ---------- */}
      <SystemComponentsCard />

      {/* ---------- Use Mode (single / multi-user) ---------- */}
      <UseModeCard />

      {/* ---------- Theme ---------- */}
      <ThemeCard />

      {/* ---------- Language ---------- */}
      <LanguageCard />

      {/* ---------- About ---------- */}
      <AboutCard />
    </div>
  );
}

// ============== System Components (read-only docker services) ==============

const KIND_ICON: Record<string, React.ReactNode> = {
  database: <Database className="h-3.5 w-3.5" />,
  graph: <Network className="h-3.5 w-3.5" />,
  cache: <Zap className="h-3.5 w-3.5" />,
  storage: <HardDrive className="h-3.5 w-3.5" />,
};

function SystemComponentsCard() {
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

// ============== Use Mode Card ==============

function UseModeCard() {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { isAdmin } = useAuth();
  const { data: authConfig, mutate } = useAuthConfig();
  const [switching, setSwitching] = useState<"single" | "multi" | null>(null);

  const currentMode = authConfig?.use_mode ?? "single";
  // In single-user mode anyone (including the default-user fallback) can
  // switch — there's only one user, so they're effectively the admin. In
  // multi-user mode only admins can switch.
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

// ============== Language Card ==============

function LanguageCard() {
  const t = useT();
  const { locale, setLocale } = useI18n();
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.language.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.language.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-zinc-500 dark:text-zinc-400">{t("settings.language.current")}</span>
          <span className="font-medium text-zinc-800 dark:text-zinc-200">{LOCALE_LABELS[locale]}</span>
          <span className="text-[10px] text-zinc-600 uppercase tracking-wide">
            {LOCALE_NAMES[locale]}
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {LOCALES.map((loc: Locale) => {
            const active = loc === locale;
            return (
              <button
                key={loc}
                type="button"
                onClick={() => setLocale(loc)}
                className={cn(
                  "flex items-center justify-between gap-2 px-3 py-2 rounded-md border text-sm transition-colors",
                  active
                    ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-200"
                    : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-700 dark:text-zinc-300 hover:border-black/20 dark:hover:border-white/20 hover:text-zinc-900 dark:hover:text-zinc-100"
                )}
              >
                <span className="truncate">{LOCALE_LABELS[loc]}</span>
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">
                  {LOCALE_NAMES[loc]}
                </span>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ============== About Card ==============

function AboutCard() {
  const t = useT();
  const [about, setAbout] = useState<AboutInfo | null>(null);
  const [update, setUpdate] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get<AboutInfo>("/meta/about")
      .then((data) => {
        if (!cancelled) setAbout(data);
      })
      .catch(() => {
        // silently ignore — card just shows fallback strings
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleCheckUpdate() {
    setChecking(true);
    setCheckError(false);
    try {
      const data = await api.get<UpdateCheck>("/meta/check-update");
      setUpdate(data);
    } catch {
      setCheckError(true);
      setUpdate(null);
    } finally {
      setChecking(false);
    }
  }

  const name = about?.name ?? "LifeTree";
  const description = about?.description ?? t("settings.about.description");
  const version = about?.version ?? "—";
  const license = about?.license ?? "AGPL-3.0";
  const githubUrl = about?.github_url ?? "https://github.com/lifetree/lifetree";

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Info className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.about.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.about.description")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            {name}
          </div>
          <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-snug mt-1">
            {description}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-zinc-500 dark:text-zinc-400">
              {t("settings.about.version")}
            </span>
            <Badge variant="default" className="text-[10px] font-mono">
              {version}
            </Badge>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-zinc-500 dark:text-zinc-400">
              {t("settings.about.license")}
            </span>
            <span className="font-mono text-zinc-700 dark:text-zinc-300">
              {license}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <a
              href={githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5"
            >
              <Github className="h-3.5 w-3.5" />
              {t("settings.about.starOnGithub")}
            </a>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleCheckUpdate}
            disabled={checking}
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5 mr-1.5", checking && "animate-spin")}
            />
            {t("settings.about.checkUpdate")}
          </Button>
        </div>

        {update?.has_update ? (
          <div className="flex items-center gap-2 text-xs text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>
              {t("settings.about.newVersion", { version: update.latest_version })}
            </span>
            <a
              href={update.release_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-brand-600 dark:text-brand-400 hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        ) : update && !update.has_update ? (
          <div className="flex items-center gap-2 text-xs text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
            <span>{t("settings.about.upToDate")}</span>
          </div>
        ) : checkError ? (
          <div className="flex items-center gap-2 text-xs text-red-600 dark:text-red-300">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>{t("settings.about.checkFailed")}</span>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
