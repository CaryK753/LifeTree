"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth, useSettings } from "@/lib/hooks";
import {
  api,
  apiUrl,
  getAccessToken,
  getDesktopHeaders,
  request,
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Download,
  ExternalLink,
  FileJson,
  Github,
  Globe,
  Info,
  Monitor,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { LOCALES, LOCALE_LABELS, LOCALE_NAMES, type Locale } from "@/lib/i18n/messages";
import { useI18n } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import Link from "next/link";
import { McpSettingsCard } from "@/components/settings/mcp-settings-card";
import { SkillSettingsCard } from "@/components/settings/skill-settings-card";
import { PersonalModelSettings } from "@/components/settings/personal-model-settings";
import { PersonalServiceKeys } from "@/components/settings/personal-service-keys";
import { WebPushControl } from "@/components/settings/web-push-control";
import { isTauriHost } from "@/lib/notifications";

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

      <PersonalModelSettings />
      <PersonalServiceKeys />
      <WebPushControl />
      <McpSettingsCard />
      <SkillSettingsCard />

      {/* ---------- Theme ---------- */}
      <ThemeCard />

      {/* ---------- Language ---------- */}
      <LanguageCard />

      {/* ---------- Backup / restore ---------- */}
      <BackupCard />

      {/* ---------- About ---------- */}
      <AboutCard />

      {/* ---------- Desktop instance switcher (only in Tauri) ---------- */}
      {isTauriHost() && <DesktopInstanceCard />}
    </div>
  );
}

// ============== Desktop Instance Card ==============

/**
 * DesktopInstanceCard — shown only in the Tauri desktop app. Provides an
 * in-app button to reopen the bootstrap launcher so the user can switch
 * between local service / self-hosted / cloud instances without relying
 * on the system tray menu.
 */
