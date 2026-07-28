"use client";

import { useEffect, useMemo, useState } from "react";
import { useAuth, useSettings } from "@/lib/hooks";
import {
  api,
  type AboutInfo,
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
import { Badge } from "@/components/ui/badge";
import { ThemeCard } from "@/components/theme/theme-card";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Github,
  Globe,
  Info,
  RefreshCw,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { LOCALES, LOCALE_LABELS, LOCALE_NAMES, type Locale } from "@/lib/i18n/messages";
import { useI18n } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import Link from "next/link";

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

      {/* ---------- Admin shortcut (admin users only) ----------
          Platform-level configuration (providers, models, API keys, SMTP,
          OAuth providers, use mode, auth settings, system components)
          lives on the /admin page to avoid duplicating it here. Show a
          shortcut card so admins know where to find it. */}
      {isAdmin && <AdminShortcutCard />}

      {/* ---------- Theme ---------- */}
      <ThemeCard />

      {/* ---------- Language ---------- */}
      <LanguageCard />

      {/* ---------- About ---------- */}
      <AboutCard />
    </div>
  );
}

// ============== Admin Shortcut Card ==============

/**
 * AdminShortcutCard — a small banner that links to /admin where all
 * platform-level configuration (providers, models, API keys, SMTP, OAuth
 * providers, use mode, auth settings) now lives. Shown only to admin
 * users so they know where to find the moved settings.
 */
function AdminShortcutCard() {
  const t = useT();
  return (
    <Link
      href="/admin"
      className="block group"
    >
      <Card className="transition-colors hover:border-brand-500/40 hover:bg-brand-500/[0.03]">
        <CardContent className="flex items-center gap-3 py-4">
          <div className="h-9 w-9 rounded-md bg-amber-500/10 text-amber-700 dark:text-amber-300 flex items-center justify-center shrink-0">
            <ShieldAlert className="h-4 w-4" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              {t("settings.adminShortcut.title")}
            </div>
            <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5 leading-snug">
              {t("settings.adminShortcut.desc")}
            </div>
          </div>
          <ArrowRight className="h-4 w-4 text-zinc-400 group-hover:text-brand-600 dark:group-hover:text-brand-400 group-hover:translate-x-0.5 transition-all shrink-0" />
        </CardContent>
      </Card>
    </Link>
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
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Project introduction — a short, human-readable summary of
            what LifeTree is and who it's for. Shown above the version /
            license row so first-time visitors get context immediately. */}
        <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">
          {t("settings.about.description")}
        </p>

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
