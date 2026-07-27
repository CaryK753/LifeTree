"use client";

import { useEffect, useRef, useState } from "react";
import { useUserProfile, useGoals, useMemories, useAuth, useAuthConfig, usePasskeys } from "@/lib/hooks";
import {
  api,
  type RiskTolerance,
  type PasskeyRead,
} from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import {
  User as UserIcon,
  Save,
  Loader2,
  Target,
  TrendingUp,
  Sparkles,
  CheckCircle2,
  Plus,
  Trash2,
  Brain,
  Camera,
  Pencil,
  Check,
  X,
  KeyRound,
  Crown,
  Bell,
  AlertTriangle,
  Fingerprint,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

// Demographic keys we surface as typed fields (per project plan §4.4).
const DEMO_FIELDS: { key: string; labelKey: string; placeholderKey: string }[] = [
  { key: "age", labelKey: "profile.field.age", placeholderKey: "profile.field.agePlaceholder" },
  { key: "nationality", labelKey: "profile.field.nationality", placeholderKey: "profile.field.nationalityPlaceholder" },
  { key: "education", labelKey: "profile.field.education", placeholderKey: "profile.field.educationPlaceholder" },
  { key: "language_score", labelKey: "profile.field.languageScore", placeholderKey: "profile.field.languageScorePlaceholder" },
  { key: "fund_range", labelKey: "profile.field.fundRange", placeholderKey: "profile.field.fundRangePlaceholder" },
  { key: "location", labelKey: "profile.field.location", placeholderKey: "profile.field.locationPlaceholder" },
];

const PRIORITY_VALUES = ["cost", "speed", "climate", "education", "security", "career"] as const;

const RISK_VALUES: RiskTolerance[] = ["low", "medium", "high"];

const MEMORY_CATEGORIES = [
  "family", "career", "health", "finance", "education",
  "location", "preference", "goal", "constraint", "other",
] as const;

/**
 * Load an image file into a canvas, downscale it to `size×size` (cover-fit),
 * and return a JPEG data URL. Used for avatar uploads — keeps the payload
 * small (≤ a few tens of KB) and avoids any backend image processing.
 */
async function resizeImageToDataUrl(
  file: File,
  size: number,
  quality = 0.85
): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");
  // Cover-fit: scale so the shorter side fills the canvas, center-crop the rest.
  const scale = Math.max(size / bitmap.width, size / bitmap.height);
  const scaledW = bitmap.width * scale;
  const scaledH = bitmap.height * scale;
  const dx = (size - scaledW) / 2;
  const dy = (size - scaledH) / 2;
  ctx.drawImage(bitmap, dx, dy, scaledW, scaledH);
  return canvas.toDataURL("image/jpeg", quality);
}

