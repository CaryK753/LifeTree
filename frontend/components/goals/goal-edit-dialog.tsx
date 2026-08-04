"use client";

/**
 * Goal edit / delete dialog.
 *
 * Wraps a Radix Dialog with a form for editing the editable fields of a
 * Goal (title, description, scenario, target_date, status) plus a
 * destructive "Delete" action with a second confirmation step.
 *
 * Calls `api.updateGoal` / `api.deleteGoal`. The caller is responsible
 * for refreshing any SWR caches via `mutate` (passed in as `onSaved` /
 * `onDeleted` callbacks).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DateInput } from "@/components/ui/date-input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Trash2, AlertTriangle, Loader2 } from "lucide-react";
import { api, ALL_GOAL_STATUSES, type GoalStatus } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

const SCENARIO_VALUES = ["fsw", "uk-study", "job-switch", "house", "generic"];

export interface GoalEditState {
  id: string;
  title: string;
  description: string;
  scenario: string;
  target_date: string;       // ISO yyyy-mm-dd or ""
  status: GoalStatus;
}

export function GoalEditDialog({
  open,
  onOpenChange,
  goal,
  onSaved,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  goal: GoalEditState | null;
  onSaved?: (newStatus?: string) => void;
  onDeleted?: () => void;
}) {
  const t = useT();
  const router = useRouter();
  const toast = useToast();

  const [form, setForm] = useState<GoalEditState | null>(goal);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Sync local form whenever the dialog opens with a new goal.
  useEffect(() => {
    if (open && goal) {
      setForm({ ...goal });
      setConfirmDelete(false);
    }
  }, [open, goal]);

  if (!form) return null;

  async function handleSave() {
    if (!form) return;
    setSaving(true);
    try {
      await api.updateGoal(form.id, {
        title: form.title,
        description: form.description || null,
        scenario: form.scenario,
        target_date: form.target_date || null,
        status: form.status,
      });
      toast({ title: t("goals.toast.updated"), variant: "success" });
      onSaved?.(form.status);
      onOpenChange(false);
    } catch (e: any) {
      toast({
        title: t("goals.toast.updateFailed"),
        description: e?.message ?? "",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!form) return;
    setDeleting(true);
    try {
      await api.deleteGoal(form.id);
      toast({ title: t("goals.toast.deleted"), variant: "success" });
      onDeleted?.();
      onOpenChange(false);
      // Navigate back to the goals list since this page no longer exists.
      router.push("/goals");
    } catch (e: any) {
      toast({
        title: t("goals.toast.deleteFailed"),
        description: e?.message ?? "",
        variant: "error",
      });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{t("goal.edit.title")}</DialogTitle>
          <DialogDescription>{t("goal.edit.subtitle")}</DialogDescription>
        </DialogHeader>

        {!confirmDelete ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 py-2">
              <div className="space-y-1.5 md:col-span-2">
                <Label>{t("goals.form.titleLabel")}</Label>
                <Input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder={t("goals.form.titlePlaceholder")}
                />
              </div>

              <div className="space-y-1.5">
                <Label>{t("goals.form.scenario")}</Label>
                <Select
                  value={form.scenario}
                  onValueChange={(v) => setForm({ ...form, scenario: v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("goals.form.scenarioPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {SCENARIO_VALUES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {t(`scenario.${s}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label>{t("goals.form.targetDate")}</Label>
                <DateInput
                  value={form.target_date}
                  onChange={(e) => setForm({ ...form, target_date: e.target.value })}
                  label={t("goals.form.targetDate")}
                />
              </div>

              <div className="space-y-1.5 md:col-span-2">
                <Label>{t("goal.edit.status")}</Label>
                <Select
                  value={form.status}
                  onValueChange={(v) => setForm({ ...form, status: v as GoalStatus })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ALL_GOAL_STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {t(`status.${s}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-zinc-500 mt-0.5">
                  {t("goal.edit.statusHint")}
                </p>
              </div>

              <div className="space-y-1.5 md:col-span-2">
                <Label>{t("goals.form.description")}</Label>
                <Textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder={t("goals.form.descriptionPlaceholder")}
                  rows={3}
                />
              </div>
            </div>

            <DialogFooter className="flex !flex-row !justify-between">
              <Button
                variant="ghost"
                className="text-red-400 hover:bg-red-500/10 hover:text-red-300"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="h-4 w-4 mr-1.5" />
                {t("goal.edit.delete")}
              </Button>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => onOpenChange(false)}>
                  {t("common.cancel")}
                </Button>
                <Button
                  onClick={handleSave}
                  disabled={saving || !form.title}
                >
                  {saving ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                      {t("goal.edit.saving")}
                    </>
                  ) : (
                    t("goal.edit.save")
                  )}
                </Button>
              </div>
            </DialogFooter>
          </>
        ) : (
          <>
            <div className="py-4 space-y-3">
              <div className="flex items-start gap-3 p-3 rounded-md bg-red-500/10 border border-red-500/30">
                <AlertTriangle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <div className="text-sm font-medium text-red-200">
                    {t("goal.edit.deleteConfirmTitle", { title: form.title })}
                  </div>
                  <div className="text-xs text-red-200/80">
                    {t("goal.edit.deleteConfirm")}
                  </div>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                variant="destructive"
                onClick={handleDelete}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                {deleting ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                    {t("goal.edit.deleting")}
                  </>
                ) : (
                  <>
                    <Trash2 className="h-4 w-4 mr-1.5" />
                    {t("goal.edit.delete")}
                  </>
                )}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
