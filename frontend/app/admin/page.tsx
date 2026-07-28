"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import {
  ShieldAlert,
  Users,
  UserCheck,
  UserX,
  Crown,
  Loader2,
  KeyRound,
  Trash2,
  Pencil,
  Power,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { useAuth, useAuthConfig, useAdminStats, useAdminUsers } from "@/lib/hooks";
import { api, type AdminUserRead, type AdminUserUpdate } from "@/lib/api";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { PlatformConfig } from "@/components/settings/platform-config";
import { UseModeCard } from "@/components/settings/use-mode-card";
import { SystemComponentsCard } from "@/components/settings/system-components-card";

export default function AdminPage() {
  const t = useT();
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, isAdmin } = useAuth();
  const { data: authConfig } = useAuthConfig();
  const singleMode = (authConfig?.use_mode ?? "single") === "single";
  const { data: stats, mutate: refreshStats } = useAdminStats();
  const { data: users, mutate: refreshUsers, isLoading: usersLoading } = useAdminUsers();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();

  // ---------- Access control ----------
  // In single mode, the default-user fallback has admin rights — skip the
  // auth check. In multi mode, require an authenticated admin.
  useEffect(() => {
    if (authLoading) return;
    if (singleMode) return;
    if (!isAuthenticated) {
      router.replace("/");
      return;
    }
    if (user && user.role !== "admin") {
      toast({
        title: t("admin.accessDenied"),
        description: t("admin.accessDeniedDesc"),
        variant: "error",
      });
      router.replace("/");
    }
  }, [authLoading, singleMode, isAuthenticated, user, router, t, toast]);

  // ---------- Edit user dialog ----------
  const [editingUser, setEditingUser] = useState<AdminUserRead | null>(null);
  const [editForm, setEditForm] = useState<AdminUserUpdate>({});
  const [saving, setSaving] = useState(false);

  function openEditDialog(u: AdminUserRead) {
    setEditingUser(u);
    setEditForm({
      display_name: u.display_name,
      role: u.role,
      is_enabled: u.is_enabled,
    });
  }

  async function saveEdit() {
    if (!editingUser) return;
    setSaving(true);
    try {
      // Only send fields that actually changed.
      const patch: AdminUserUpdate = {};
      if (editForm.display_name && editForm.display_name !== editingUser.display_name) {
        patch.display_name = editForm.display_name;
      }
      if (editForm.role && editForm.role !== editingUser.role) {
        patch.role = editForm.role;
      }
      if (editForm.is_enabled !== undefined && editForm.is_enabled !== editingUser.is_enabled) {
        patch.is_enabled = editForm.is_enabled;
      }
      if (editForm.new_password) {
        patch.new_password = editForm.new_password;
      }

      if (Object.keys(patch).length === 0) {
        setEditingUser(null);
        return;
      }

      await api.adminUpdateUser(editingUser.id, patch);
      await Promise.all([refreshUsers(), refreshStats()]);
      toast({ title: t("admin.userUpdated"), variant: "success" });
      setEditingUser(null);
    } catch (e: any) {
      const msg =
        e?.details?.detail || e?.message || t("admin.updateFailed");
      toast({
        title: t("admin.updateFailed"),
        description: msg,
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function deleteUser(u: AdminUserRead) {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("admin.deleteConfirm", { name: u.display_name }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.adminDeleteUser(u.id);
      await Promise.all([refreshUsers(), refreshStats()]);
      toast({ title: t("admin.userDeleted"), variant: "success" });
    } catch (e: any) {
      const msg =
        e?.details?.detail || e?.message || t("admin.deleteFailed");
      toast({
        title: t("admin.deleteFailed"),
        description: msg,
        variant: "error",
      });
    }
  }

  // ---------- Loading ----------
  if (authLoading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-zinc-400" />
      </div>
    );
  }

  // Access check — in single mode, the default user is admin.
  if (!singleMode && (!isAuthenticated || !isAdmin)) {
    return null;
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 w-full max-w-[1600px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <ShieldAlert className="h-6 w-6 text-amber-600 dark:text-amber-400" />
            {t("admin.title")}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">{t("admin.subtitle")}</p>
        </div>
        <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200">
          <Crown className="h-3 w-3 mr-1" />
          {t("admin.adminPanel")}
        </Badge>
      </header>

      {/* Stats */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          icon={<Users className="h-4 w-4" />}
          label={t("admin.statTotalUsers")}
          value={stats?.total_users ?? 0}
          color="brand"
        />
        <StatCard
          icon={<UserCheck className="h-4 w-4" />}
          label={t("admin.statEnabledUsers")}
          value={stats?.enabled_users ?? 0}
          color="emerald"
        />
        <StatCard
          icon={<Crown className="h-4 w-4" />}
          label={t("admin.statAdminUsers")}
          value={stats?.admin_users ?? 0}
          color="amber"
        />
        <StatCard
          icon={<UserX className="h-4 w-4" />}
          label={t("admin.statDisabledUsers")}
          value={stats?.disabled_users ?? 0}
          color="red"
        />
      </section>

      {/* User list */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("admin.userList")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("admin.userListHint")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {usersLoading ? (
            <div className="flex items-center justify-center py-8 text-zinc-500 text-sm">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              {t("common.loading")}
            </div>
          ) : users && users.length > 0 ? (
            users.map((u) => (
              <UserRow
                key={u.id}
                user={u}
                isSelf={!!user && u.id === user.id}
                onEdit={() => openEditDialog(u)}
                onDelete={() => deleteUser(u)}
              />
            ))
          ) : (
            <div className="py-8 text-center text-sm text-zinc-500">
              {t("admin.noUsers")}
            </div>
          )}
        </CardContent>
      </Card>

      {/* System components (docker services status) */}
      <SystemComponentsCard />

      {/* Platform services configuration */}
      <PlatformConfig />

      {/* Use mode (single-user / multi-user) */}
      <UseModeCard />

      {/* Edit dialog */}
      <Dialog
        open={!!editingUser}
        onOpenChange={(o) => !o && setEditingUser(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("admin.editUser")}</DialogTitle>
            <DialogDescription>
              {editingUser?.display_name} · {editingUser?.email}
            </DialogDescription>
          </DialogHeader>
          {editingUser && (
            <div className="space-y-3">
              <Field label={t("auth.displayName")}>
                <Input
                  value={editForm.display_name ?? ""}
                  onChange={(e) =>
                    setEditForm({ ...editForm, display_name: e.target.value })
                  }
                  className="h-9 text-sm"
                />
              </Field>
              <Field label={t("admin.role")}>
                <Select
                  value={editForm.role ?? "user"}
                  onValueChange={(v) =>
                    setEditForm({
                      ...editForm,
                      role: v as "admin" | "user",
                    })
                  }
                >
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="user">{t("admin.roleUser")}</SelectItem>
                    <SelectItem value="admin">{t("admin.roleAdmin")}</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label={t("admin.accountStatus")}>
                <Select
                  value={editForm.is_enabled ? "enabled" : "disabled"}
                  onValueChange={(v) =>
                    setEditForm({
                      ...editForm,
                      is_enabled: v === "enabled",
                    })
                  }
                >
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="enabled">
                      {t("admin.statusEnabled")}
                    </SelectItem>
                    <SelectItem value="disabled">
                      {t("admin.statusDisabled")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field
                label={t("admin.resetPassword")}
                hint={t("admin.resetPasswordHint")}
              >
                <Input
                  type="password"
                  value={editForm.new_password ?? ""}
                  onChange={(e) =>
                    setEditForm({ ...editForm, new_password: e.target.value || undefined })
                  }
                  placeholder={t("admin.resetPasswordPlaceholder")}
                  className="h-9 text-sm"
                  minLength={6}
                />
              </Field>
            </div>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                {t("common.cancel")}
              </Button>
            </DialogClose>
            <Button size="sm" onClick={saveEdit} disabled={saving}>
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {ConfirmRoot}
    </div>
  );
}

// ---------- Subcomponents ----------

function StatCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  color: "brand" | "emerald" | "amber" | "red";
}) {
  const colorMap = {
    brand: "bg-brand-500/10 text-brand-700 dark:text-brand-300",
    emerald: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    amber: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
    red: "bg-red-500/10 text-red-700 dark:text-red-300",
  };
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "h-9 w-9 shrink-0 rounded-md flex items-center justify-center",
              colorMap[color]
            )}
          >
            {icon}
          </div>
          <div>
            <div className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
              {value}
            </div>
            <div className="text-[11px] text-zinc-500">{label}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function UserRow({
  user,
  isSelf,
  onEdit,
  onDelete,
}: {
  user: AdminUserRead;
  isSelf: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border border-black/5 dark:border-white/5 bg-surface/30">
      {/* Avatar */}
      <div className="h-9 w-9 shrink-0 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white text-sm font-semibold overflow-hidden">
        {user.avatar_url ? (
          <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
        ) : (
          user.display_name?.[0]?.toUpperCase() || "?"
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {user.display_name}
          </span>
          {isSelf && (
            <Badge className="text-[9px] border-brand-500/30 bg-brand-500/10 text-brand-700 dark:text-brand-300">
              {t("admin.you")}
            </Badge>
          )}
          {user.role === "admin" && (
            <Badge className="text-[9px] border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
              <Crown className="h-2.5 w-2.5 mr-0.5" />
              {t("admin.roleAdmin")}
            </Badge>
          )}
          {!user.is_enabled && (
            <Badge className="text-[9px] border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300">
              <UserX className="h-2.5 w-2.5 mr-0.5" />
              {t("admin.statusDisabled")}
            </Badge>
          )}
          {!user.has_password && (
            <Badge className="text-[9px] border-zinc-500/30 bg-zinc-500/10 text-zinc-700 dark:text-zinc-300">
              {t("admin.noPassword")}
            </Badge>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[10px] text-zinc-500 min-w-0">
          <span className="font-mono truncate">{user.id}</span>
          <span>·</span>
          <span className="truncate">{user.email || "—"}</span>
        </div>
      </div>

      {/* Actions */}
      <div className="shrink-0 flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          onClick={onEdit}
          title={t("admin.edit")}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 text-red-600 dark:text-red-400 hover:bg-red-500/10"
          onClick={onDelete}
          disabled={isSelf}
          title={isSelf ? t("admin.cannotDeleteSelf") : t("admin.delete")}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-zinc-700 dark:text-zinc-300">{label}</Label>
      {children}
      {hint && <p className="text-[10px] text-zinc-500 leading-snug">{hint}</p>}
    </div>
  );
}
