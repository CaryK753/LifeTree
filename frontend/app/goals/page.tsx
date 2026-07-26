"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useGoals } from "@/lib/hooks";
import { api, ALL_GOAL_STATUSES, type GoalStatus } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
import { Compass, Plus, ArrowRight, Calendar, Tag, Search, FilterX, Loader2 } from "lucide-react";
import { formatDate } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

const SCENARIO_VALUES = ["fsw", "uk-study", "job-switch", "house", "generic"] as const;

type StatusFilter = "all" | GoalStatus;
type ScenarioFilter = "all" | (typeof SCENARIO_VALUES)[number];

export default function GoalsPage() {
  const { data: goals, mutate, isLoading } = useGoals();
  const t = useT();
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    title: "",
    description: "",
    scenario: "generic",
    target_date: "",
  });
  const toast = useToast();

  // Search + filters
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [scenarioFilter, setScenarioFilter] = useState<ScenarioFilter>("all");

  const allGoals = (goals ?? []) as any[];

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allGoals.filter((g) => {
      if (statusFilter !== "all" && g.status !== statusFilter) return false;
      if (scenarioFilter !== "all" && g.scenario !== scenarioFilter) return false;
      if (q) {
        const haystack = `${g.title ?? ""} ${g.description ?? ""}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [allGoals, query, statusFilter, scenarioFilter]);

  const isFiltering =
    query.trim() !== "" || statusFilter !== "all" || scenarioFilter !== "all";

  function clearFilters() {
    setQuery("");
    setStatusFilter("all");
    setScenarioFilter("all");
  }

  async function handleCreate() {
    if (!form.title) return;
    setSaving(true);
    try {
      await api.createGoal({
        ...form,
        target_date: form.target_date || null,
      });
      toast({ title: t("goals.toast.created"), variant: "success" });
      setForm({
        title: "",
        description: "",
        scenario: "generic",
        target_date: "",
      });
      mutate();
      setShowForm(false);
    } catch (e: any) {
      toast({
        title: t("goals.toast.createFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <Compass className="h-6 w-6 text-brand-600 dark:text-brand-400" />
            {t("goals.title")}
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">{t("goals.subtitle")}</p>
        </div>
        <Button onClick={() => setShowForm(true)}>
          <Plus className="h-4 w-4 mr-1.5" /> {t("goals.newGoal")}
        </Button>
      </header>

      {/* Create goal dialog — replaces the inline form. Keeps the page
          layout stable (no card pushing the list down) and matches the
          pattern used by the scenarios page. */}
      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("goals.form.title")}</DialogTitle>
            <DialogDescription>{t("goals.form.subtitle")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>{t("goals.form.titleLabel")}</Label>
                <Input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder={t("goals.form.titlePlaceholder")}
                  autoFocus
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
              <div className="space-y-1.5 md:col-span-2">
                <Label>{t("goals.form.targetDate")}</Label>
                <Input
                  type="date"
                  value={form.target_date}
                  onChange={(e) => setForm({ ...form, target_date: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>{t("goals.form.description")}</Label>
              <Textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder={t("goals.form.descriptionPlaceholder")}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">{t("common.cancel")}</Button>
            </DialogClose>
            <Button onClick={handleCreate} disabled={saving || !form.title}>
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
              ) : (
                <Plus className="h-4 w-4 mr-1.5" />
              )}
              {saving ? t("goals.form.creating") : t("goals.form.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Search + filters toolbar — only show when there are goals */}
      {allGoals.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500 pointer-events-none" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("goals.list.searchPlaceholder")}
              className="h-9 pl-8 text-sm"
            />
          </div>
          <Select
            value={statusFilter}
            onValueChange={(v) => setStatusFilter(v as StatusFilter)}
          >
            <SelectTrigger className="h-9 w-32 text-xs">
              <SelectValue placeholder={t("goals.list.filterStatus")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("goals.list.filterAll")}</SelectItem>
              {ALL_GOAL_STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {t(`status.${s}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={scenarioFilter}
            onValueChange={(v) => setScenarioFilter(v as ScenarioFilter)}
          >
            <SelectTrigger className="h-9 w-32 text-xs">
              <SelectValue placeholder={t("goals.list.filterScenario")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("goals.list.filterAll")}</SelectItem>
              {SCENARIO_VALUES.map((s) => (
                <SelectItem key={s} value={s}>
                  {t(`scenario.${s}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {isFiltering && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearFilters}
              className="h-9 text-xs"
            >
              <FilterX className="h-3.5 w-3.5 mr-1" />
              {t("goals.list.clearFilters")}
            </Button>
          )}
          <div className="ml-auto text-[11px] text-zinc-500 dark:text-zinc-400">
            {isFiltering
              ? t("goals.list.countFiltered", {
                  n: filtered.length,
                  total: allGoals.length,
                })
              : t("goals.list.count", { n: allGoals.length })}
          </div>
        </div>
      )}

      {isLoading && <div className="text-sm text-zinc-500 dark:text-zinc-400">{t("common.loading")}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filtered.map((g: any) => {
          const statusRisk: "low" | "medium" | "high" =
            g.status === "active" ? "low"
            : g.status === "achieved" ? "low"
            : g.status === "paused" ? "medium"
            : g.status === "draft" ? "medium"
            : "high";
          return (
          <Link key={g.id} href={`/goals/${g.id}`} className="block group">
            <Card className="hover:border-brand-500/40 transition-colors h-full">
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="truncate">{g.title}</CardTitle>
                  {g.status && (
                    <Badge variant="risk" riskLevel={statusRisk} className="shrink-0">
                      {t(`status.${g.status}`)}
                    </Badge>
                  )}
                </div>
                <CardDescription className="mt-1 flex items-center gap-2 flex-wrap">
                  <span className="inline-flex items-center gap-1">
                    <Tag className="h-3 w-3" />
                    {g.scenario}
                  </span>
                  {g.target_date && (
                    <span className="inline-flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      {g.target_date}
                    </span>
                  )}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-zinc-600 dark:text-zinc-400 line-clamp-2 min-h-[2rem]">
                  {g.description ?? t("goals.list.noDesc")}
                </p>
                <div className="mt-3 flex items-center justify-between text-[10px] text-zinc-500 dark:text-zinc-600">
                  <span>{t("goals.list.updatedAt", { date: formatDate(g.updated_at) })}</span>
                  <span className="inline-flex items-center gap-1 text-brand-600 dark:text-brand-400 group-hover:translate-x-0.5 transition-transform">
                    {t("goals.list.open")} <ArrowRight className="h-3 w-3" />
                  </span>
                </div>
              </CardContent>
            </Card>
          </Link>
          );
        })}

        {/* No results after filtering — different from "no goals at all" */}
        {allGoals.length > 0 && filtered.length === 0 && !isLoading && (
          <Card className="col-span-full">
            <CardContent className="py-10 text-center space-y-3">
              <div className="mx-auto h-10 w-10 rounded-full bg-black/[0.04] dark:bg-white/[0.04] border border-black/5 dark:border-white/5 flex items-center justify-center">
                <Search className="h-4 w-4 text-zinc-500" />
              </div>
              <div className="text-sm text-zinc-700 dark:text-zinc-300">{t("goals.list.noMatch")}</div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-sm mx-auto">
                {t("goals.list.noMatchHint")}
              </p>
              <Button variant="outline" size="sm" onClick={clearFilters} className="mt-1">
                <FilterX className="h-3.5 w-3.5 mr-1.5" />
                {t("goals.list.clearFilters")}
              </Button>
            </CardContent>
          </Card>
        )}

        {allGoals.length === 0 && !isLoading && (
          <Card className="col-span-full">
            <CardContent className="py-12 text-center space-y-3">
              <div className="mx-auto h-12 w-12 rounded-full bg-brand-500/10 flex items-center justify-center">
                <Compass className="h-6 w-6 text-brand-600 dark:text-brand-400" />
              </div>
              <div className="text-sm text-zinc-700 dark:text-zinc-300">{t("goals.empty.title")}</div>
              <Button className="mt-2" onClick={() => setShowForm(true)}>
                <Plus className="h-4 w-4 mr-1.5" /> {t("goals.empty.create")}
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
