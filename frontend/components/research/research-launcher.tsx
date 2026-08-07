"use client";

import { useState } from "react";
import { Search, Loader2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useResearchEngines, useSettings } from "@/lib/hooks";
import { api, type ResearchJobSummary } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/**
 * ResearchLauncher — input form for starting a new deep research job.
 *
 * Shows a question textarea, an engine multi-select (only engines with
 * configured API keys), and a submit button. When no engines are
 * configured, renders a warning instead of the form.
 */
export function ResearchLauncher({
  onCreated,
}: {
  onCreated?: (job: ResearchJobSummary) => void;
}) {
  const t = useT();
  const toast = useToast();
  const { data, isLoading } = useResearchEngines();
  const { data: settingsData } = useSettings();
  const [question, setQuestion] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const engines = (data?.engines ?? []).filter((e) => e.available);

  function toggleEngine(name: string) {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  }

  function engineLabel(name: string): string {
    const key = `research.engine.${name}`;
    const label = t(key);
    return label === key ? name : label;
  }

  async function handleSubmit() {
    const q = question.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    try {
      const job = await api.createResearchJob({
        question: q,
        engines: selected.length > 0 ? selected : null,
      });
      toast({ title: t("research.toast.created"), variant: "success" });
      setQuestion("");
      setSelected([]);
      onCreated?.(job);
    } catch (err: any) {
      toast({
        title: t("research.toast.createFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setSubmitting(false);
    }
  }

  // No chat model configured — deep research requires an LLM.
  if (!settingsData?.roles_configured?.chat) {
    return (
      <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-4 py-3 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
        <p className="text-sm text-amber-800 dark:text-amber-200">
          {t("research.launcher.noChatModel")}
        </p>
      </div>
    );
  }

  // No engines configured — show a warning instead of the form.
  if (!isLoading && engines.length === 0) {
    return (
      <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-4 py-3 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
        <p className="text-sm text-amber-800 dark:text-amber-200">
          {t("research.launcher.noEngines")}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-black/5 dark:border-white/10 bg-surface/60 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 text-brand-500" />
        <h2 className="text-sm font-semibold">{t("research.launcher.title")}</h2>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs text-muted-foreground">
          {t("research.launcher.questionLabel")}
        </label>
        <Textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t("research.launcher.questionPlaceholder")}
          rows={2}
          className="resize-none"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handleSubmit();
            }
          }}
        />
      </div>

      {engines.length > 0 && (
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">
            {t("research.launcher.enginesLabel")}
            <span className="ml-1 opacity-60">
              ({t("research.launcher.enginesHint")})
            </span>
          </label>
          <div className="flex flex-wrap gap-1.5">
            {engines.map((e) => {
              const active = selected.includes(e.name);
              return (
                <button
                  key={e.name}
                  type="button"
                  onClick={() => toggleEngine(e.name)}
                  className={cn(
                    "px-2.5 py-1 rounded-md border text-xs transition-colors",
                    active
                      ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-300"
                      : "border-black/5 dark:border-white/10 text-zinc-500 dark:text-zinc-400 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]"
                  )}
                >
                  {engineLabel(e.name)}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <Button
          onClick={handleSubmit}
          disabled={!question.trim() || submitting || isLoading}
          size="sm"
          className="gap-1.5"
        >
          {submitting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Search className="h-3.5 w-3.5" />
          )}
          {submitting
            ? t("research.launcher.submitting")
            : t("research.launcher.submit")}
        </Button>
      </div>
    </div>
  );
}
