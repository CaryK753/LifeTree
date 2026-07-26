"use client";

import { useState } from "react";
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

export default function PluginsPage() {
  const t = useT();
  const { data: plugins, isLoading } = usePlugins();

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header>
        <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
          <Plug className="h-6 w-6 text-brand-400" />
          {t("plugins.title")}
        </h1>
        <p className="text-sm text-zinc-500 mt-1">{t("plugins.subtitle")}</p>
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
          <PluginCard key={p.id} plugin={p} />
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
        </CardContent>
      </Card>
    </div>
  );
}

function PluginCard({ plugin }: { plugin: PluginManifest }) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [params, setParams] = useState<Record<string, string>>({});
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PluginRunResult | null>(null);
  const toast = useToast();

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
          </div>
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

          <Button onClick={handleRun} disabled={busy} className="w-full">
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

          {result && <ResultBlock result={result} />}
        </CardContent>
      )}
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