function DesktopInstanceCard() {
  const t = useT();
  const [switching, setSwitching] = useState(false);

  async function handleSwitch() {
    setSwitching(true);
    try {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__?: {
          invoke: (cmd: string) => Promise<unknown>;
        };
      }).__TAURI_INTERNALS__;
      if (internals) {
        await internals.invoke("switch_instance");
      }
    } catch {
      // Ignore — the window will close anyway if the command succeeded.
    } finally {
      setSwitching(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Monitor className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.desktopInstance.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.desktopInstance.desc")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <Button
          variant="outline"
          size="sm"
          onClick={handleSwitch}
          disabled={switching}
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5 mr-1.5", switching && "animate-spin")}
          />
          {t("settings.desktopInstance.switch")}
        </Button>
      </CardContent>
    </Card>
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

// ============== Backup Card ==============

interface ImportSummary {
  imported: Record<string, number>;
  skipped: number;
  errors: Array<{ type: string; id?: string; error: string }>;
}

function BackupCard() {
  const t = useT();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // ---- Download helpers ----
  // Use direct fetch (not api.request) so we get the raw response body
  // as a Blob — api.request always parses as JSON, which would fail for
  // the JSONL endpoint and double-encode the JSON endpoint.
  async function fetchAuthed(path: string): Promise<Response> {
    const token = getAccessToken();
    const res = await fetch(apiUrl(path), {
      headers: {
        ...getDesktopHeaders(),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    if (!res.ok) {
      throw new Error(`${res.status} ${res.statusText}`);
    }
    return res;
  }

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function todayStamp(): string {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
  }

  async function handleExportJson() {
    setExporting(true);
    try {
      const res = await fetchAuthed("/backup/export");
      const blob = await res.blob();
      triggerDownload(blob, `lifetree-export-${todayStamp()}.json`);
    } catch (error) {
      toast({
        title: t("settings.backup.exportFailed"),
        description: error instanceof Error ? error.message : "",
        variant: "error",
      });
    } finally {
      setExporting(false);
    }
  }

  async function handleExportJsonl() {
    setExporting(true);
    try {
      const res = await fetchAuthed("/backup/export-jsonl");
      const blob = await res.blob();
      triggerDownload(blob, `lifetree-export-${todayStamp()}.jsonl`);
    } catch (error) {
      toast({
        title: t("settings.backup.exportFailed"),
        description: error instanceof Error ? error.message : "",
        variant: "error",
      });
    } finally {
      setExporting(false);
    }
  }

  // ---- Import helpers ----
  async function runImport(confirm: boolean) {
    if (!selectedFile) {
      toast({ title: t("settings.backup.noFileSelected"), variant: "warning" });
      return;
    }

    let data: unknown;
    try {
      const text = await selectedFile.text();
      data = JSON.parse(text);
    } catch {
      toast({ title: t("settings.backup.invalidFile"), variant: "error" });
      return;
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      toast({ title: t("settings.backup.invalidFile"), variant: "error" });
      return;
    }

    setImporting(true);
    try {
      const summary = await request<ImportSummary>("/backup/import", {
        method: "POST",
        body: JSON.stringify({
          data,
          mode,
          confirm,
        }),
      });
      const totalImported = Object.values(summary.imported || {}).reduce(
        (a, b) => a + b,
        0
      );
      toast({
        title: t("settings.backup.importSuccess"),
        description: t("settings.backup.summary", {
          imported: totalImported,
          skipped: summary.skipped ?? 0,
          errors: summary.errors?.length ?? 0,
        }),
        variant: "success",
      });
      // Reset file picker after a successful import.
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (error) {
      toast({
        title: t("settings.backup.importFailed"),
        description: error instanceof Error ? error.message : "",
        variant: "error",
      });
    } finally {
      setImporting(false);
    }
  }

  function handleImportClick() {
    if (!selectedFile) {
      toast({ title: t("settings.backup.noFileSelected"), variant: "warning" });
      return;
    }
    if (mode === "replace") {
      // Confirm dialog gates the actual import.
      setConfirmOpen(true);
      return;
    }
    void runImport(false);
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Download className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.backup.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.backup.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* ---------- Export ---------- */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportJson}
              disabled={exporting || importing}
            >
              <Download className="h-3.5 w-3.5 mr-1.5" />
              {exporting ? t("settings.backup.exporting") : t("settings.backup.exportJson")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportJsonl}
              disabled={exporting || importing}
            >
              <FileJson className="h-3.5 w-3.5 mr-1.5" />
              {exporting ? t("settings.backup.exporting") : t("settings.backup.exportJsonl")}
            </Button>
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
            {t("settings.backup.exportHint")}
          </p>
        </div>

        {/* ---------- Import ---------- */}
        <div className="space-y-3 border-t border-black/5 dark:border-white/5 pt-4">
          <div>
            <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              {t("settings.backup.importTitle")}
            </div>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1 leading-relaxed">
              {t("settings.backup.importHint")}
            </p>
          </div>

          {/* Hidden file input + pick button */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setSelectedFile(f);
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={exporting || importing}
            >
              <Upload className="h-3.5 w-3.5 mr-1.5" />
              {t("settings.backup.selectFile")}
            </Button>
            {selectedFile && (
              <span className="text-xs text-zinc-600 dark:text-zinc-300 truncate max-w-[16rem]">
                {selectedFile.name}
              </span>
            )}
          </div>

          {/* Mode selector */}
          <div className="space-y-1.5">
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              {t("settings.backup.modeLabel")}
            </div>
            <div className="grid grid-cols-2 gap-2 max-w-md">
              <button
                type="button"
                onClick={() => setMode("merge")}
                className={cn(
                  "rounded-md border px-3 py-2 text-left text-sm transition-colors",
                  mode === "merge"
                    ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-200"
                    : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-700 dark:text-zinc-300 hover:border-black/20 dark:hover:border-white/20"
                )}
              >
                <div className="font-medium">{t("settings.backup.modeMerge")}</div>
                <div className="text-[11px] text-zinc-500 mt-0.5">
                  {t("settings.backup.modeMergeDesc")}
                </div>
              </button>
              <button
                type="button"
                onClick={() => setMode("replace")}
                className={cn(
                  "rounded-md border px-3 py-2 text-left text-sm transition-colors",
                  mode === "replace"
                    ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-200"
                    : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-700 dark:text-zinc-300 hover:border-black/20 dark:hover:border-white/20"
                )}
              >
                <div className="font-medium">{t("settings.backup.modeReplace")}</div>
                <div className="text-[11px] text-zinc-500 mt-0.5">
                  {t("settings.backup.modeReplaceDesc")}
                </div>
              </button>
            </div>
          </div>

          {mode === "replace" && (
            <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-300">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{t("settings.backup.modeReplaceDesc")}</span>
            </div>
          )}

          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={handleImportClick}
              disabled={exporting || importing || !selectedFile}
            >
              {importing ? t("settings.backup.importing") : t("settings.backup.importButton")}
            </Button>
          </div>
        </div>
      </CardContent>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={t("settings.backup.confirmReplaceTitle")}
        description={t("settings.backup.confirmReplaceDesc")}
        confirmLabel={t("settings.backup.modeReplace")}
        cancelLabel={t("common.cancel")}
        variant="danger"
        onConfirm={() => {
          void runImport(true);
        }}
      />
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
          <Button asChild variant="outline" size="sm">
            <Link href="/terms" className="inline-flex items-center gap-1.5">
              <ScrollText className="h-3.5 w-3.5" />
              {t("legal.terms")}
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href="/privacy" className="inline-flex items-center gap-1.5">
              <ShieldCheck className="h-3.5 w-3.5" />
              {t("legal.privacy")}
            </Link>
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