export default function ProfilePage() {
  const t = useT();
  const { data: profile, mutate, isLoading } = useUserProfile();
  const { data: goals } = useGoals();
  const { user: authUser } = useAuth();
  const { data: authConfig } = useAuthConfig();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();

  const [form, setForm] = useState<{
    display_name: string;
    email: string;
    avatar_url: string | null;
    demographics: Record<string, string>;
    priority_factors: Record<string, boolean>;
    risk_tolerance: RiskTolerance;
    primary_goal_id: string;
    notify_channels: Record<string, boolean>;
    quiet_hours_start: string;
    quiet_hours_end: string;
  }>({
    display_name: "",
    email: "",
    avatar_url: null,
    demographics: {},
    priority_factors: {},
    risk_tolerance: "medium",
    primary_goal_id: "",
    notify_channels: { email: true, in_app: true },
    quiet_hours_start: "",
    quiet_hours_end: "",
  });
  const [saving, setSaving] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [dirty, setDirty] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  // Hydrate form when profile loads.
  useEffect(() => {
    if (!profile) return;
    const demo: Record<string, string> = {};
    for (const f of DEMO_FIELDS) {
      const v = (profile.demographics as Record<string, unknown>)?.[f.key];
      demo[f.key] = v == null ? "" : String(v);
    }
    const pf = profile.priority_factors ?? {};
    const nc = profile.notify_channels ?? {};
    const qh = (profile.quiet_hours ?? {}) as { start?: string; end?: string };
    setForm({
      display_name: profile.display_name ?? "",
      email: profile.email ?? "",
      avatar_url: profile.avatar_url ?? null,
      demographics: demo,
      priority_factors:
        typeof pf === "object" && !Array.isArray(pf)
          ? Object.fromEntries(
              Object.entries(pf).map(([k, v]) => [k, Boolean(v)])
            )
          : {},
      risk_tolerance: profile.risk_tolerance ?? "medium",
      primary_goal_id: profile.primary_goal_id ?? "",
      notify_channels: {
        email: nc.email !== false,
        in_app: nc.in_app !== false,
        sms: !!nc.sms,
      },
      quiet_hours_start: qh.start ?? "",
      quiet_hours_end: qh.end ?? "",
    });
    setDirty(false);
  }, [profile]);

  function update<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  }

  function updateDemo(key: string, value: string) {
    setForm((prev) => ({
      ...prev,
      demographics: { ...prev.demographics, [key]: value },
    }));
    setDirty(true);
  }

  function togglePriority(value: string) {
    setForm((prev) => ({
      ...prev,
      priority_factors: {
        ...prev.priority_factors,
        [value]: !prev.priority_factors[value],
      },
    }));
    setDirty(true);
  }

  function toggleChannel(key: "email" | "in_app" | "sms") {
    setForm((prev) => ({
      ...prev,
      notify_channels: {
        ...prev.notify_channels,
        [key]: !prev.notify_channels[key],
      },
    }));
    setDirty(true);
  }

  /**
   * Read an image file, downscale it to 256x256, and produce a JPEG data URL.
   * Stored directly on the user profile via PATCH /users/{id}.
   */
  async function handleAvatarChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !profile) return;
    if (!file.type.startsWith("image/")) {
      toast({
        title: t("profile.toast.saveFailed"),
        description: t("profile.avatar.invalidType"),
        variant: "error",
      });
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      toast({
        title: t("profile.toast.saveFailed"),
        description: t("profile.avatar.tooLarge"),
        variant: "error",
      });
      return;
    }
    setUploadingAvatar(true);
    try {
      const dataUrl = await resizeImageToDataUrl(file, 256, 256);
      const next = await api.updateUser(profile.id, { avatar_url: dataUrl });
      mutate(next, { revalidate: false });
      setForm((prev) => ({ ...prev, avatar_url: dataUrl }));
      toast({ title: t("profile.avatar.saved"), variant: "success" });
    } catch (err: any) {
      toast({
        title: t("profile.toast.saveFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setUploadingAvatar(false);
      if (avatarInputRef.current) avatarInputRef.current.value = "";
    }
  }

  async function handleAvatarRemove() {
    if (!profile) return;
    setUploadingAvatar(true);
    try {
      const next = await api.updateUser(profile.id, { avatar_url: null });
      mutate(next, { revalidate: false });
      setForm((prev) => ({ ...prev, avatar_url: null }));
      toast({ title: t("profile.avatar.removed"), variant: "success" });
    } catch (err: any) {
      toast({
        title: t("profile.toast.saveFailed"),
        description: err?.message,
        variant: "error",
      });
    } finally {
      setUploadingAvatar(false);
    }
  }

  async function handleSave() {
    if (!profile) return;
    setSaving(true);
    try {
      // Strip empty demographic strings.
      const demographics: Record<string, string> = {};
      for (const [k, v] of Object.entries(form.demographics)) {
        if (v.trim()) demographics[k] = v.trim();
      }
      const priority_factors: Record<string, boolean> = {};
      for (const [k, v] of Object.entries(form.priority_factors)) {
        if (v) priority_factors[k] = true;
      }
      // Build quiet_hours payload: only set if both endpoints are filled.
      const quiet_hours: Record<string, string> = {};
      if (form.quiet_hours_start && form.quiet_hours_end) {
        quiet_hours.start = form.quiet_hours_start;
        quiet_hours.end = form.quiet_hours_end;
      }
      const next = await api.updateUser(profile.id, {
        display_name: form.display_name.trim() || profile.display_name,
        email: form.email.trim() || null,
        demographics,
        priority_factors,
        risk_tolerance: form.risk_tolerance,
        primary_goal_id: form.primary_goal_id || null,
        notify_channels: form.notify_channels,
        quiet_hours,
      });
      mutate(next, { revalidate: false });
      toast({ title: t("profile.toast.saved"), variant: "success" });
      setDirty(false);
    } catch (e: any) {
      toast({
        title: t("profile.toast.saveFailed"),
        description: e?.message ?? t("plugins.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  /**
   * One-click data destruction — calls DELETE /users/me/destroy which
   * cascades to all user-scoped rows (goals, scenarios, memories, uploads,
   * notifications, risk assessments). Requires a typed confirmation
   * matching the locale-specific confirmText, then logs out and reloads.
   *
   * Blocked by the backend for the default user (single-user mode) and
   * for the last remaining admin — both surface as 400 errors.
   */
  const [destroyOpen, setDestroyOpen] = useState(false);
  const [destroyTyped, setDestroyTyped] = useState("");
  const [destroying, setDestroying] = useState(false);

  async function handleDestroy() {
    if (!profile) return;
    setDestroying(true);
    try {
      await api.destroyMyAccount();
      toast({ title: t("profile.destroy.success"), variant: "success" });
      // Clear tokens + force reload → AuthGate shows login dialog.
      const { clearTokens } = await import("@/lib/api");
      clearTokens();
      window.location.href = "/";
    } catch (e: any) {
      const detail = (e as { details?: { detail?: string } })?.details?.detail;
      toast({
        title: t("profile.destroy.failed"),
        description: detail ?? e?.message,
        variant: "error",
      });
    } finally {
      setDestroying(false);
    }
  }

  if (isLoading || !profile) {
    return (
      <div className="p-4 sm:p-8 flex items-center justify-center text-zinc-500 text-sm">
        <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("common.loading")}
      </div>
    );
  }

  const progress = profile.progress ?? {};
  const tags = profile.implicit_tags ?? {};

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 w-full max-w-[1600px] mx-auto animate-fade-in">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <UserIcon className="h-6 w-6 text-brand-600 dark:text-brand-400" />
            {t("profile.title")}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">{t("profile.subtitle")}</p>
        </div>
        <Button onClick={handleSave} disabled={!dirty || saving}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <Save className="h-4 w-4 mr-1.5" />}
          {t("profile.save")}
        </Button>
      </header>

      {/* ---------- 账户信息（用户 ID + 角色）----------
          用户 ID 用于在 .env 中配置管理员提权；角色展示当前用户的权限。
          仅在已登录（authUser 存在）时显示。 */}
      {authUser && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="h-4 w-4 text-brand-600 dark:text-brand-400" />
                {t("profile.section.account")}
              </CardTitle>
              <CardDescription className="mt-1">
                {t("profile.section.accountHint")}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label={t("profile.field.userId")}>
                <div className="flex items-center gap-2">
                  <code className="flex-1 px-3 py-2 rounded-md bg-black/[0.04] dark:bg-white/[0.04] border border-black/10 dark:border-white/10 text-xs font-mono text-zinc-700 dark:text-zinc-300 break-all select-all">
                    {authUser.id}
                  </code>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-9 shrink-0"
                    onClick={() => {
                      navigator.clipboard.writeText(authUser.id);
                      toast({
                        title: t("profile.userIdCopied"),
                        variant: "success",
                      });
                    }}
                  >
                    {t("common.copy")}
                  </Button>
                </div>
              </Field>
              <Field label={t("profile.field.role")}>
                <div className="flex items-center gap-2">
                  {authUser.role === "admin" ? (
                    <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                      <Crown className="h-3 w-3 mr-1" />
                      {t("profile.roleAdmin")}
                    </Badge>
                  ) : (
                    <Badge className="border-brand-500/30 bg-brand-500/10 text-brand-700 dark:text-brand-300">
                      <UserIcon className="h-3 w-3 mr-1" />
                      {t("profile.roleUser")}
                    </Badge>
                  )}
                  {!authUser.is_enabled && (
                    <Badge className="border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300">
                      {t("profile.accountDisabled")}
                    </Badge>
                  )}
                </div>
                <p className="text-[10px] text-zinc-500 leading-snug mt-1.5">
                  {t("profile.field.roleHint")}
                </p>
              </Field>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ---------- 基础属性 ---------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <UserIcon className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              {t("profile.section.basic")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("profile.section.basicHint")}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Avatar uploader — round preview + upload / remove buttons.
              Saves immediately (not deferred to the main Save button) so the
              avatar propagates to the chat UI without a profile-wide commit. */}
          <div className="flex items-center gap-4">
            <div className="relative">
              <div className="h-20 w-20 rounded-full overflow-hidden bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white text-2xl font-semibold shrink-0 border-2 border-black/10 dark:border-white/10">
                {form.avatar_url ? (
                  <img
                    src={form.avatar_url}
                    alt={form.display_name || "avatar"}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <span>
                    {(form.display_name || "?").slice(0, 1).toUpperCase()}
                  </span>
                )}
              </div>
              {uploadingAvatar && (
                <div className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-white" />
                </div>
              )}
            </div>
            <div className="space-y-1.5">
              <div className="text-sm font-medium text-zinc-200">
                {t("profile.avatar.label")}
              </div>
              <p className="text-[11px] text-zinc-500 max-w-xs">
                {t("profile.avatar.hint")}
              </p>
              <div className="flex items-center gap-2">
                <input
                  ref={avatarInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleAvatarChange}
                  disabled={uploadingAvatar}
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => avatarInputRef.current?.click()}
                  disabled={uploadingAvatar}
                  className="h-7 text-xs"
                >
                  <Camera className="h-3.5 w-3.5 mr-1" />
                  {t("profile.avatar.upload")}
                </Button>
                {form.avatar_url && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={handleAvatarRemove}
                    disabled={uploadingAvatar}
                    className="h-7 text-xs text-zinc-500 hover:text-red-600 dark:hover:text-red-300"
                  >
                    <Trash2 className="h-3.5 w-3.5 mr-1" />
                    {t("profile.avatar.remove")}
                  </Button>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label={t("profile.field.displayName")}>
              <Input
                value={form.display_name}
                onChange={(e) => update("display_name", e.target.value)}
                placeholder={t("profile.field.displayNamePlaceholder")}
                className="h-9 text-sm"
              />
            </Field>
            <Field label={t("profile.field.email")}>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                placeholder={t("profile.field.emailPlaceholder")}
                className="h-9 text-sm"
              />
            </Field>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {DEMO_FIELDS.map((f) => (
              <Field key={f.key} label={t(f.labelKey)}>
                <Input
                  value={form.demographics[f.key] ?? ""}
                  onChange={(e) => updateDemo(f.key, e.target.value)}
                  placeholder={t(f.placeholderKey)}
                  className="h-9 text-sm"
                />
              </Field>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ---------- 目标与偏好 ---------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Target className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              {t("profile.section.goals")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("profile.section.goalsHint")}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field label={t("profile.field.primaryGoal")} hint={t("profile.field.primaryGoalHint")}>
            <Select
              value={form.primary_goal_id || "__none__"}
              onValueChange={(v) =>
                update("primary_goal_id", v === "__none__" ? "" : v)
              }
            >
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder={t("profile.field.none")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">{t("profile.field.none")}</SelectItem>
                {(goals as any[])?.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label={t("profile.field.priorityFactors")} hint={t("profile.field.priorityFactorsHint")}>
            <div className="flex items-center gap-2 flex-wrap">
              {PRIORITY_VALUES.map((opt) => {
                const active = !!form.priority_factors[opt];
                return (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => togglePriority(opt)}
                    className={cn(
                      "text-xs px-2.5 py-1 rounded-full border transition-colors",
                      active
                        ? "border-brand-500/40 bg-brand-500/15 text-brand-700 dark:text-brand-200"
                        : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:border-black/20 dark:hover:border-white/20"
                    )}
                  >
                    {active && <CheckCircle2 className="inline h-3 w-3 mr-1" />}
                    {t(`priority.${opt}`)}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label={t("profile.field.riskTolerance")}>
            <div className="grid grid-cols-3 gap-2">
              {RISK_VALUES.map((r) => {
                const active = form.risk_tolerance === r;
                return (
                  <button
                    key={r}
                    type="button"
                    onClick={() => update("risk_tolerance", r)}
                    className={cn(
                      "rounded-md border px-3 py-2 text-left transition-colors",
                      active
                        ? "border-brand-500/40 bg-brand-500/10"
                        : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] hover:border-black/20 dark:hover:border-white/20"
                    )}
                  >
                    <div className="text-sm font-medium text-zinc-100">
                      {t(`riskTolerance.${r}.label`)}
                    </div>
                    <div className="text-[10px] text-zinc-500 mt-0.5 leading-snug">
                      {t(`riskTolerance.${r}.desc`)}
                    </div>
                  </button>
                );
              })}
            </div>
          </Field>
        </CardContent>
      </Card>

      {/* ---------- 行为与进度 ---------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              {t("profile.section.behavior")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("profile.section.behaviorHint")}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <ProgressBoard progress={progress} />
        </CardContent>
      </Card>

      {/* ---------- 隐式标签 ---------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              {t("profile.section.tags")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("profile.section.tagsHint")}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {Object.keys(tags).length === 0 ? (
            <div className="text-xs text-zinc-600 py-3">
              {t("profile.section.tagsEmpty")}
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-wrap">
              {Object.entries(tags).map(([k, v]) => (
                <Badge
                  key={k}
                  variant="default"
                  className="text-[11px] border-brand-500/30 bg-brand-500/10 text-brand-700 dark:text-brand-200"
                >
                  {k}
                  {typeof v === "boolean" && v ? "" : `: ${String(v)}`}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---------- 通知偏好 ---------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              {t("profile.section.notifications")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("profile.section.notificationsHint")}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field
            label={t("profile.field.channels")}
            hint={t("profile.field.channelsHint")}
          >
            <div className="flex items-center gap-2 flex-wrap">
              {(["email", "in_app", "sms"] as const).map((ch) => {
                const active = !!form.notify_channels[ch];
                return (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => toggleChannel(ch)}
                    className={cn(
                      "text-xs px-2.5 py-1 rounded-full border transition-colors",
                      active
                        ? "border-brand-500/40 bg-brand-500/15 text-brand-700 dark:text-brand-200"
                        : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:border-black/20 dark:hover:border-white/20"
                    )}
                  >
                    {active && <CheckCircle2 className="inline h-3 w-3 mr-1" />}
                    {t(`profile.channel.${ch}`)}
                  </button>
                );
              })}
            </div>
            {form.notify_channels.sms && (
              <p className="text-[10px] text-amber-600 dark:text-amber-400 mt-1.5">
                {t("profile.channel.smsHint")}
              </p>
            )}
          </Field>

          <Field
            label={t("profile.field.quietHours")}
            hint={t("profile.field.quietHoursHint")}
          >
            <div className="grid grid-cols-2 gap-3 max-w-xs">
              <div>
                <Label className="text-[10px] text-zinc-500 mb-1 block">
                  {t("profile.field.quietHoursStart")}
                </Label>
                <Input
                  type="time"
                  value={form.quiet_hours_start}
                  onChange={(e) => {
                    setForm((prev) => ({ ...prev, quiet_hours_start: e.target.value }));
                    setDirty(true);
                  }}
                  className="h-9 text-sm"
                />
              </div>
              <div>
                <Label className="text-[10px] text-zinc-500 mb-1 block">
                  {t("profile.field.quietHoursEnd")}
                </Label>
                <Input
                  type="time"
                  value={form.quiet_hours_end}
                  onChange={(e) => {
                    setForm((prev) => ({ ...prev, quiet_hours_end: e.target.value }));
                    setDirty(true);
                  }}
                  className="h-9 text-sm"
                />
              </div>
            </div>
          </Field>
        </CardContent>
      </Card>

      {/* ---------- 通行密钥 ---------- */}
      {authUser && authConfig?.passkey_login_enabled && (
        <PasskeyCard userId={authUser.id} />
      )}

      {/* ---------- 记忆 ---------- */}
      <MemoryBoard />

      {/* ---------- 危险操作 ---------- */}
      <Card className="border-red-500/30">
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2 text-red-600 dark:text-red-400">
              <AlertTriangle className="h-4 w-4" />
              {t("profile.section.danger")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("profile.section.dangerHint")}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                {t("profile.destroy.title")}
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1 leading-relaxed">
                {t("profile.destroy.desc")}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="border-red-500/40 text-red-600 hover:bg-red-500/10 dark:text-red-400 dark:hover:bg-red-500/10"
              onClick={() => {
                setDestroyTyped("");
                setDestroyOpen(true);
              }}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1" />
              {t("profile.destroy.button")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Destroy confirmation dialog — requires typing the locale-specific
          confirmText to enable the destructive button. */}
      <Dialog open={destroyOpen} onOpenChange={(o) => !destroying && setDestroyOpen(o)}>
        <DialogContent className="max-w-md" hideClose>
          <DialogHeader>
            <DialogTitle className="text-red-600 dark:text-red-400">
              {t("profile.destroy.confirmTitle")}
            </DialogTitle>
            <DialogDescription className="whitespace-pre-line">
              {t("profile.destroy.confirmDesc", {
                confirmText: t("profile.destroy.confirmText"),
              })}
            </DialogDescription>
          </DialogHeader>
          <Input
            value={destroyTyped}
            onChange={(e) => setDestroyTyped(e.target.value)}
            placeholder={t("profile.destroy.confirmPlaceholder")}
            className="h-9 text-sm"
            autoFocus
          />
          <DialogFooter className="mt-2">
            <DialogClose
              className="inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium transition-colors border border-black/10 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-black/5 dark:hover:bg-white/5"
            >
              {t("common.cancel")}
            </DialogClose>
            <button
              type="button"
              disabled={
                destroying ||
                destroyTyped !== t("profile.destroy.confirmText")
              }
              onClick={handleDestroy}
              className={cn(
                "inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium transition-colors text-white",
                "bg-red-600 hover:bg-red-500",
                "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-red-600"
              )}
            >
              {destroying ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              ) : (
                <Trash2 className="h-3.5 w-3.5 mr-1" />
              )}
              {t("profile.destroy.button")}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {ConfirmRoot}
    </div>
  );
}

// ---------- Memory board ----------

function catMeta(c: string) {
  return `memory.category.${c}`;
}

// ============== Passkey management ==============

/**
 * Decode a base64url string into a Uint8Array. WebAuthn API requires
 * ArrayBuffer inputs for challenge / user.id / credential_id fields.
 */
function base64urlToUint8Array(b64: string): Uint8Array {
  // Pad to length multiple of 4
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  // Convert base64url → base64
  const b64std = padded.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64std);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

/**
 * Encode an ArrayBuffer into a base64url string (no padding).
 * Used to convert PublicKeyCredential.rawId → the id field the backend expects.
 */
function uint8ArrayToBase64url(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  const b64 = btoa(bin);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Browser support check — WebAuthn is available in all modern browsers
 * (Chrome 67+, Safari 14+, Firefox 60+) but not in older ones or
 * non-secure contexts (HTTP other than localhost).
 */
function isPasskeySupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    typeof PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.credentials !== "undefined"
  );
}

function formatPasskeyDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function PasskeyCard({ userId }: { userId: string }) {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data: passkeys, mutate, isLoading } = usePasskeys(true);
  const [registering, setRegistering] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [nickname, setNickname] = useState("");

  // WebAuthn requires a secure context (HTTPS or localhost). If not
  // available, show a hint instead of letting the user click a button
  // that will silently fail.
  const supported = isPasskeySupported();

  async function handleRegister() {
    if (!supported) {
      toast({
        title: t("profile.passkey.unsupported"),
        variant: "error",
      });
      return;
    }
    setRegistering(true);
    try {
      // 1. Fetch registration options from the backend.
      const { options } = await api.passkeyRegisterOptions();

      // 2. Convert the JSON-serializable options back into the format
      //    navigator.credentials.create() expects (ArrayBuffers for
      //    challenge and user.id).
      const publicKey = {
        ...options,
        challenge: base64urlToUint8Array(
          (options as { challenge?: string }).challenge ?? ""
        ),
        user: {
          ...(options as { user?: Record<string, unknown> }).user,
          id: base64urlToUint8Array(
            ((options as { user?: { id?: string } }).user?.id as string) ??
              userId
          ),
        },
        excludeCredentials: (
          (options as { excludeCredentials?: Array<{ id: string }> })
            .excludeCredentials ?? []
        ).map((c) => ({
          ...c,
          id: base64urlToUint8Array(c.id),
          type: "public-key" as PublicKeyCredentialType,
        })),
      } as unknown as PublicKeyCredentialCreationOptions;

      // 3. Prompt the user to touch their authenticator.
      const credential = (await navigator.credentials.create({
        publicKey,
      })) as PublicKeyCredential | null;

      if (!credential) {
        toast({
          title: t("profile.passkey.registerCanceled"),
          variant: "error",
        });
        return;
      }

      // 4. Serialize the credential into the JSON format the backend
      //    expects. The rawId and response.attestationObject/clientDataJSON
      //    are all ArrayBuffers — they need to be base64url-encoded.
      const response = credential.response as AuthenticatorAttestationResponse;
      const serializedCredential = {
        id: credential.id,
        rawId: uint8ArrayToBase64url(credential.rawId),
        type: credential.type,
        response: {
          attestationObject: uint8ArrayToBase64url(response.attestationObject),
          clientDataJSON: uint8ArrayToBase64url(response.clientDataJSON),
          transports:
            response.getTransports?.() ?? [],
        },
        clientExtensionResults:
          credential.getClientExtensionResults?.() ?? {},
      };

      // 5. Send to the backend for verification + storage.
      const r = await api.passkeyRegisterVerify(
        serializedCredential,
        nickname.trim()
      );
      mutate((prev) => [...(prev ?? []), r.passkey], {
        revalidate: false,
      });
      toast({
        title: t("profile.passkey.registerSuccess"),
        description: r.passkey.nickname || undefined,
        variant: "success",
      });
      setShowAddForm(false);
      setNickname("");
    } catch (e: any) {
      const name = e?.name ?? "";
      if (name === "NotAllowedError" || name === "AbortError") {
        toast({
          title: t("profile.passkey.registerCanceled"),
          variant: "error",
        });
      } else {
        toast({
          title: t("profile.passkey.registerFailed"),
          description: e?.message ?? t("settings.toast.retryLater"),
          variant: "error",
        });
      }
    } finally {
      setRegistering(false);
    }
  }

  async function handleDelete(pk: PasskeyRead) {
    const label = pk.nickname || formatPasskeyDate(pk.created_at);
    const ok = await confirm({
      title: t("profile.passkey.delete"),
      description: pk.nickname
        ? t("profile.passkey.deleteConfirm", { name: label })
        : t("profile.passkey.deleteConfirmUnnamed"),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deletePasskey(pk.id);
      mutate((prev) => (prev ?? []).filter((x) => x.id !== pk.id), {
        revalidate: false,
      });
      toast({
        title: t("settings.toast.deleted"),
        description: label,
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("settings.toast.deleteFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Fingerprint className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("profile.passkey.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("profile.passkey.subtitle")}
          </CardDescription>
        </div>
        {supported && !showAddForm && (
          <Button variant="outline" size="sm" onClick={() => setShowAddForm(true)}>
            <Plus className="h-3.5 w-3.5 mr-1.5" />
            {t("profile.passkey.add")}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {!supported ? (
          <div className="text-sm text-amber-700 dark:text-amber-300 leading-relaxed">
            {t("profile.passkey.unsupported")}
          </div>
        ) : isLoading ? (
          <div className="flex items-center justify-center py-6 text-zinc-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("common.loading")}
          </div>
        ) : (passkeys?.length ?? 0) === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Fingerprint className="h-8 w-8 text-zinc-400 mb-2" />
            <div className="text-sm text-zinc-800 dark:text-zinc-300">
              {t("profile.passkey.empty")}
            </div>
            <div className="text-xs text-zinc-500 mt-1">
              {t("profile.passkey.emptyHint")}
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {passkeys?.map((pk) => (
              <div
                key={pk.id}
                className="rounded-lg border border-black/10 dark:border-white/10 bg-surface/40 p-3 group"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                        {pk.nickname || formatPasskeyDate(pk.created_at)}
                      </span>
                      <Badge
                        className={
                          pk.backed_up
                            ? "text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                            : "text-[10px] border-zinc-400/30 dark:border-zinc-700/50 bg-zinc-200/50 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400"
                        }
                      >
                        {pk.backed_up
                          ? t("profile.passkey.backedUp")
                          : t("profile.passkey.deviceBound")}
                      </Badge>
                      <Badge
                        variant="default"
                        className="text-[10px] font-mono"
                      >
                        {pk.device_type}
                      </Badge>
                    </div>
                    <div className="mt-1 text-[10px] text-zinc-500 dark:text-zinc-400">
                      {t("profile.passkey.createdAt")}:{" "}
                      {formatPasskeyDate(pk.created_at)}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 hover:text-red-600 dark:hover:text-red-300 transition-opacity shrink-0"
                    onClick={() => handleDelete(pk)}
                    title={t("profile.passkey.delete")}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Inline add form — nickname is optional */}
        {showAddForm && supported && (
          <div className="rounded-md border border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] p-3 space-y-3">
            <Field label={t("profile.passkey.nickname")}>
              <Input
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                placeholder={t("profile.passkey.nicknamePlaceholder")}
                className="h-9 text-sm"
                maxLength={128}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !registering) {
                    e.preventDefault();
                    handleRegister();
                  }
                }}
              />
            </Field>
            <p className="text-[10px] text-zinc-500 leading-snug">
              {t("profile.passkey.addHint")}
            </p>
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowAddForm(false);
                  setNickname("");
                }}
                disabled={registering}
              >
                {t("common.cancel")}
              </Button>
              <Button size="sm" onClick={handleRegister} disabled={registering}>
                {registering && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                )}
                {registering
                  ? t("profile.passkey.registering")
                  : t("profile.passkey.add")}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
      {ConfirmRoot}
    </Card>
  );
}

function MemoryBoard() {
  const t = useT();
  const { data: memories, mutate, isLoading } = useMemories();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();

  const [newContent, setNewContent] = useState("");
  const [newCategory, setNewCategory] = useState<string>("other");
  const [newImportance, setNewImportance] = useState(0.5);
  const [adding, setAdding] = useState(false);

  // Inline edit state. `editingId` holds the id of the memory being edited;
  // the three `edit*` fields hold the draft values.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editCategory, setEditCategory] = useState<string>("other");
  const [editImportance, setEditImportance] = useState(0.5);
  const [saving, setSaving] = useState(false);

  async function handleAdd() {
    const trimmed = newContent.trim();
    if (!trimmed) return;
    setAdding(true);
    try {
      const created = await api.createMemory({
        content: trimmed,
        category: newCategory,
        importance: newImportance,
        source: "manual",
      });
      mutate((prev) => [created, ...(prev ?? [])], { revalidate: false });
      setNewContent("");
      setNewImportance(0.5);
      setNewCategory("other");
      toast({ title: t("memory.toast.added"), variant: "success" });
    } catch (e: any) {
      toast({ title: t("memory.toast.addFailed"), description: e?.message, variant: "error" });
    } finally {
      setAdding(false);
    }
  }

  function startEdit(m: { id: string; content: string; category: string; importance: number }) {
    setEditingId(m.id);
    setEditContent(m.content);
    setEditCategory(m.category);
    setEditImportance(m.importance);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditContent("");
    setEditCategory("other");
    setEditImportance(0.5);
  }

  async function handleSaveEdit(id: string) {
    const trimmed = editContent.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      const updated = await api.updateMemory(id, {
        content: trimmed,
        category: editCategory,
        importance: editImportance,
      });
      mutate(
        (prev) => prev?.map((m) => (m.id === id ? updated : m)),
        { revalidate: false }
      );
      toast({ title: t("memory.toast.updated"), variant: "success" });
      cancelEdit();
    } catch (e: any) {
      toast({ title: t("memory.toast.updateFailed"), description: e?.message, variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("memory.deleteConfirm"),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteMemory(id);
      mutate(
        (prev) => prev?.filter((m) => m.id !== id),
        { revalidate: false }
      );
      toast({ title: t("memory.toast.deleted"), variant: "success" });
    } catch (e: any) {
      toast({ title: t("memory.toast.deleteFailed"), description: e?.message, variant: "error" });
    }
  }

  return (
    <>
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("memory.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("memory.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Add form */}
        <div className="space-y-2 rounded-md bg-white/[0.02] border border-white/5 p-3">
          <textarea
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder={t("memory.placeholder")}
            rows={2}
            className="w-full resize-none rounded bg-white/5 border border-white/10 px-2.5 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
          />
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={newCategory} onValueChange={setNewCategory}>
              <SelectTrigger className="h-8 w-24 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MEMORY_CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>
                    {t(catMeta(c))}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex items-center gap-1.5 text-xs text-zinc-400">
              <span>{t("memory.importance")}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={newImportance}
                onChange={(e) => setNewImportance(Number(e.target.value))}
                className="w-24 accent-brand-500"
              />
              <span className="text-zinc-300 w-8">{newImportance.toFixed(1)}</span>
            </div>
            <Button
              onClick={handleAdd}
              disabled={adding || !newContent.trim()}
              className="h-8 ml-auto text-xs"
              size="sm"
            >
              {adding ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              ) : (
                <Plus className="h-3.5 w-3.5 mr-1" />
              )}
              {t("memory.add")}
            </Button>
          </div>
        </div>

        {/* List */}
        {isLoading ? (
          <div className="text-xs text-zinc-600 py-3 flex items-center gap-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("common.loading")}
          </div>
        ) : !memories || memories.length === 0 ? (
          <div className="text-xs text-zinc-600 py-3">
            {t("memory.empty")}
          </div>
        ) : (
          <ul className="space-y-1.5">
            {memories.map((m) => {
              // Light/dark paired colors: -700 reads on light, -300 reads on dark.
              // Backgrounds stay as /10 alpha tints which work in both themes.
              const catColor = {
                family: "text-pink-700 dark:text-pink-300 border-pink-500/30 bg-pink-500/10",
                career: "text-sky-700 dark:text-sky-300 border-sky-500/30 bg-sky-500/10",
                health: "text-emerald-700 dark:text-emerald-300 border-emerald-500/30 bg-emerald-500/10",
                finance: "text-amber-700 dark:text-amber-300 border-amber-500/30 bg-amber-500/10",
                education: "text-violet-700 dark:text-violet-300 border-violet-500/30 bg-violet-500/10",
                location: "text-cyan-700 dark:text-cyan-300 border-cyan-500/30 bg-cyan-500/10",
                preference: "text-indigo-700 dark:text-indigo-300 border-indigo-500/30 bg-indigo-500/10",
                goal: "text-brand-700 dark:text-brand-300 border-brand-500/30 bg-brand-500/10",
                constraint: "text-red-700 dark:text-red-300 border-red-500/30 bg-red-500/10",
                other: "text-zinc-700 dark:text-zinc-300 border-zinc-500/30 bg-zinc-500/10",
              }[m.category] ?? "text-zinc-700 dark:text-zinc-300 border-zinc-500/30 bg-zinc-500/10";
              const isEditing = editingId === m.id;
              return (
                <li
                  key={m.id}
                  className="group rounded-md border border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-white/[0.02] px-2.5 py-2 hover:bg-black/[0.04] dark:hover:bg-white/[0.04] transition-colors"
                >
                  {isEditing ? (
                    /* Inline edit form */
                    <div className="space-y-2">
                      <textarea
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        rows={2}
                        autoFocus
                        className="w-full resize-none rounded bg-black/5 dark:bg-white/5 border border-black/10 dark:border-white/10 px-2.5 py-1.5 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                      />
                      <div className="flex items-center gap-2 flex-wrap">
                        <Select value={editCategory} onValueChange={setEditCategory}>
                          <SelectTrigger className="h-8 w-24 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {MEMORY_CATEGORIES.map((c) => (
                              <SelectItem key={c} value={c}>
                                {t(catMeta(c))}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <div className="flex items-center gap-1.5 text-xs text-zinc-400">
                          <span>{t("memory.importance")}</span>
                          <input
                            type="range"
                            min={0}
                            max={1}
                            step={0.1}
                            value={editImportance}
                            onChange={(e) => setEditImportance(Number(e.target.value))}
                            className="w-24 accent-brand-500"
                          />
                          <span className="text-zinc-300 w-8">{editImportance.toFixed(1)}</span>
                        </div>
                        <div className="flex items-center gap-1 ml-auto">
                          <Button
                            onClick={() => handleSaveEdit(m.id)}
                            disabled={saving || !editContent.trim()}
                            className="h-8 text-xs"
                            size="sm"
                          >
                            {saving ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                            ) : (
                              <Check className="h-3.5 w-3.5 mr-1" />
                            )}
                            {t("memory.save")}
                          </Button>
                          <Button
                            onClick={cancelEdit}
                            disabled={saving}
                            variant="ghost"
                            className="h-8 text-xs"
                            size="sm"
                          >
                            <X className="h-3.5 w-3.5 mr-1" />
                            {t("memory.cancel")}
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    /* Display mode */
                    <div className="flex items-start gap-2">
                      <span
                        className={cn(
                          "text-[10px] px-1.5 py-0.5 rounded border shrink-0 mt-0.5",
                          catColor
                        )}
                      >
                        {t(catMeta(m.category))}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-zinc-100 break-words leading-snug">
                          {m.content}
                        </div>
                        <div className="text-[10px] text-zinc-500 mt-0.5 flex items-center gap-2">
                          <span>{t("memory.importance")} {m.importance.toFixed(2)}</span>
                          <span>·</span>
                          <span>
                            {t(`memory.source.${m.source}`)}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5">
                        <button
                          onClick={() => startEdit(m)}
                          className="text-zinc-500 hover:text-brand-600 dark:hover:text-brand-300 p-1 rounded"
                          title={t("memory.edit")}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(m.id)}
                          className="text-zinc-500 hover:text-red-600 dark:hover:text-red-300 p-1 rounded"
                          title={t("memory.delete")}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
    {ConfirmRoot}
    </>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs text-zinc-400">{label}</Label>
      {children}
      {hint && <p className="text-[10px] text-zinc-500 leading-snug">{hint}</p>}
    </div>
  );
}

function ProgressBoard({ progress }: { progress: Record<string, unknown> }) {
  const t = useT();
  const total = Number(progress.requirements_total ?? 0);
  const met = Number(progress.met ?? 0);
  const partial = Number(progress.partial ?? 0);
  const missing = Number(progress.missing ?? 0);
  const unknown = Math.max(0, total - met - partial - missing);
  const pct = total > 0 ? Math.round((met / total) * 100) : 0;

  if (total === 0) {
    return (
      <div className="text-xs text-zinc-600 py-3">
        {t("profile.progress.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-2xl font-semibold text-zinc-100">{pct}%</div>
          <div className="text-[11px] text-zinc-500">{t("profile.progress.completion")}</div>
        </div>
        <div className="text-[11px] text-zinc-500">{t("profile.progress.total", { n: total })}</div>
      </div>
      <div className="h-2 rounded-full bg-white/5 overflow-hidden flex">
        {met > 0 && (
          <div
            className="bg-emerald-500/70"
            style={{ width: `${(met / total) * 100}%` }}
            title={t("profile.progress.metTitle", { n: met })}
          />
        )}
        {partial > 0 && (
          <div
            className="bg-amber-500/70"
            style={{ width: `${(partial / total) * 100}%` }}
            title={t("profile.progress.partialTitle", { n: partial })}
          />
        )}
        {missing > 0 && (
          <div
            className="bg-red-500/70"
            style={{ width: `${(missing / total) * 100}%` }}
            title={t("profile.progress.missingTitle", { n: missing })}
          />
        )}
        {unknown > 0 && (
          <div
            className="bg-zinc-600/70"
            style={{ width: `${(unknown / total) * 100}%` }}
            title={t("profile.progress.unknownTitle", { n: unknown })}
          />
        )}
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        <ProgressStat label={t("profile.progress.met")} value={met} color="text-emerald-300" />
        <ProgressStat label={t("profile.progress.partial")} value={partial} color="text-amber-300" />
        <ProgressStat label={t("profile.progress.missing")} value={missing} color="text-red-300" />
        <ProgressStat label={t("profile.progress.unknown")} value={unknown} color="text-zinc-400" />
      </div>
    </div>
  );
}

function ProgressStat({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="rounded-md bg-white/[0.02] border border-white/5 py-2">
      <div className={cn("text-lg font-semibold", color)}>{value}</div>
      <div className="text-[10px] text-zinc-500">{label}</div>
    </div>
  );
}
