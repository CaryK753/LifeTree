"use client";

import { useEffect, useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";

type PathwayOption = { id: string; name: string };

export function ScenarioCreateDialog({
  open,
  onOpenChange,
  goalId,
  pathways,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  goalId: string;
  pathways: PathwayOption[];
  onCreated: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [pathwayId, setPathwayId] = useState("");
  const [form, setForm] = useState({ name: "", description: "", assumptions: "" });

  useEffect(() => {
    if (open && pathways.length === 1) setPathwayId(pathways[0].id);
  }, [open, pathways]);

  async function handleCreate() {
    if (!form.name.trim() || !pathwayId) return;
    let assumptions: Record<string, unknown> = {};
    if (form.assumptions.trim()) {
      try {
        assumptions = JSON.parse(form.assumptions);
      } catch {
        toast({
          title: t("scenarios.toast.createFailed"),
          description: t("scenarios.invalidJson"),
          variant: "error",
        });
        return;
      }
    }

    setCreating(true);
    try {
      await api.createScenario({
        goal_id: goalId,
        pathway_id: pathwayId,
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        assumptions,
      });
      toast({ title: t("scenarios.toast.created"), variant: "success" });
      setForm({ name: "", description: "", assumptions: "" });
      setPathwayId(pathways.length === 1 ? pathways[0].id : "");
      onOpenChange(false);
      onCreated();
    } catch (error: any) {
      toast({
        title: t("scenarios.toast.createFailed"),
        description: error?.message,
        variant: "error",
      });
    } finally {
      setCreating(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("scenarios.create.title")}</DialogTitle>
          <DialogDescription>{t("scenarios.create.subtitle")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label={t("scenarios.create.pathway")}>
            <Select value={pathwayId} onValueChange={setPathwayId}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder={t("scenarios.create.pathwayPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {pathways.map((pathway) => (
                  <SelectItem key={pathway.id} value={pathway.id}>{pathway.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("scenarios.create.name")}>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder={t("scenarios.create.namePlaceholder")}
              className="h-9 text-sm"
              autoFocus
            />
          </Field>
          <Field label={t("scenarios.create.description")}>
            <Input
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              placeholder={t("scenarios.create.descriptionPlaceholder")}
              className="h-9 text-sm"
            />
          </Field>
          <Field label={t("scenarios.create.assumptions")}>
            <Textarea
              value={form.assumptions}
              onChange={(event) => setForm({ ...form, assumptions: event.target.value })}
              placeholder={t("scenarios.create.assumptionsPlaceholder")}
              className="text-xs font-mono"
              rows={3}
            />
          </Field>
        </div>
        <DialogFooter>
          <DialogClose asChild><Button size="sm" variant="ghost">{t("scenarios.create.cancel")}</Button></DialogClose>
          <Button size="sm" onClick={handleCreate} disabled={!form.name.trim() || !pathwayId || creating}>
            {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <Plus className="h-3.5 w-3.5 mr-1" />}
            {creating ? t("scenarios.create.creating") : t("scenarios.create.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="space-y-1.5"><Label className="text-xs">{label}</Label>{children}</div>;
}
