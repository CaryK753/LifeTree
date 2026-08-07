"use client";

import {
  AlertTriangle,
  ShieldAlert,
  CheckCircle,
  Users,
  Layers,
  FileText,
  ListChecks,
  AlertCircle,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  TeamFinalOutput,
  TeamSpecialistSummary,
} from "@/lib/api";
import { useT } from "@/lib/i18n/provider";

/**
 * TeamResultView — renders the final output produced by the AgentTeam
 * orchestrator's `synthesize` node.
 *
 * Sections: summary → consensus → divergences → gaps → warnings →
 * specialist execution → metadata → honesty disclaimer.
 *
 * The orchestrator's output schema is intentionally flexible
 * (`Array<Record<string, unknown>>` for consensus/divergences/gaps) so
 * each item is rendered as pretty-printed JSON inside a card. The
 * specialist_summaries table is the exception — its fields are stable
 * enough to render as a structured table.
 */
export function TeamResultView({
  result,
}: {
  result: TeamFinalOutput;
}) {
  const t = useT();
  const meta = result.team_metadata;

  return (
    <div className="space-y-4">
      {/* Summary */}
      {result.summary && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4 text-brand-500" />
              {t("agentTeam.result.summary")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-foreground whitespace-pre-wrap">
              {result.summary}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Consensus */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-green-500" />
            {t("agentTeam.result.consensus")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {(result.consensus ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("agentTeam.result.noConsensus")}
            </p>
          ) : (
            (result.consensus ?? []).map((item, i) => (
              <JsonItem key={i} item={item} />
            ))
          )}
        </CardContent>
      </Card>

      {/* Divergences */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            {t("agentTeam.result.divergences")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {(result.divergences ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("agentTeam.result.noDivergences")}
            </p>
          ) : (
            (result.divergences ?? []).map((item, i) => (
              <JsonItem key={i} item={item} />
            ))
          )}
        </CardContent>
      </Card>

      {/* Gaps */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-brand-500" />
            {t("agentTeam.result.gaps")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {(result.gaps ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("agentTeam.result.noGaps")}
            </p>
          ) : (
            (result.gaps ?? []).map((item, i) => (
              <JsonItem key={i} item={item} />
            ))
          )}
        </CardContent>
      </Card>

      {/* Warnings */}
      {(result.warnings ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-amber-500" />
              {t("agentTeam.result.warnings")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {(result.warnings ?? []).map((w, i) => (
              <div
                key={i}
                className="text-xs text-amber-700 dark:text-amber-300"
              >
                ⚠️ {w}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Specialist execution */}
      {(result.specialist_summaries ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Users className="h-4 w-4 text-brand-500" />
              {t("agentTeam.result.specialists")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <SpecialistTable
              specialists={result.specialist_summaries ?? []}
              t={t}
            />
          </CardContent>
        </Card>
      )}

      {/* Metadata */}
      {meta && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Layers className="h-4 w-4 text-brand-500" />
              {t("agentTeam.result.metadata")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
              <MetaItem
                label={t("agentTeam.result.totalLlmCalls")}
                value={meta.total_llm_calls}
              />
              <MetaItem
                label={t("agentTeam.result.failureCount")}
                value={meta.failure_count}
              />
              <MetaItem
                label={t("agentTeam.result.iterations")}
                value={result.iterations}
              />
              <MetaItem
                label={t("agentTeam.result.specialistCount")}
                value={result.specialist_count}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Honesty disclaimer */}
      {meta?.honesty_disclaimer && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-4 py-3 flex items-start gap-3">
          <ShieldAlert className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
          <div>
            <div className="text-xs font-medium text-amber-800 dark:text-amber-200">
              {t("agentTeam.result.disclaimer")}
            </div>
            <div className="text-xs text-amber-700 dark:text-amber-300 mt-1">
              {meta.honesty_disclaimer}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * JsonItem — pretty-prints a flexible record from the orchestrator output.
 *
 * The consensus/divergences/gaps arrays contain items whose shape varies
 * by template (e.g. cross_domain_research produces {topic, finding,
 * supporting_specialists}, while multi_pathway_compare produces
 * {pathway, pros, cons}). Rather than hard-code every variant, we render
 * the raw JSON in a <pre> block — readable for both developers and
 * advanced users, and resilient to backend schema evolution.
 */
function JsonItem({ item }: { item: Record<string, unknown> }) {
  return (
    <div className="rounded-md border border-black/5 dark:border-white/10 p-2.5">
      <pre className="text-xs text-foreground whitespace-pre-wrap break-words font-mono">
        {JSON.stringify(item, null, 2)}
      </pre>
    </div>
  );
}

function SpecialistTable({
  specialists,
  t,
}: {
  specialists: TeamSpecialistSummary[];
  t: (k: string) => string;
}) {
  return (
    <div className="overflow-x-auto -mx-2">
      <table className="w-full text-xs min-w-[640px]">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-black/5 dark:border-white/10">
            <th className="py-1.5 px-2 font-medium">
              {t("agentTeam.result.role")}
            </th>
            <th className="py-1.5 px-2 font-medium">
              {t("agentTeam.result.status")}
            </th>
            <th className="py-1.5 px-2 font-medium text-right">
              {t("agentTeam.result.toolCalls")}
            </th>
            <th className="py-1.5 px-2 font-medium text-right">
              {t("agentTeam.result.llmCalls")}
            </th>
            <th className="py-1.5 px-2 font-medium text-right">
              {t("agentTeam.result.sources")}
            </th>
            <th className="py-1.5 px-2 font-medium text-right">
              {t("agentTeam.result.assertions")}
            </th>
          </tr>
        </thead>
        <tbody>
          {specialists.map((s, i) => {
            const failed = s.status === "failed";
            return (
              <tr
                key={i}
                className="border-b border-black/5 dark:border-white/5 last:border-0"
              >
                <td className="py-1.5 px-2 font-medium text-foreground">
                  {s.role ?? "—"}
                </td>
                <td
                  className={
                    "py-1.5 px-2 " +
                    (failed
                      ? "text-red-600 dark:text-red-400"
                      : "text-green-600 dark:text-green-400")
                  }
                >
                  {s.status ?? "—"}
                </td>
                <td className="py-1.5 px-2 text-right tabular-nums">
                  {s.tool_calls ?? 0}
                </td>
                <td className="py-1.5 px-2 text-right tabular-nums">
                  {s.llm_calls ?? 0}
                </td>
                <td className="py-1.5 px-2 text-right tabular-nums">
                  {s.sources_count ?? 0}
                </td>
                <td className="py-1.5 px-2 text-right tabular-nums">
                  {s.assertions_count ?? 0}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MetaItem({
  label,
  value,
}: {
  label: string;
  value?: number | null;
}) {
  return (
    <div className="rounded-md border border-black/5 dark:border-white/10 px-2 py-1.5">
      <div className="text-muted-foreground text-[10px]">{label}</div>
      <div className="font-medium">{value ?? "—"}</div>
    </div>
  );
}
