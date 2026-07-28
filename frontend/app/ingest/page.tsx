"use client";

import { useState, useRef, useEffect } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Loader2,
  Upload,
  FileText,
  Sparkles,
  CheckCircle2,
  FileUp,
  FileType2,
  AlertTriangle,
  X,
  Search as SearchIcon,
  Globe,
  ExternalLink,
  Plus,
  Info,
  RotateCcw,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { PIIPreviewPanel } from "@/components/sources/pii-preview-panel";

const KIND_VALUES = ["public", "official", "news", "advisor", "user_upload", "other"] as const;

const ACCEPTED_SUFFIXES = [
  ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
  ".txt", ".md", ".csv",
  ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
];

type Mode = "text" | "file" | "search";

interface SearchHit {
  title: string;
  url: string;
  content: string;
  score: number;
  published_at?: string | null;
}

export default function IngestPage() {
  const t = useT();
  const [mode, setMode] = useState<Mode>("text");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const toast = useToast();

  // text mode state
  const [text, setText] = useState("");
  const [textTitle, setTextTitle] = useState("");
  const [kind, setKind] = useState("public");
  const [url, setUrl] = useState("");
  const [publisher, setPublisher] = useState("");

  // file mode state
  const [file, setFile] = useState<File | null>(null);
  const [fileTitle, setFileTitle] = useState("");
  const [legalAck, setLegalAck] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileContent, setFileContent] = useState("");
  // Last upload error — when set, a retry banner is shown. Cleared on
  // successful upload, file change, or new attempt. Allows the user to
  // retry without re-selecting the file (file state is preserved on
  // failure since setFile(null) only runs in the success path).
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (!file) {
      setFileContent("");
      return;
    }
    const isTextLike =
      file.type.startsWith("text/") ||
      /\.(txt|md|csv|json|xml|html|log|py|js|ts|tsx|jsx)$/i.test(file.name);

    if (isTextLike || file.size < 2 * 1024 * 1024) {
      file
        .text()
        .then((t) => setFileContent(t))
        .catch(() => setFileContent(file.name));
    } else {
      setFileContent(file.name);
    }
  }, [file]);

  async function handleTextIngest() {
    if (!text.trim() || !textTitle.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await api.ingestText({
        text,
        title: textTitle,
        source_kind: kind,
        url: url || null,
        publisher: publisher || null,
      });
      setResult(res);
      toast({
        title: t("ingest.toast.stored"),
        description: t("ingest.toast.storedDesc"),
        variant: "success",
      });
      setText("");
      setTextTitle("");
      setUrl("");
      setPublisher("");
    } catch (e: any) {
      toast({
        title: t("ingest.toast.failed"),
        description: e?.message ?? t("plugins.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function handleFileIngest() {
    if (!file) return;
    if (!legalAck) {
      toast({
        title: t("ingest.toast.failed"),
        description: t("ingest.file.legalAckRequired"),
        variant: "warning",
      });
      return;
    }
    setBusy(true);
    setResult(null);
    setFileError(null);
    try {
      const res = await api.ingestUpload(file, {
        title: fileTitle || file.name,
        source_kind: "user_upload",
      });
      setResult(res);
      // If the response carries a parser warning (e.g. no Mineru key),
      // surface it instead of pretending success.
      const warning = (res as any)?.warning;
      if (warning) {
        toast({
          title: t("ingest.toast.savedNoExtract"),
          description: warning,
          variant: "error",
        });
      } else {
        toast({
          title: t("ingest.toast.stored"),
          description: t("ingest.toast.fileParsed", { name: file.name }),
          variant: "success",
        });
      }
      setFile(null);
      setFileTitle("");
      setLegalAck(false);
    } catch (e: any) {
      const msg = e?.message ?? t("plugins.toast.retryLater");
      setFileError(msg);
      toast({
        title: t("ingest.toast.uploadFailed"),
        description: msg,
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      setFile(f);
      setFileError(null);
    }
  }

  function pickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f);
      setFileError(null);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 w-full max-w-[1400px] mx-auto animate-fade-in">
      <header>
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
          <SidebarToggleButton />
          <Upload className="h-6 w-6 text-brand-600 dark:text-brand-400" />
          {t("ingest.title")}
        </h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">{t("ingest.subtitle")}</p>
      </header>

      {/* Guide banner — explains WHY the user should upload documents and
          what happens to them. First-time users often land on this page
          with no context; without this they'd see a bare upload form and
          leave. The card uses an info accent (not a warning) so it reads
          as helpful guidance, not an error. */}
      <div className="rounded-md border border-brand-500/20 bg-brand-500/[0.04] p-3 flex gap-3">
        <div className="h-7 w-7 rounded-md bg-brand-500/15 flex items-center justify-center shrink-0">
          <Info className="h-4 w-4 text-brand-600 dark:text-brand-400" />
        </div>
        <div className="min-w-0">
          <div className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
            {t("ingest.guide.title")}
          </div>
          <p className="text-[11px] text-zinc-600 dark:text-zinc-400 mt-0.5 leading-relaxed">
            {t("ingest.guide.desc")}
          </p>
        </div>
      </div>

      {/* Mode switch — a segmented control / "slider" toggle. Uses
          light/dark paired classes so the active segment, track, and
          inactive labels all read correctly in both themes. */}
      <div className="flex gap-1 p-1 rounded-md bg-black/[0.04] dark:bg-white/5 border border-black/5 dark:border-white/5 w-fit">
        <ModeButton
          active={mode === "text"}
          onClick={() => setMode("text")}
          icon={<FileText className="h-3.5 w-3.5" />}
          label={t("ingest.mode.text")}
        />
        <ModeButton
          active={mode === "file"}
          onClick={() => setMode("file")}
          icon={<FileUp className="h-3.5 w-3.5" />}
          label={t("ingest.mode.file")}
        />
        <ModeButton
          active={mode === "search"}
          onClick={() => setMode("search")}
          icon={<SearchIcon className="h-3.5 w-3.5" />}
          label={t("ingest.mode.search")}
        />
      </div>

      {mode === "search" ? (
        <SearchCard
          busy={busy}
          setBusy={setBusy}
          setResult={setResult}
        />
      ) : mode === "text" ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <FileText className="h-4 w-4 text-brand-600 dark:text-brand-400" />
                {t("ingest.text.title")}
              </CardTitle>
              <CardDescription className="mt-1">
                {t("ingest.text.subtitle")}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label>{t("ingest.field.title")}</Label>
              <Input
                value={textTitle}
                onChange={(e) => setTextTitle(e.target.value)}
                placeholder={t("ingest.field.titlePlaceholder")}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>{t("ingest.field.publisher")}</Label>
                <Input
                  value={publisher}
                  onChange={(e) => setPublisher(e.target.value)}
                  placeholder={t("ingest.field.publisherPlaceholder")}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("ingest.field.url")}</Label>
                <Input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://..."
                />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-2 md:gap-4 items-center">
              <Label>{t("ingest.field.kind")}</Label>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger>
                  <SelectValue placeholder={t("ingest.field.kindPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {KIND_VALUES.map((v) => (
                    <SelectItem key={v} value={v}>
                      {t(`kind.${v}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>{t("ingest.field.body")}</Label>
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={10}
                placeholder={t("ingest.field.bodyPlaceholder")}
              />
            </div>
            {text.trim() && <PIIPreviewPanel text={text} />}
            <div className="flex justify-end">
              <Button
                onClick={handleTextIngest}
                disabled={busy || !text.trim() || !textTitle.trim()}
              >
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                    {t("ingest.text.processing")}
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4 mr-1.5" />
                    {t("ingest.text.submit")}
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <FileUp className="h-4 w-4 text-brand-600 dark:text-brand-400" />
                {t("ingest.file.title")}
              </CardTitle>
              <CardDescription className="mt-1">
                {t("ingest.file.subtitle")}
                <br />
                {t("ingest.file.subtitle2")}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Dropzone */}
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
                dragOver
                  ? "border-brand-400/60 bg-brand-500/5"
                  : "border-black/10 dark:border-white/10 hover:border-black/20 dark:hover:border-white/20 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]"
              )}
            >
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept={ACCEPTED_SUFFIXES.join(",")}
                onChange={pickFile}
              />
              {!file ? (
                <>
                  <FileUp className="h-8 w-8 mx-auto text-zinc-500 dark:text-zinc-400 mb-2" />
                  <div className="text-sm text-zinc-700 dark:text-zinc-300">
                    {t("ingest.file.drop")}
                    <span className="text-brand-600 dark:text-brand-400">{t("ingest.file.browse")}</span>
                  </div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-500 mt-1.5">
                    {ACCEPTED_SUFFIXES.join("  ·  ")}
                  </div>
                </>
              ) : (
                <div className="flex items-center justify-center gap-3 text-left">
                  <FileType2 className="h-8 w-8 text-brand-600 dark:text-brand-400 shrink-0" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">
                      {file.name}
                    </div>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                      {(file.size / 1024).toFixed(1)} KB
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={(e) => {
                      e.stopPropagation();
                      setFile(null);
                    }}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <Label>{t("ingest.file.titleOptional")}</Label>
              <Input
                value={fileTitle}
                onChange={(e) => setFileTitle(e.target.value)}
                placeholder={file?.name ?? t("ingest.file.titlePlaceholder")}
              />
            </div>
            {file && (
              <PIIPreviewPanel text={fileContent || fileTitle || file.name} />
            )}

            {/* Legal disclaimer — required for private uploads. Per project
                plan §4.7: "上传流程强制确认" the user must acknowledge that
                uploaded private info is unverified and they bear the risk
                of acting on it. The submit button stays disabled until
                this is checked. */}
            <label className="flex items-start gap-2 text-xs text-zinc-600 dark:text-zinc-300 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 cursor-pointer hover:bg-amber-500/10 transition-colors">
              <input
                type="checkbox"
                checked={legalAck}
                onChange={(e) => setLegalAck(e.target.checked)}
                className="mt-0.5 accent-amber-500 shrink-0"
              />
              <span className="leading-relaxed">
                {t("ingest.file.legalDisclaimer")}
              </span>
            </label>

            <div className="flex justify-end">
              <Button
                onClick={handleFileIngest}
                disabled={busy || !file || !legalAck}
              >
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                    {t("ingest.file.processing")}
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4 mr-1.5" />
                    {t("ingest.file.submit")}
                  </>
                )}
              </Button>
            </div>

            {/* Upload failure retry banner — shown when the previous
                upload attempt failed. The file state is preserved on
                failure so the user can retry without re-selecting the
                file. Provides an explicit, visible retry affordance
                instead of relying on the user to click submit again. */}
            {fileError && !busy && file && (
              <div className="rounded-md border border-red-500/30 bg-red-500/[0.06] p-3 flex items-start gap-3">
                <AlertTriangle className="h-4 w-4 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-red-900 dark:text-red-200">
                    {t("ingest.toast.uploadFailed")}
                  </div>
                  <p className="text-[11px] text-red-700/90 dark:text-red-300/80 mt-0.5 leading-relaxed break-words">
                    {fileError}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 text-xs shrink-0 border-red-500/40 text-red-700 dark:text-red-300 hover:bg-red-500/10"
                  onClick={handleFileIngest}
                  disabled={busy || !legalAck}
                >
                  <RotateCcw className="h-3 w-3" />
                  {t("ingest.file.retry")}
                </Button>
              </div>
            )}

            <MineruHint />
          </CardContent>
        </Card>
      )}

      {result && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <CheckCircle2 className="h-4 w-4 text-emerald-500 dark:text-emerald-400" />
                {t("ingest.result.title")}
              </CardTitle>
              <CardDescription className="mt-1">
                {t("ingest.result.subtitle")}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <Stat label={t("ingest.stat.events")} value={result.events_created} />
              <Stat label={t("ingest.stat.metrics")} value={result.metrics_created} />
              <Stat label={t("ingest.stat.assertions")} value={result.assertions_created} />
              <Stat label={t("ingest.stat.relationships")} value={result.relationships_created} />
              <Stat label={t("ingest.stat.notifications")} value={result.notifications_triggered} />
              <Stat
                label={t("ingest.stat.confidence")}
                value={
                  result.extraction_confidence !== null &&
                  result.extraction_confidence !== undefined
                    ? `${(result.extraction_confidence * 100).toFixed(0)}%`
                    : "—"
                }
              />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-colors",
        active
          ? "bg-brand-500/15 text-brand-700 dark:text-brand-200 border border-brand-500/30"
          : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 border border-transparent"
      )}
    >
      {icon}
      {label}
    </button>
  );
}

/**
 * Network search card — uses the backend Crawler (Tavily) API to search the
 * public web, let the user pick results, then extract + ingest the full
 * content of selected pages in one go.
 */
function SearchCard({
  busy,
  setBusy,
  setResult,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  setResult: (v: any | null) => void;
}) {
  const t = useT();
  const toast = useToast();

  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("general");
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [searched, setSearched] = useState(false);

  async function handleSearch() {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setHits([]);
    setSelected(new Set());
    setSearched(false);
    try {
      const results = (await api.crawlerSearch(q, {
        max_results: 10,
        topic,
      })) as SearchHit[];
      setHits(results);
      setSearched(true);
      if (results.length === 0) {
        toast({
          title: t("ingest.search.empty"),
          description: t("ingest.search.emptyHint"),
          variant: "warning",
        });
      }
    } catch (e: any) {
      toast({
        title: t("ingest.search.failed"),
        description: e?.message,
        variant: "error",
      });
    } finally {
      setSearching(false);
    }
  }

  function toggleSelect(url: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(hits.map((h) => h.url)));
  }

  function selectNone() {
    setSelected(new Set());
  }

  async function handleExtractAndIngest() {
    if (selected.size === 0) return;
    setBusy(true);
    setResult(null);
    try {
      const urls = Array.from(selected);
      const extracted = await api.crawlerExtract({
        urls,
        query: query.trim() || undefined,
        extract_depth: "basic",
        format: "markdown",
      });

      // Ingest each extracted page as a separate text source.
      let totalEvents = 0;
      let totalMetrics = 0;
      let totalAssertions = 0;
      let totalRelationships = 0;
      let totalNotifications = 0;
      let count = 0;
      let lastResult: any = null;

      for (const item of extracted as Array<{
        url: string;
        content: string;
        failed?: boolean;
        error?: string | null;
      }>) {
        if (item.failed || !item.content) continue;
        // Find the original hit to get the title.
        const hit = hits.find((h) => h.url === item.url);
        const res = await api.ingestText({
          text: item.content,
          title: hit?.title ?? item.url,
          source_kind: "public",
          url: item.url,
        });
        count += 1;
        lastResult = res;
        totalEvents += (res as any)?.events_created ?? 0;
        totalMetrics += (res as any)?.metrics_created ?? 0;
        totalAssertions += (res as any)?.assertions_created ?? 0;
        totalRelationships += (res as any)?.relationships_created ?? 0;
        totalNotifications += (res as any)?.notifications_triggered ?? 0;
      }

      if (count === 0) {
        toast({
          title: t("ingest.search.noContent"),
          variant: "error",
        });
      } else {
        const aggregate = {
          ok: true,
          source_id: null,
          events_created: totalEvents,
          metrics_created: totalMetrics,
          assertions_created: totalAssertions,
          relationships_created: totalRelationships,
          extraction_confidence: lastResult?.extraction_confidence ?? null,
          notifications_triggered: totalNotifications,
          error: null,
          warning: null,
        };
        setResult(aggregate);
        toast({
          title: t("ingest.search.ingested", { n: count }),
          variant: "success",
        });
        // Clear selection after successful ingest.
        setSelected(new Set());
      }
    } catch (e: any) {
      toast({
        title: t("ingest.search.ingestFailed"),
        description: e?.message,
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
                <Globe className="h-4 w-4 text-brand-600 dark:text-brand-400" />
                {t("ingest.search.title")}
              </CardTitle>
          <CardDescription className="mt-1">
            {t("ingest.search.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Search bar */}
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSearch();
              }
            }}
            placeholder={t("ingest.search.placeholder")}
            className="flex-1"
          />
          <Select value={topic} onValueChange={setTopic}>
            <SelectTrigger className="h-9 w-28 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="general">{t("ingest.search.topic.general")}</SelectItem>
              <SelectItem value="news">{t("ingest.search.topic.news")}</SelectItem>
              <SelectItem value="finance">{t("ingest.search.topic.finance")}</SelectItem>
            </SelectContent>
          </Select>
          <Button
            onClick={handleSearch}
            disabled={searching || !query.trim()}
          >
            {searching ? (
              <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
            ) : (
              <SearchIcon className="h-4 w-4 mr-1.5" />
            )}
            {t("ingest.search.button")}
          </Button>
        </div>

        {/* Results */}
        {searched && hits.length > 0 && (
          <>
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                {t("ingest.search.resultsCount", { n: hits.length })}
                {selected.size > 0 && (
                  <span className="text-brand-600 dark:text-brand-300 ml-2">
                    · {t("ingest.search.selected", { n: selected.size })}
                  </span>
                )}
              </span>
              <div className="flex gap-2 text-[11px]">
                <button
                  onClick={selectAll}
                  className="text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                >
                  {t("ingest.search.selectAll")}
                </button>
                <span className="text-zinc-400 dark:text-zinc-600">·</span>
                <button
                  onClick={selectNone}
                  className="text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                >
                  {t("ingest.search.selectNone")}
                </button>
              </div>
            </div>

            <ul className="space-y-1.5 max-h-[420px] overflow-y-auto pr-1">
              {hits.map((h) => {
                const checked = selected.has(h.url);
                return (
                  <li
                    key={h.url}
                    className={cn(
                      "flex items-start gap-2.5 rounded-md border px-3 py-2 cursor-pointer transition-colors",
                      checked
                        ? "border-brand-500/40 bg-brand-500/10"
                        : "border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] hover:bg-black/[0.04] dark:hover:bg-white/[0.04]"
                    )}
                    onClick={() => toggleSelect(h.url)}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleSelect(h.url)}
                      onClick={(e) => e.stopPropagation()}
                      className="mt-0.5 accent-brand-500 shrink-0"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">
                          {h.title}
                        </span>
                        <a
                          href={h.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-zinc-500 hover:text-brand-600 dark:hover:text-brand-300 shrink-0"
                          title={h.url}
                        >
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </div>
                      <div className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate mt-0.5">
                        {h.url}
                      </div>
                      {h.content && (
                        <div className="text-xs text-zinc-600 dark:text-zinc-400 mt-1 line-clamp-2">
                          {h.content}
                        </div>
                      )}
                      <div className="flex items-center gap-2 mt-1 text-[10px] text-zinc-500 dark:text-zinc-500">
                        {h.published_at && (
                          <span>
                            {new Date(h.published_at).toLocaleDateString()}
                          </span>
                        )}
                        {h.score > 0 && (
                          <>
                            <span>·</span>
                            <span>
                              {t("ingest.search.relevance", {
                                score: (h.score * 100).toFixed(0),
                              })}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>

            <div className="flex justify-end gap-2">
              <Button
                onClick={handleExtractAndIngest}
                disabled={busy || selected.size === 0}
              >
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                    {t("ingest.search.processing")}
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4 mr-1.5" />
                    {t("ingest.search.ingest", { n: selected.size })}
                  </>
                )}
              </Button>
            </div>
          </>
        )}

        {/* Empty state after search */}
        {searched && hits.length === 0 && !searching && (
          <div className="text-xs text-zinc-500 dark:text-zinc-600 py-6 text-center">
            {t("ingest.search.noResults")}
          </div>
        )}

        {/* Hint before search */}
        {!searched && (
          <div className="text-xs text-zinc-500 dark:text-zinc-600 py-3 flex items-start gap-2">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-500/80 dark:text-amber-400/70" />
            <div>
              {t("ingest.search.hint", {
                settings: t("ingest.file.mineruHintLink"),
              }).split(t("ingest.file.mineruHintLink")).map((part, i, arr) => (
                <span key={i}>
                  {part}
                  {i < arr.length - 1 && (
                    <a href="/settings" className="text-brand-600 dark:text-brand-400 hover:underline">
                      {t("ingest.file.mineruHintLink")}
                    </a>
                  )}
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MineruHint() {
  const t = useT();
  return (
    <div className="flex items-start gap-2 text-[11px] text-zinc-500 dark:text-zinc-400 rounded-md border border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] px-3 py-2">
      <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-500/80 dark:text-amber-400/70" />
      <div>
        {t("ingest.file.mineruHint", {
          settings: t("ingest.file.mineruHintLink"),
        }).split(t("ingest.file.mineruHintLink")).map((part, i, arr) => (
          <span key={i}>
            {part}
            {i < arr.length - 1 && (
              <a href="/settings" className="text-brand-600 dark:text-brand-400 hover:underline">
                {t("ingest.file.mineruHintLink")}
              </a>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md bg-black/[0.03] dark:bg-white/5 px-3 py-2 border border-black/5 dark:border-white/5">
      <div className="text-[10px] text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 mt-0.5">{value}</div>
    </div>
  );
}
