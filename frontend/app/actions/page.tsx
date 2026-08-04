"use client";

import { useMemo, useState } from "react";
import {
  useTodayActions,
  useROIActions,
  useGoals,
} from "@/lib/hooks";
import {
  api,
  type ActionRead,
  type ActionStatus,
  type ActionCreate,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { Input } from "@/components/ui/input";
import { DateInput } from "@/components/ui/date-input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  ListTodo,
  Plus,
  Loader2,
  CalendarDays,
  Check,
  Trash2,
  TrendingUp,
  Clock,
  Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

// Returns today's date as a `YYYY-MM-DD` string in the user's local
// timezone. ISO date strings sort lexicographically, so a simple string
// comparison (`due_at < todayLocalISO()`) correctly detects overdue items.
function todayLocalISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isOverdue(a: ActionRead): boolean {
  if (!a.due_at) return false;
  if (a.status === "completed" || a.status === "skipped") return false;
  return a.due_at < todayLocalISO();
}

// Builds the i18n key for a status label: "in_progress" → "actions.statusInProgress".
function statusKey(status: string): string {
  const pascal = status
    .split("_")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join("");
  return `actions.status${pascal}`;
}

type StatusFilter = "all" | ActionStatus;

// Filter options exposed in the status dropdown (per spec: all/pending/
// in_progress/completed). The today endpoint only returns pending and
// in_progress rows, so "completed" yields an empty list — the correct
// signal that no completed actions are due today.
const FILTER_STATUSES: ActionStatus[] = [
  "pending",
  "in_progress",
  "completed",
];

const STAGE_TONES: Record<string, string> = {
  research: "border-sky-500/30 bg-sky-500/[0.07] text-sky-700 dark:text-sky-300",
  plan: "border-violet-500/30 bg-violet-500/[0.07] text-violet-700 dark:text-violet-300",
  execute: "border-brand-500/30 bg-brand-500/[0.07] text-brand-700 dark:text-brand-300",
  review: "border-amber-500/30 bg-amber-500/[0.07] text-amber-700 dark:text-amber-300",
};

function stageTone(stage?: string | null): string {
  if (!stage) return "";
  return STAGE_TONES[stage] ?? "border-black/10 dark:border-white/10 bg-black/[0.04] dark:bg-white/5 text-zinc-700 dark:text-zinc-300";
}

const EMPTY_FORM: ActionForm = {
  title: "",
  description: "",
  goal_id: "",
  due_at: "",
  stage: "",
  cost: "0.5",
  expected_prob_lift: "0",
};

type ActionForm = {
  title: string;
  description: string;
  goal_id: string;
  due_at: string;
  stage: string;
  cost: string;
  expected_prob_lift: string;
};

export default function ActionsPage() {
  const t = useT();
  const toast = useToast();
  const { data: goals } = useGoals();
  const goalList = (goals ?? []) as Array<{ id: string; title: string }>;

  // Goal filter — passed server-side to the today endpoint so it refetches.
  const [goalFilter, setGoalFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const goalId = goalFilter !== "all" ? goalFilter : undefined;
  const { data: todayActions, isLoading, mutate: mutateToday } = useTodayActions(goalId);
  const { data: roiData, mutate: mutateROI } = useROIActions(5);

  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<ActionForm>(EMPTY_FORM);

  // Delete confirmation state.
  const [deleteTarget, setDeleteTarget] = useState<ActionRead | null>(null);

  // Client-side status filter on top of the today list. The today endpoint
  // only returns pending/in_progress, so "completed" yields an empty list —
  // which is the correct signal that no completed actions are due today.
  const filtered = useMemo(() => {
    const list = (todayActions ?? []) as ActionRead[];
    if (statusFilter === "all") return list;
    return list.filter((a) => a.status === statusFilter);
  }, [todayActions, statusFilter]);

  // Max ROI in the visible list — used to scale the ROI bars relative to
  // the highest-leverage action so the bars stay meaningful even when all
  // ROIs are small.
  const maxRoi = useMemo(() => {
    const list = (todayActions ?? []) as ActionRead[];
    const m = Math.max(...list.map((a) => a.roi ?? 0), 0);
    return m > 0 ? m : 1;
  }, [todayActions]);

  async function handleCreate() {
    if (!form.title || !form.goal_id) return;
    setSaving(true);
    try {
      const payload: ActionCreate = {
        goal_id: form.goal_id,
        title: form.title,
        description: form.description || null,
        due_at: form.due_at || null,
        stage: form.stage || null,
        cost: Number(form.cost) || 0,
        expected_prob_lift: Number(form.expected_prob_lift) || 0,
      };
      await api.createAction(payload);
      toast({ title: t("actions.save"), variant: "success" });
      setForm(EMPTY_FORM);
      mutateToday();
      mutateROI();
      setShowForm(false);
    } catch (e: any) {
      toast({
        title: t("actions.save"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleComplete(action: ActionRead) {
    // Optimistic: remove from today list immediately, then reconcile.
    const prev = todayActions;
    mutateToday(
      ((todayActions ?? []) as ActionRead[]).filter((a) => a.id !== action.id),
      { revalidate: false }
    );
    try {
      await api.completeAction(action.id);
      toast({ title: t("actions.completed"), variant: "success" });
      mutateToday();
      mutateROI();
    } catch (e: any) {
      // Roll back on failure.
      mutateToday(prev, { revalidate: false });
      toast({
        title: t("actions.save"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await api.deleteAction(deleteTarget.id);
      toast({ title: t("actions.delete"), variant: "success" });
      mutateToday();
      mutateROI();
    } catch (e: any) {
      toast({
        title: t("actions.delete"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setDeleteTarget(null);
    }
  }

  const roiActions = (roiData?.actions ?? []) as ActionRead[];

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <ListTodo className="h-6 w-6 text-brand-600 dark:text-brand-400" />
            {t("actions.title")}
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            {t("actions.today")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="icon"
            variant="outline"
            title="导出 ICS 日历"
            onClick={() => api.downloadActionCalendar()}
          >
            <Download className="h-4 w-4" />
          </Button>
          <Button onClick={() => setShowForm(true)}>
            <Plus className="h-4 w-4 mr-1.5" /> {t("actions.new")}
          </Button>
        </div>
      </header>

      {/* Create action dialog */}
      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("actions.new")}</DialogTitle>
            <DialogDescription>{t("actions.title")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>{t("actions.titleField")}</Label>
              <Input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder={t("actions.titleField")}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("actions.goal")}</Label>
              <Select
                value={form.goal_id}
                onValueChange={(v) => setForm({ ...form, goal_id: v })}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t("actions.goal")} />
                </SelectTrigger>
                <SelectContent>
                  {goalList.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>{t("actions.due")}</Label>
                <DateInput
                  value={form.due_at}
                  onChange={(e) => setForm({ ...form, due_at: e.target.value })}
                  label={t("actions.due")}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("actions.stage")}</Label>
                <Input
                  value={form.stage}
                  onChange={(e) => setForm({ ...form, stage: e.target.value })}
                  placeholder="research / plan / execute / review"
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("actions.cost")}</Label>
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  value={form.cost}
                  onChange={(e) => setForm({ ...form, cost: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("actions.lift")}</Label>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={form.expected_prob_lift}
                  onChange={(e) => setForm({ ...form, expected_prob_lift: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>{t("actions.description")}</Label>
              <Textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">{t("actions.cancel")}</Button>
            </DialogClose>
            <Button onClick={handleCreate} disabled={saving || !form.title || !form.goal_id}>
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
              ) : (
                <Plus className="h-4 w-4 mr-1.5" />
              )}
              {saving ? t("common.loading") : t("actions.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <Select
          value={goalFilter}
          onValueChange={(v) => setGoalFilter(v)}
        >
          <SelectTrigger className="h-9 w-44 text-xs">
            <SelectValue placeholder={t("actions.goal")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("actions.all")}</SelectItem>
            {goalList.map((g) => (
              <SelectItem key={g.id} value={g.id}>
                {g.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as StatusFilter)}
        >
          <SelectTrigger className="h-9 w-36 text-xs">
            <SelectValue placeholder={t("actions.status")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("actions.all")}</SelectItem>
            {FILTER_STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                {t(statusKey(s))}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Two-column layout: today's actions (main) + top ROI (side).
          Wrapped in ErrorBoundary so a render-level failure in either
          column (e.g. a malformed action row) doesn't blank the whole
          page — the header / filter bar / create dialog stay usable
          and the user can retry via the boundary's "重试" button. */}
      <ErrorBoundary>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Main column — Today's Actions */}
          <div className="lg:col-span-2 space-y-3">
            {isLoading && !todayActions ? (
              <div className="space-y-3">
                {[0, 1, 2].map((i) => (
                  <Card key={i} className="opacity-80">
                    <CardContent className="p-4 space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-5 w-16 rounded-full" />
                      </div>
                      <Skeleton className="h-3 w-full" />
                      <Skeleton className="h-2 w-1/3" />
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center space-y-3">
                  <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center">
                    <ListTodo className="h-6 w-6 text-brand-600 dark:text-brand-400" />
                  </div>
                  <div className="text-sm text-zinc-700 dark:text-zinc-300">
                    {t("actions.empty")}
                  </div>
                </CardContent>
              </Card>
            ) : (
              filtered.map((a) => (
                <ActionCard
                  key={a.id}
                  action={a}
                  maxRoi={maxRoi}
                  onComplete={() => handleComplete(a)}
                  onDelete={() => setDeleteTarget(a)}
                />
              ))
            )}
          </div>

          {/* Side column — Top ROI */}
          <div className="space-y-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-brand-400" />
                  {t("actions.topROI")}
                </CardTitle>
                <CardDescription>{t("actions.roi")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {roiActions.length === 0 ? (
                  <div className="text-xs text-zinc-500 py-3 text-center">
                    {t("actions.empty")}
                  </div>
                ) : (
                  roiActions.map((a) => (
                    <div
                      key={a.id}
                      className="flex items-center gap-2 rounded-md border border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] px-2.5 py-2"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate">
                          {a.title}
                        </div>
                        <div className="text-[10px] text-zinc-500 mt-0.5">
                          {t("actions.roi")}: {(a.roi ?? 0).toFixed(2)}
                        </div>
                      </div>
                      <div className="shrink-0 w-16">
                        <RoiBar value={a.roi ?? 0} max={maxRoi} compact />
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </ErrorBoundary>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={t("actions.delete")}
        description={t("actions.deleteConfirm")}
        confirmLabel={t("actions.delete")}
        cancelLabel={t("actions.cancel")}
        variant="danger"
        onConfirm={handleDelete}
      />
    </div>
  );
}

function ActionCard({
  action,
  maxRoi,
  onComplete,
  onDelete,
}: {
  action: ActionRead;
  maxRoi: number;
  onComplete: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  const [completing, setCompleting] = useState(false);
  const overdue = isOverdue(action);
  const statusLabel = t(statusKey(action.status));

  async function onCompleteClick() {
    setCompleting(true);
    try {
      await onComplete();
    } finally {
      setCompleting(false);
    }
  }

  return (
    <Card className={cn(overdue && "border-red-500/30")}>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 break-words">
                {action.title}
              </h3>
              {action.stage && (
                <Badge className={cn("shrink-0", stageTone(action.stage))}>
                  {action.stage}
                </Badge>
              )}
              <Badge variant="default" className="shrink-0 text-[10px]">
                {statusLabel}
              </Badge>
            </div>
            {action.description && (
              <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-1.5 leading-relaxed line-clamp-2">
                {action.description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onDelete}
            aria-label={t("actions.delete")}
            className="shrink-0 rounded-md p-1.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* ROI bar */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[10px] text-zinc-500 dark:text-zinc-400">
            <span className="inline-flex items-center gap-1">
              <TrendingUp className="h-3 w-3" />
              {t("actions.roi")}
            </span>
            <span className="font-medium text-zinc-700 dark:text-zinc-300">
              {(action.roi ?? 0).toFixed(2)}
            </span>
          </div>
          <RoiBar value={action.roi ?? 0} max={maxRoi} />
        </div>

        {/* Footer: due date + complete button */}
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="flex items-center gap-3 text-[11px]">
            {action.due_at && (
              <span
                className={cn(
                  "inline-flex items-center gap-1",
                  overdue
                    ? "text-red-600 dark:text-red-400 font-medium"
                    : "text-zinc-500 dark:text-zinc-400"
                )}
              >
                {overdue ? <Clock className="h-3 w-3" /> : <CalendarDays className="h-3 w-3" />}
                {action.due_at}
                {overdue && <span className="ml-0.5">{t("actions.overdue")}</span>}
              </span>
            )}
            <span className="inline-flex items-center gap-1 text-zinc-500 dark:text-zinc-400">
              {t("actions.cost")}: {action.cost ?? 0}
            </span>
            <span className="inline-flex items-center gap-1 text-zinc-500 dark:text-zinc-400">
              {t("actions.lift")}: {action.expected_prob_lift ?? 0}
            </span>
          </div>
          <Button
            size="sm"
            variant={action.status === "completed" ? "secondary" : "default"}
            onClick={onCompleteClick}
            disabled={completing || action.status === "completed"}
          >
            {completing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <Check className="h-3.5 w-3.5 mr-1" />
            )}
            {action.status === "completed" ? t("actions.completed") : t("actions.complete")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RoiBar({
  value,
  max,
  compact,
}: {
  value: number;
  max: number;
  compact?: boolean;
}) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div
      className={cn(
        "w-full rounded-full bg-black/[0.06] dark:bg-white/5 overflow-hidden",
        compact ? "h-1.5" : "h-2"
      )}
    >
      <div
        className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-400 transition-[width] duration-300"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
