"use client";

import { useState } from "react";
import { Bot, Loader2, AlertCircle, Users, GitBranch, ShieldAlert, Repeat } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useTeamTemplates, useSettings } from "@/lib/hooks";
import { api, type TeamJobSummary, type TeamTemplateInfo } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/**
 * AgentTeamLauncher — input form for starting a new AgentTeam job.
 *
 * Shows an objective textarea, a template picker (5 predefined templates),
 * and a submit button. The template picker renders as a row of cards
 * with icon + name + description, so the user can see what each team
 * template does before picking one.
 */
export function AgentTeamLauncher({
  onCreated,
}: {
  onCreated?: (job: TeamJobSummary) => void;
}) {
  const t = useT();
  const toast = useToast();
  const { data, isLoading } = useTeamTemplates();
  const { data: settingsData } = useSettings();
  const [objective, setObjective] = useState("");
  const [template, setTemplate] = useState<string>(
    "cross_domain_research"
  );
  const [submitting, setSubmitting] = useState(false);

  const templates = data?.templates ?? [];

  function templateIcon(name: string) {
    switch (name) {
      case "independent_validation":
        return ShieldAlert;
      case "multi_pathway_compare":
        return GitBranch;
      case "risk_scan":
        return ShieldAlert;
      case "iterative_research":
        return Repeat;
      default:
        return Users;
    }
  }

  async function handleSubmit() {
    const q = objective.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    try {
      const job = await api.createTeamJob({
        objective: q,
        template,
      });
      toast({ title: t("agentTeam.toast.created"), variant: "success" });
      setObjective("");
      onCreated?.(job);
    } catch (err: any) {
      toast({
        title: t("agentTeam.toast.createFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setSubmitting(false);
    }
  }

  // No chat model configured — agent team requires an LLM.
  if (!settingsData?.roles_configured?.chat) {
    return (
      <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-4 py-3 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
        <p className="text-sm text-amber-800 dark:text-amber-200">
          {t("agentTeam.launcher.noChatModel")}
        </p>
      </div>
    );
  }

  // Templates endpoint failed or returned empty — show a warning.
  if (!isLoading && templates.length === 0) {
    return (
      <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-4 py-3 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
        <p className="text-sm text-amber-800 dark:text-amber-200">
          {t("agentTeam.launcher.noTemplates")}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-black/5 dark:border-white/10 bg-surface/60 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Bot className="h-4 w-4 text-brand-500" />
        <h2 className="text-sm font-semibold">{t("agentTeam.launcher.title")}</h2>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs text-muted-foreground">
          {t("agentTeam.launcher.objectiveLabel")}
        </label>
        <Textarea
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          placeholder={t("agentTeam.launcher.objectivePlaceholder")}
          rows={3}
          className="resize-none"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handleSubmit();
            }
          }}
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-xs text-muted-foreground">
          {t("agentTeam.launcher.templateLabel")}
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {templates.map((tpl: TeamTemplateInfo) => {
            const Icon = templateIcon(tpl.name);
            const active = template === tpl.name;
            return (
              <button
                key={tpl.name}
                type="button"
                onClick={() => setTemplate(tpl.name)}
                className={cn(
                  "text-left p-2.5 rounded-md border transition-colors space-y-1",
                  active
                    ? "border-brand-500/40 bg-brand-500/10 text-brand-700 dark:text-brand-300"
                    : "border-black/5 dark:border-white/10 text-zinc-500 dark:text-zinc-400 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]"
                )}
              >
                <div className="flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="text-xs font-medium truncate">
                    {t(`agentTeam.template.${tpl.name}`) ===
                    `agentTeam.template.${tpl.name}`
                      ? tpl.name
                      : t(`agentTeam.template.${tpl.name}`)}
                  </span>
                </div>
                <p className="text-[11px] leading-tight opacity-80 line-clamp-2">
                  {t(
                    `agentTeam.template.${tpl.name}.description`
                  ) ===
                  `agentTeam.template.${tpl.name}.description`
                    ? tpl.description
                    : t(`agentTeam.template.${tpl.name}.description`)}
                </p>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <Button
          onClick={handleSubmit}
          disabled={!objective.trim() || submitting || isLoading}
          size="sm"
          className="gap-1.5"
        >
          {submitting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Bot className="h-3.5 w-3.5" />
          )}
          {submitting
            ? t("agentTeam.launcher.submitting")
            : t("agentTeam.launcher.submit")}
        </Button>
      </div>
    </div>
  );
}
