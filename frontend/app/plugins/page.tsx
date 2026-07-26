"use client";

import { useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { usePlugins } from "@/lib/hooks";
import { api, type PluginManifest, type PluginRunResult } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
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
import {
  Plug,
  Loader2,
  Play,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Tag,
  Upload,
  Trash2,
  Power,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

export default function PluginsPage() {
  const t = useT();
  const { data: plugins, isLoading } = usePlugins();
  const [uploadOpen, setUploadOpen] = useState(false);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <Plug className="h-6 w-6 text-brand-400" />
            {t("plugins.title")}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">{t("plugins.subtitle")}</p>
        </div>
        <Button onClick={() => setUploadOpen(true)} variant="outline" size="sm">
          <Upload className="h-4 w-4 mr-1.5" />
          {t("plugins.upload.button")}
        </Button>
      </header>

      {isLoading && (
        <div className="text-sm text-zinc-500">{t("common.loading")}</div>
      )}

      {!isLoading && (plugins?.length ?? 0) === 0 && (
        <Card>
          <CardContent className="py-12 text-center space-y-3">
            <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center">
              <Plug className="h-6 w-6 text-brand-400" />
            </div>
            <div className="text-sm text-zinc-300">{t("plugins.empty.title")}</div>
            <p className="text-xs text-zinc-500 max-w-md mx-auto">
              {t("plugins.empty.hint", {
                dir: "backend/plugins/",
                iface: "Plugin",
              })}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {plugins?.map((p) => (
          <PluginCard key={`${p.source ?? "builtin"}-${p.id}`} plugin={p} />
        ))}
      </div>

      <Card>
        <CardContent className="py-4 text-xs text-zinc-500 leading-relaxed space-y-2">
          <div className="font-medium text-zinc-300">{t("plugins.howTo.title")}</div>
          <p>
            {t("plugins.howTo.body", {
              dir: "backend/plugins/",
              ext: ".py",
              cls: "Plugin",
            })}
          </p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>
              <code className="font-mono text-zinc-400">manifest()</code> — {t("plugins.howTo.manifest")}
            </li>
            <li>
              <code className="font-mono text-zinc-400">fetch(params)</code> — {t("plugins.howTo.fetch")}
            </li>
            <li>
              <code className="font-mono text-zinc-400">transform(raw, llm)</code> — {t("plugins.howTo.transform")}
            </li>
          </ul>
          <p>
            {t("plugins.howTo.footer", {
              a: "sample_web_scraper.py",
              b: "sample_rss_feed.py",
            })}
          </p>
          <div className="mt-4 pt-4 border-t border-zinc-200 dark:border-zinc-800">
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              {t("plugins.howTo.contribute")}
            </p>
          </div>
        </CardContent>
      </Card>

      <UploadPluginDialog open={uploadOpen} onOpenChange={setUploadOpen} />
    </div>
  );
}

function UploadPluginDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const t = useT();
  const toast = useToast();
  const { mutate } = useSWRConfig();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<
    { kind: "error" | "success"; message: string } | null
  >(null);

  function reset() {
    setFile(null);
    setOverwrite(false);
    setFeedback(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFeedback(null);
    if (f && !f.name.endsWith(".py")) {
      setFeedback({
        kind: "error",
        message: t("plugins.upload.invalidExtension"),
      });
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setFile(f);
  }

  async function handleSubmit() {
    if (!file) return;
    setBusy(true);
    setFeedback(null);
    try {
      const r = await api.uploadPlugin(file, overwrite);
      if (r.ok) {
        toast({
          title: t("plugins.upload.success"),
          description: r.plugin_id ?? file.name,
          variant: "success",
        });
        await mutate("plugins");
        reset();
        onOpenChange(false);
      } else {
        const msg = r.error ?? t("plugins.upload.failed");
        setFeedback({ kind: "error", message: msg });
        toast({
          title: t("plugins.upload.failed"),
          description: msg,
          variant: "error",
        });
      }
    } catch (e: any) {
      const msg = e?.message ?? t("plugins.upload.failed");
      setFeedback({ kind: "error", message: msg });
      toast({
        title: t("plugins.upload.failed"),
        description: msg,
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!busy) {
          onOpenChange(v);
          if (!v) reset();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("plugins.upload.dialogTitle")}</DialogTitle>
          <DialogDescription>
            {t("plugins.upload.dropzone")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div
            className={cn(
              "border border-dashed border-white/15 rounded-md p-4 text-center cursor-pointer hover:bg-white/5 transition-colors",
              file && "border-brand-500/40 bg-brand-500/5"
            )}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".py"
              onChange={handleFileChange}
              className="hidden"
            />
            {file ? (
              <div className="text-sm text-zinc-200 font-mono">{file.name}</div>
            ) : (
              <div className="text-sm text-zinc-500">
                {t("plugins.upload.dropzone")}
              </div>
            )}
            <div className="text-[10px] text-zinc-600 mt-1">
              .py — {t("plugins.upload.dropzone")}
            </div>
          </div>

          <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(e) => setOverwrite(e.target.checked)}
              className="accent-brand-500"
            />
            {t("plugins.upload.overwrite")}
          </label>

          {feedback && (
            <div
              className={cn(
                "rounded-md border p-2 text-xs",
                feedback.kind === "error"
                  ? "border-red-500/30 bg-red-500/5 text-red-300"
                  : "border-emerald-500/30 bg-emerald-500/5 text-emerald-300"
              )}
            >
              {feedback.message}
            </div>
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost" size="sm" disabled={busy}>
              {t("common.cancel")}
            </Button>
          </DialogClose>
          <Button onClick={handleSubmit} disabled={!file || busy} size="sm">
            {busy ? (
              <>
                <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                {t("common.loading")}
              </>
            ) : (
              <>
                <Upload className="h-3.5 w-3.5 mr-1" />
                {t("plugins.upload.submit")}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PluginCard({ plugin }: { plugin: PluginManifest }) {
  const t = useT();
  const { mutate } = useSWRConfig();
  const toast = useToast();
  const [expanded, setExpanded] = useState(false);
  const [params, setParams] = useState<Record<string, string>>({});
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PluginRunResult | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [toggling, setToggling] = useState(false);

  const isUser = plugin.source === "user";
  const enabled = plugin.enabled !== false; // builtin or user-enabled

  function setParam(name: string, value: string) {
    setParams((prev) => ({ ...prev, [name]: value }));
  }

  function initDefaults() {
    const d: Record<string, string> = {};
    for (const p of plugin.params) {
      if (p.default !== null && p.default !== undefined) {
        d[p.name] = String(p.default);
      }
    }
    setParams((prev) => ({ ...d, ...prev }));
  }

  async function handleRun() {
    // Validate required params
    for (const p of plugin.params) {
      if (p.required && !params[p.name]?.trim()) {
        toast({
          title: t("plugins.toast.missingParam"),
          description: `${p.label} (${p.name})`,
          variant: "error",
        });
        return;
      }
    }
    setBusy(true);
    setResult(null);
    try {
      const r = await api.runPlugin(plugin.id, {
        params,
        title: title || undefined,
      });
      setResult(r);
      if (r.ok && !r.error) {
        toast({
          title: t("plugins.toast.runDone"),
          description:
            r.warning ??
            t("plugins.toast.runDoneDesc", {
              e: r.events_created,
              m: r.metrics_created,
              a: r.assertions_created,
            }),
          variant: r.warning ? "error" : "success",
        });
      } else {
        toast({
          title: t("plugins.toast.runFailed"),
          description: r.error ?? t("plugins.toast.runFailedDesc"),
          variant: "error",
        });
      }
    } catch (e: any) {
      toast({
        title: t("plugins.toast.runFailed"),
        description: e?.message ?? t("plugins.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function handleToggle() {
    if (!isUser) return;
    setToggling(true);
    try {
      await api.togglePlugin(plugin.id, !enabled);
      await mutate("plugins");
      toast({
        title: enabled
          ? t("plugins.card.disable")
          : t("plugins.card.enable"),
        description: plugin.id,
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("plugins.toast.runFailed"),
        description: e?.message ?? t("plugins.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setToggling(false);
    }
  }

  async function handleDelete() {
    if (!isUser) return;
    setBusy(true);
    try {
      await api.deletePlugin(plugin.id);
      await mutate("plugins");
      toast({
        title: t("plugins.card.delete"),
        description: plugin.id,
        variant: "success",
      });
      setConfirmingDelete(false);
    } catch (e: any) {
      toast({
        title: t("plugins.toast.runFailed"),
        description: e?.message ?? t("plugins.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <button
                onClick={() => {
                  setExpanded((v) => !v);
                  if (!expanded && Object.keys(params).length === 0) initDefaults();
                }}
                className="text-zinc-400 hover:text-zinc-200"
                aria-label={expanded ? t("plugins.card.collapse") : t("plugins.card.expand")}
              >
                {expanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </button>
              <span className="truncate">{plugin.name}</span>
              <Badge variant="default" className="text-[10px] font-mono">
                v{plugin.version}
              </Badge>
              <Badge
                variant="default"
                className={cn(
                  "text-[10px]",
                  isUser
                    ? "border-brand-500/40 text-brand-300"
                    : "border-white/10 text-zinc-400"
                )}
              >
                {isUser
                  ? t("plugins.card.sourceUser")
                  : t("plugins.card.sourceBuiltin")}
              </Badge>
              {isUser && !enabled && (
                <Badge
                  variant="default"
                  className="text-[10px] border-amber-500/40 text-amber-300"
                >
                  {t("plugins.card.disable")}
                </Badge>
              )}
            </CardTitle>
            <CardDescription className="mt-1">{plugin.description}</CardDescription>
            {plugin.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {plugin.tags.map((tg) => (
                  <span
                    key={tg}
                    className="inline-flex items-center gap-0.5 text-[10px] text-zinc-500 border border-white/10 rounded px-1.5 py-0.5"
                  >
                    <Tag className="h-2.5 w-2.5" />
                    {tg}
                  </span>
                ))}
              </div>
            )}
            {isUser && plugin.uploaded_at && (
              <div className="text-[10px] text-zinc-600 mt-1">
                {t("plugins.card.uploadedAt", {
                  when: new Date(plugin.uploaded_at).toLocaleString(),
                })}
              </div>
            )}
          </div>

          {isUser && (
            <div className="flex items-center gap-1 shrink-0">
              <Button
                size="icon"
                variant="ghost"
                onClick={handleToggle}
                disabled={toggling}
                title={enabled ? t("plugins.card.disable") : t("plugins.card.enable")}
                className="h-7 w-7"
              >
                <Power
                  className={cn(
                    "h-3.5 w-3.5",
                    enabled ? "text-emerald-400" : "text-zinc-500"
                  )}
                />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setConfirmingDelete(true)}
                disabled={busy}
                title={t("plugins.card.delete")}
                className="h-7 w-7 hover:text-red-300"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-3 flex-1">
          <div className="space-y-2">
            {plugin.params.map((p) => (
              <div key={p.name} className="space-y-1">
                <Label className="text-xs flex items-center gap-1">
                  {p.label}
                  {p.required && <span className="text-red-400">*</span>}
                  <span className="text-[10px] text-zinc-600 font-mono">({p.name})</span>
                </Label>
                <Input
                  value={params[p.name] ?? ""}
                  onChange={(e) => setParam(p.name, e.target.value)}
                  placeholder={p.help || t("plugins.card.paramPlaceholder", { label: p.label })}
                  className="h-8 text-sm"
                />
                {p.help && (
                  <p className="text-[10px] text-zinc-500 leading-snug">{p.help}</p>
                )}
              </div>
            ))}
          </div>

          <div className="space-y-1">
            <Label className="text-xs">{t("plugins.card.sourceTitle")}</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("plugins.card.sourcePlaceholder")}
              className="h-8 text-sm"
            />
          </div>

          <Button
            onClick={handleRun}
            disabled={busy || !enabled}
            className="w-full"
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                {t("plugins.card.running")}
              </>
            ) : (
              <>
                <Play className="h-4 w-4 mr-1.5" />
                {t("plugins.card.run")}
              </>
            )}
          </Button>

          {!enabled && (
            <p className="text-[10px] text-amber-300 leading-snug">
              {t("plugins.card.disable")}
            </p>
          )}

          {result && <ResultBlock result={result} />}
        </CardContent>
      )}

      <Dialog
        open={confirmingDelete}
        onOpenChange={(v) => !busy && setConfirmingDelete(v)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("plugins.card.delete")}</DialogTitle>
            <DialogDescription>
              {t("plugins.card.deleteConfirm", { name: plugin.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost" size="sm" disabled={busy}>
                {t("common.cancel")}
              </Button>
            </DialogClose>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              disabled={busy}
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5 mr-1" />
              )}
              {t("common.delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function ResultBlock({ result }: { result: PluginRunResult }) {
  const t = useT();
  if (!result.ok && result.error) {
    return (
      <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-xs">
        <div className="flex items-center gap-1.5 text-red-300 font-medium mb-1">
          <AlertTriangle className="h-3.5 w-3.5" />
          {t("plugins.result.error")}
        </div>
        <p className="text-zinc-400 leading-snug break-words">{result.error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs">
        <div className="flex items-center gap-1.5 text-emerald-300 font-medium mb-1.5">
          <CheckCircle2 className="h-3.5 w-3.5" />
          {t("plugins.result.success")}
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Stat label={t("plugins.stat.events")} value={result.events_created} />
          <Stat label={t("plugins.stat.metrics")} value={result.metrics_created} />
          <Stat label={t("plugins.stat.assertions")} value={result.assertions_created} />
          <Stat label={t("plugins.stat.relationships")} value={result.relationships_created} />
          <Stat label={t("plugins.stat.notifications")} value={result.notifications_triggered} />
          <Stat
            label={t("plugins.stat.confidence")}
            value={
              result.extraction_confidence !== null
                ? `${(result.extraction_confidence * 100).toFixed(0)}%`
                : "—"
            }
          />
        </div>
        {result.source_id && (
          <div className="mt-2 text-[10px] text-zinc-600 font-mono truncate">
            source: {result.source_id}
          </div>
        )}
      </div>
      {result.warning && (
        <div className="text-[11px] text-amber-300 leading-snug flex items-start gap-1.5">
          <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
          <span>{result.warning}</span>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded bg-black/20 px-2 py-1.5 border border-white/5">
      <div className="text-[9px] text-zinc-500">{label}</div>
      <div className="text-sm font-semibold text-zinc-100 mt-0.5">{value}</div>
    </div>
  );
}
