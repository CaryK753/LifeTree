"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSettings } from "@/lib/hooks";
import {
  api,
  type ModelView,
  type Protocol,
  type ProviderView,
  type Role,
  type SmtpUpdate,
  type TestResult,
  type OAuthProviderView,
  type OAuthProviderCreate,
  type OAuthProviderUpdate,
  ALL_ROLES,
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
  AlertTriangle,
  Bot,
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  ImageIcon,
  KeyRound,
  Layers,
  Loader2,
  Mail,
  MessageSquare,
  Pencil,
  PlugZap,
  Plus,
  Power,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type TFunc = (key: string, vars?: Record<string, string | number>) => string;

function protocolOptions(t: TFunc): { value: Protocol; label: string; hint: string }[] {
  return [
    {
      value: "openai_compatible",
      label: t("settings.protocol.openai.label"),
      hint: t("settings.protocol.openai.hint"),
    },
    {
      value: "anthropic",
      label: t("settings.protocol.anthropic.label"),
      hint: t("settings.protocol.anthropic.hint"),
    },
    {
      value: "bailian",
      label: t("settings.protocol.bailian.label"),
      hint: t("settings.protocol.bailian.hint"),
    },
    {
      value: "bailian_rerank",
      label: t("settings.protocol.bailianRerank.label"),
      hint: t("settings.protocol.bailianRerank.hint"),
    },
  ];
}

/**
 * Vendor preset table — when the user picks a vendor in the Add Provider
 * dialog, the name and base URL are auto-filled from this table.
 *
 * Alibaba Cloud (bailian): a single base URL covers chat, vision,
 * embedding, AND qwen3-rerank (all use the OpenAI-compatible endpoint).
 * The gte-* / qwen3-vl-rerank models use DashScope's native endpoint,
 * which is handled by the backend — the frontend only stores the
 * compatible-mode URL.
 *
 * bailian_rerank: a dedicated special provider for Alibaba Cloud Bailian
 * rerank service. Uses the host root URL (not /compatible-mode/v1) so the
 * backend can route to either the compatible rerank endpoint
 * (/compatible-api/v1/reranks for qwen3-rerank) or the native rerank
 * endpoint (/api/v1/services/rerank/text-rerank/text-rerank for
 * gte-rerank-v2 / qwen3-vl-rerank) based on the model name. This avoids
 * the URL-mismatch issues that occur when a generic "bailian" provider
 * configured for chat is reused for rerank.
 */
const VENDOR_PRESETS: Record<Protocol, { name: string; baseUrl: string }> = {
  openai_compatible: {
    name: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
  },
  anthropic: {
    name: "Anthropic",
    baseUrl: "https://api.anthropic.com",
  },
  bailian: {
    name: "Alibaba Cloud Bailian",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  bailian_rerank: {
    name: "Alibaba Cloud Bailian (Rerank)",
    baseUrl: "https://dashscope.aliyuncs.com",
  },
};

interface RoleMeta {
  label: string;
  description: string;
  icon: typeof MessageSquare;
}

function roleMeta(t: TFunc, role: Role): RoleMeta {
  switch (role) {
    case "chat":
      return {
        label: t("settings.role.chat.label"),
        description: t("settings.role.chat.desc"),
        icon: MessageSquare,
      };
    case "vision":
      return {
        label: t("settings.role.vision.label"),
        description: t("settings.role.vision.desc"),
        icon: ImageIcon,
      };
    case "embedding":
      return {
        label: t("settings.role.embedding.label"),
        description: t("settings.role.embedding.desc"),
        icon: Layers,
      };
    case "rerank":
      return {
        label: t("settings.role.rerank.label"),
        description: t("settings.role.rerank.desc"),
        icon: Search,
      };
  }
}

export function PlatformConfig() {
  const { data: settings, mutate, isLoading } = useSettings();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const t = useT();

  async function handleProviderCreate(body: {
    name: string;
    protocol: Protocol;
    base_url: string;
    api_key: string;
  }) {
    try {
      const next = await api.addProvider(body);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.added"), description: body.name, variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.addFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleProviderUpdate(
    id: string,
    body: {
      name?: string;
      protocol?: Protocol;
      base_url?: string | null;
      api_key?: string | null;
    }
  ) {
    try {
      const next = await api.updateProvider(id, body);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.updated"), variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleProviderDelete(id: string, name: string) {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("settings.provider.deleteConfirm", { name }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    try {
      const next = await api.deleteProvider(id);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.deleted"), description: name, variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.deleteFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleModelCreate(body: {
    provider_id: string;
    name: string;
    display_name: string;
    capabilities: Role[];
  }) {
    try {
      const next = await api.addModel(body);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.modelAdded"), description: body.name, variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.addFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleModelUpdate(
    id: string,
    body: { name?: string; display_name?: string; capabilities?: Role[] }
  ) {
    try {
      const next = await api.updateModel(id, body);
      mutate(next, { revalidate: false });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleModelDelete(id: string, name: string) {
    const ok = await confirm({
      title: t("common.delete"),
      description: t("settings.model.deleteConfirm", { name }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    try {
      const next = await api.deleteModel(id);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.modelDeleted"), variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.deleteFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleRoleAssign(role: Role, modelId: string | null) {
    try {
      const next = await api.setRoles({ [role]: modelId });
      mutate(next, { revalidate: false });
    } catch (e: any) {
      toast({
        title: t("settings.toast.roleAssignFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleTavilySave(key: string) {
    try {
      const next = await api.setTavily(key);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.tavilySaved"), variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleMineruSave(key: string, baseUrl?: string) {
    try {
      const next = await api.setMineru(key, baseUrl);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.mineruSaved"), variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  async function handleSmtpSave(patch: SmtpUpdate) {
    try {
      const next = await api.setSmtp(patch);
      mutate(next, { revalidate: false });
      toast({ title: t("settings.toast.smtpSaved"), variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    }
  }

  const rolesConfigured = useMemo(() => {
    if (!settings) return 0;
    return ALL_ROLES.filter((r) => settings.roles_configured[r]).length;
  }, [settings]);

  return (
    <>
      {/* ---------- Role status cards ---------- */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {ALL_ROLES.map((role) => {
          const assignedId = settings?.role_assignments[role];
          const model = settings?.models.find((m) => m.id === assignedId);
          const provider = model
            ? settings?.providers.find((p) => p.id === model.provider_id)
            : undefined;
          const ready = settings?.roles_configured[role];
          return (
            <RoleCard
              key={role}
              role={role}
              models={settings?.models ?? []}
              assignedModel={model}
              assignedProvider={provider}
              ready={!!ready}
              onAssign={(mid) => handleRoleAssign(role, mid)}
            />
          );
        })}
      </section>

      {/* ---------- Providers & Models ---------- */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              {t("settings.provider.title")}
            </CardTitle>
            <CardDescription className="mt-1">
              {t("settings.provider.hint")}
            </CardDescription>
          </div>
          <ProviderAddButton onAdd={handleProviderCreate} />
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading && (
            <div className="flex items-center justify-center py-10 text-zinc-500 text-sm">
              <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("common.loading")}
            </div>
          )}
          {!isLoading && (settings?.providers.length ?? 0) === 0 && (
            <EmptyState
              icon={<Bot className="h-8 w-8 text-zinc-600" />}
              title={t("settings.provider.empty")}
              hint={t("settings.provider.emptyHint")}
            />
          )}
          {settings?.providers.map((p) => (
            <ProviderCard
              key={p.id}
              provider={p}
              models={settings.models.filter((m) => m.provider_id === p.id)}
              onEdit={(body) => handleProviderUpdate(p.id, body)}
              onDelete={() => handleProviderDelete(p.id, p.name)}
              onAddModel={(body) => handleModelCreate({ ...body, provider_id: p.id })}
              onEditModel={(mid, body) => handleModelUpdate(mid, body)}
              onDeleteModel={(mid, name) => handleModelDelete(mid, name)}
            />
          ))}
        </CardContent>
      </Card>

      {/* ---------- Tavily ---------- */}
      <TavilyCard
        configured={settings?.tavily_api_key_configured ?? false}
        preview={settings?.tavily_api_key_preview ?? ""}
        onSave={handleTavilySave}
      />

      {/* ---------- Mineru ---------- */}
      <MineruCard
        configured={settings?.mineru_api_key_configured ?? false}
        preview={settings?.mineru_api_key_preview ?? ""}
        baseUrl={settings?.mineru_base_url ?? "https://mineru.net/api/v4"}
        onSave={handleMineruSave}
      />

      {/* ---------- SMTP ---------- */}
      <SmtpCard
        host={settings?.smtp_host ?? ""}
        port={settings?.smtp_port ?? 587}
        user={settings?.smtp_user ?? ""}
        passwordConfigured={settings?.smtp_password_configured ?? false}
        passwordPreview={settings?.smtp_password_preview ?? ""}
        fromAddr={settings?.smtp_from ?? "notify@lifetree.local"}
        senderName={settings?.smtp_sender_name ?? "LifeTree"}
        useTls={settings?.smtp_use_tls ?? true}
        useSsl={settings?.smtp_use_ssl ?? false}
        onSave={handleSmtpSave}
      />

      {/* ---------- OAuth providers (admin-configured) ---------- */}
      <OAuthProvidersCard />

      {/* ---------- Auth settings (email verification, registration, service address) ---------- */}
      <AuthSettingsCard />
      {ConfirmRoot}
    </>
  );
}

export default PlatformConfig;

// ============== Role card ==============

function RoleCard({
  role,
  models,
  assignedModel,
  assignedProvider,
  ready,
  onAssign,
}: {
  role: Role;
  models: ModelView[];
  assignedModel?: ModelView;
  assignedProvider?: ProviderView;
  ready: boolean;
  onAssign: (modelId: string | null) => void;
}) {
  const t = useT();
  const meta = roleMeta(t, role);
  const Icon = meta.icon;
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const toast = useToast();

  const candidates = models.filter((m) => m.capabilities.includes(role));

  async function handleTest() {
    setTesting(true);
    setResult(null);
    try {
      const r = await api.testRole(role);
      setResult(r);
      if (r.ok) {
        toast({
          title: t("settings.role.testOk", { label: meta.label }),
          description:
            r.available_count != null
              ? t("settings.role.testOkDesc", { n: r.available_count })
              : undefined,
          variant: "success",
        });
      } else {
        toast({
          title: t("settings.role.testFail", { label: meta.label }),
          description: r.error ?? t("settings.role.testFailDesc"),
          variant: "error",
        });
      }
    } catch (e: any) {
      toast({
        title: t("settings.role.testError", { label: meta.label }),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <Card
      className={cn(
        "transition-colors",
        ready ? "border-emerald-500/20" : "border-black/5 dark:border-white/5"
      )}
    >
      <CardContent className="space-y-3 pt-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "h-8 w-8 rounded-md flex items-center justify-center",
                ready
                  ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "bg-black/5 dark:bg-white/5 text-zinc-500 dark:text-zinc-400"
              )}
            >
              <Icon className="h-4 w-4" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{meta.label}</div>
              <div className="text-[10px] text-zinc-500">{meta.description}</div>
            </div>
          </div>
          {ready ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          ) : (
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 mt-1.5" />
          )}
        </div>

        <Select
          value={assignedModel?.id ?? "__none__"}
          onValueChange={(v) => onAssign(v === "__none__" ? null : v)}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder={t("settings.role.unassigned")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">{t("settings.role.unassigned")}</SelectItem>
            {candidates.map((m) => (
              <SelectItem key={m.id} value={m.id}>
                {m.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {assignedModel && (
          <div className="text-[10px] text-zinc-500 leading-tight">
            <div className="font-mono text-zinc-500 dark:text-zinc-400 truncate">{assignedModel.name}</div>
            {assignedProvider && (
              <div className="truncate">via {assignedProvider.name}</div>
            )}
          </div>
        )}

        <Button
          variant="outline"
          size="sm"
          className="w-full h-7 text-xs"
          onClick={handleTest}
          disabled={testing || !ready}
        >
          {testing ? (
            <Loader2 className="h-3 w-3 mr-1.5 animate-spin" />
          ) : (
            <PlugZap className="h-3 w-3 mr-1.5" />
          )}
          {t("settings.role.testConnection")}
        </Button>

        {result && !result.ok && result.error && (
          <p className="text-[10px] text-red-600 dark:text-red-400 leading-snug line-clamp-2">
            {result.error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ============== Provider card ==============

function ProviderCard({
  provider,
  models,
  onEdit,
  onDelete,
  onAddModel,
  onEditModel,
  onDeleteModel,
}: {
  provider: ProviderView;
  models: ModelView[];
  onEdit: (body: {
    name?: string;
    protocol?: Protocol;
    base_url?: string | null;
    api_key?: string | null;
  }) => void;
  onDelete: () => void;
  onAddModel: (body: {
    name: string;
    display_name: string;
    capabilities: Role[];
  }) => void;
  onEditModel: (
    id: string,
    body: { name?: string; display_name?: string; capabilities?: Role[] }
  ) => void;
  onDeleteModel: (id: string, name: string) => void;
}) {
  const t = useT();
  const toast = useToast();
  const options = protocolOptions(t);
  const [editing, setEditing] = useState(false);
  const [showKey, setShowKey] = useState(false);
  // Actual (unmasked) key fetched from /settings/providers/{id}/key when the
  // user first clicks the eye button. Stays null until revealed.
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [editForm, setEditForm] = useState({
    name: provider.name,
    protocol: provider.protocol,
    base_url: provider.base_url ?? "",
    api_key: "",
  });

  useEffect(() => {
    setEditForm({
      name: provider.name,
      protocol: provider.protocol,
      base_url: provider.base_url ?? "",
      api_key: "",
    });
  }, [provider]);

  function saveEdit() {
    onEdit({
      name: editForm.name,
      protocol: editForm.protocol,
      base_url: editForm.base_url,
      api_key: editForm.api_key || null, // null = leave unchanged, "" = clear (sent as null here)
    });
    setEditing(false);
  }

  /**
   * Toggle key visibility. When showing for the first time, fetch the actual
   * key from the backend so the user sees the real value (not just "configured").
   * If they've already typed something into the input, we keep their edit
   * instead of overwriting it.
   */
  async function handleToggleKey() {
    if (!showKey) {
      // Turning ON — fetch the real key if we don't have it yet and the
      // user hasn't typed anything into the input.
      if (revealedKey === null && !editForm.api_key) {
        setRevealing(true);
        try {
          const r = await api.getProviderKey(provider.id);
          setRevealedKey(r.value ?? "");
          if (r.value) setEditForm((f) => ({ ...f, api_key: r.value! }));
        } catch (e: any) {
          toast({
            title: t("settings.provider.fetchKeyFailed"),
            description: e?.message,
            variant: "error",
          });
        } finally {
          setRevealing(false);
        }
      }
    }
    setShowKey((v) => !v);
  }

  /**
   * When the user changes the protocol in the edit form, auto-fill the
   * base_url from the preset table if the current value is empty or
   * matches another preset. The name is NOT auto-filled in edit mode
   * — the user has already named the provider.
   */
  function handleEditProtocolChange(protocol: Protocol) {
    const preset = VENDOR_PRESETS[protocol];
    setEditForm((prev) => ({
      ...prev,
      protocol,
      base_url:
        !prev.base_url.trim() ||
        Object.values(VENDOR_PRESETS).some((p) => p.baseUrl === prev.base_url)
          ? preset.baseUrl
          : prev.base_url,
    }));
  }

  return (
    <div className="rounded-lg border border-black/10 dark:border-white/10 bg-surface/40 overflow-hidden">
      {/* Provider header */}
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{provider.name}</span>
            <Badge variant="default" className="text-[10px]">
              {options.find((o) => o.value === provider.protocol)?.label ?? provider.protocol}
            </Badge>
            {provider.api_key_configured ? (
              <Badge className="text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200">
                Key {provider.api_key_preview}
              </Badge>
            ) : (
              <Badge className="text-[10px] border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200">
                {t("settings.provider.keyNotConfigured")}
              </Badge>
            )}
          </div>
          {provider.base_url && (
            <div className="mt-1 text-[11px] text-zinc-500 font-mono truncate">
              {provider.base_url}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setEditing((v) => !v)}
            title={t("settings.provider.edit")}
          >
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 hover:text-red-600 dark:hover:text-red-300"
            onClick={onDelete}
            title={t("settings.provider.delete")}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Inline edit form */}
      {editing && (
        <div className="px-4 pb-4 space-y-3 border-t border-black/5 dark:border-white/5 pt-3 bg-black/[0.03] dark:bg-black/20">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label={t("settings.provider.name")}>
              <Input
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                className="h-8 text-sm"
              />
            </Field>
            <Field label={t("settings.provider.protocol")}>
              <Select
                value={editForm.protocol}
                onValueChange={(v) => handleEditProtocolChange(v as Protocol)}
              >
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {options.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      <div className="flex flex-col">
                        <span>{o.label}</span>
                        <span className="text-[10px] text-zinc-500">{o.hint}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field
            label={t("settings.provider.baseUrl")}
            hint={t("settings.provider.baseUrlHint")}
          >
            <Input
              value={editForm.base_url}
              onChange={(e) => setEditForm({ ...editForm, base_url: e.target.value })}
              placeholder={t("settings.provider.baseUrlPlaceholder")}
              className="h-8 text-sm font-mono"
            />
          </Field>
          <Field
            label={t("settings.provider.apiKey")}
            hint={
              provider.api_key_configured
                ? t("settings.provider.apiKeyHint", { preview: provider.api_key_preview })
                : t("settings.provider.apiKeyNotConfigured")
            }
          >
            <div className="flex gap-2">
              <Input
                type={showKey ? "text" : "password"}
                value={editForm.api_key}
                onChange={(e) => {
                  setEditForm({ ...editForm, api_key: e.target.value });
                  // Mark that the user has manually edited the key so we
                  // don't overwrite their edit with the revealed value.
                  setRevealedKey(e.target.value);
                }}
                placeholder={
                  provider.api_key_configured && !editForm.api_key
                    ? t("settings.provider.apiKeyConfiguredHint")
                    : t("settings.provider.apiKeyPlaceholder")
                }
                autoComplete="off"
                className="h-8 text-sm font-mono"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={handleToggleKey}
                disabled={revealing}
                title={showKey ? t("settings.provider.hide") : t("settings.provider.show")}
              >
                {revealing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : showKey ? (
                  <EyeOff className="h-3.5 w-3.5" />
                ) : (
                  <Eye className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </Button>
            <Button size="sm" onClick={saveEdit}>
              {t("common.save")}
            </Button>
          </div>
        </div>
      )}

      {/* Models under this provider */}
      <div className="border-t border-black/5 dark:border-white/5 bg-black/[0.02] dark:bg-black/10 px-4 py-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-medium">
            {t("settings.provider.models", { n: models.length })}
          </div>
        </div>
        {models.length === 0 && (
          <div className="text-[11px] text-zinc-600 dark:text-zinc-500 py-2">
            {t("settings.provider.noModels")}
          </div>
        )}
        {models.map((m) => (
          <ModelRow
            key={m.id}
            model={m}
            onEdit={(body) => onEditModel(m.id, body)}
            onDelete={() => onDeleteModel(m.id, m.display_name)}
          />
        ))}
        <ModelAddButton onAdd={onAddModel} />
      </div>
    </div>
  );
}

// ============== Model row ==============

function ModelRow({
  model,
  onEdit,
  onDelete,
}: {
  model: ModelView;
  onEdit: (body: { name?: string; display_name?: string; capabilities?: Role[] }) => void;
  onDelete: () => void;
}) {
  const t = useT();

  const toggleCap = (role: Role) => {
    const has = model.capabilities.includes(role);
    const next = has
      ? model.capabilities.filter((r) => r !== role)
      : [...model.capabilities, role];
    onEdit({ capabilities: next });
  };

  return (
    <div className="flex items-center gap-3 py-1.5 rounded-md hover:bg-black/[0.02] dark:hover:bg-white/[0.02] group">
      <div className="min-w-0 flex-1">
        <div className="text-sm text-zinc-800 dark:text-zinc-200 truncate">{model.display_name}</div>
        <div className="text-[10px] text-zinc-500 dark:text-zinc-500 font-mono truncate">{model.name}</div>
      </div>
      <div className="flex items-center gap-1 flex-wrap justify-end">
        {ALL_ROLES.map((role) => {
          const has = model.capabilities.includes(role);
          const meta = roleMeta(t, role);
          return (
            <button
              key={role}
              type="button"
              onClick={() => toggleCap(role)}
              title={t("settings.model.toggleCapability", { label: meta.label })}
              className={cn(
                "text-[10px] px-1.5 py-0.5 rounded border transition-colors",
                has
                  ? "border-brand-500/30 bg-brand-500/15 text-brand-700 dark:text-brand-200"
                  : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 hover:border-black/20 dark:hover:border-white/20"
              )}
            >
              {meta.label}
            </button>
          );
        })}
      </div>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 opacity-0 group-hover:opacity-100 hover:text-red-600 dark:hover:text-red-300 transition-opacity"
        onClick={onDelete}
        title={t("settings.model.delete")}
      >
        <Trash2 className="h-3 w-3" />
      </Button>
    </div>
  );
}

// ============== Add buttons ==============

function ProviderAddButton({
  onAdd,
}: {
  onAdd: (body: {
    name: string;
    protocol: Protocol;
    base_url: string;
    api_key: string;
  }) => void;
}) {
  const t = useT();
  const options = protocolOptions(t);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    protocol: "openai_compatible" as Protocol,
    base_url: "",
    api_key: "",
  });
  const [showKey, setShowKey] = useState(false);

  /**
   * When the user picks a protocol/vendor, auto-fill name and base_url
   * from the preset table — but only if the user hasn't manually edited
   * those fields yet. This lets the user override the defaults without
   * fighting the auto-fill.
   */
  function handleProtocolChange(protocol: Protocol) {
    const preset = VENDOR_PRESETS[protocol];
    setForm((prev) => ({
      ...prev,
      protocol,
      // Only auto-fill name if it's empty or matches a previous preset
      name:
        !prev.name.trim() || Object.values(VENDOR_PRESETS).some((p) => p.name === prev.name)
          ? preset.name
          : prev.name,
      // Only auto-fill base_url if it's empty or matches a previous preset
      base_url:
        !prev.base_url.trim() ||
        Object.values(VENDOR_PRESETS).some((p) => p.baseUrl === prev.base_url)
          ? preset.baseUrl
          : prev.base_url,
    }));
  }

  function submit() {
    if (!form.name.trim()) return;
    onAdd({
      name: form.name.trim(),
      protocol: form.protocol,
      base_url: form.base_url.trim(),
      api_key: form.api_key.trim(),
    });
    setForm({ name: "", protocol: "openai_compatible", base_url: "", api_key: "" });
    setOpen(false);
  }

  // Trigger button — dialog is rendered (and portals Select correctly)
  // only when `open` is true. Using Radix Dialog here means ESC and
  // click-outside both close the dialog automatically, AND any portaled
  // content inside (like SelectContent) stacks above the dialog overlay
  // via Radix's internal layering — no more z-index wars.
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          // Pre-fill from the default protocol's preset when opening.
          const preset = VENDOR_PRESETS["openai_compatible"];
          setForm({
            name: preset.name,
            protocol: "openai_compatible",
            base_url: preset.baseUrl,
            api_key: "",
          });
          setOpen(true);
        }}
      >
        <Plus className="h-3.5 w-3.5 mr-1.5" />
        {t("settings.provider.add")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) {
            setForm({
              name: "",
              protocol: "openai_compatible",
              base_url: "",
              api_key: "",
            });
            setShowKey(false);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("settings.provider.add")}</DialogTitle>
            <DialogDescription>
              {t("settings.provider.addHint")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Field label={t("settings.provider.name")}>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t("settings.provider.namePlaceholder")}
                className="h-9 text-sm"
                autoFocus
              />
            </Field>
            <Field label={t("settings.provider.protocol")}>
              <Select
                value={form.protocol}
                onValueChange={(v) => handleProtocolChange(v as Protocol)}
              >
                <SelectTrigger className="h-9 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {options.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      <div className="flex flex-col">
                        <span>{o.label}</span>
                        <span className="text-[10px] text-zinc-500">
                          {o.hint}
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field
              label={t("settings.provider.baseUrl")}
              hint={t("settings.provider.baseUrlHint")}
            >
              <Input
                value={form.base_url}
                onChange={(e) =>
                  setForm({ ...form, base_url: e.target.value })
                }
                placeholder={t("settings.provider.baseUrlPlaceholder")}
                className="h-9 text-sm font-mono"
              />
            </Field>
            <Field label={t("settings.provider.apiKey")}>
              <div className="flex gap-2">
                <Input
                  type={showKey ? "text" : "password"}
                  value={form.api_key}
                  onChange={(e) =>
                    setForm({ ...form, api_key: e.target.value })
                  }
                  placeholder={t("settings.provider.apiKeyPlaceholderNew")}
                  autoComplete="off"
                  className="h-9 text-sm font-mono"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="h-9 w-9"
                  onClick={() => setShowKey((v) => !v)}
                >
                  {showKey ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </Field>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                {t("common.cancel")}
              </Button>
            </DialogClose>
            <Button size="sm" onClick={submit} disabled={!form.name.trim()}>
              {t("common.add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ModelAddButton({
  onAdd,
}: {
  onAdd: (body: {
    name: string;
    display_name: string;
    capabilities: Role[];
  }) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    display_name: "",
    capabilities: [] as Role[],
  });

  function submit() {
    if (!form.name.trim()) return;
    onAdd({
      name: form.name.trim(),
      display_name: form.display_name.trim() || form.name.trim(),
      capabilities: form.capabilities,
    });
    setForm({ name: "", display_name: "", capabilities: [] });
    setOpen(false);
  }

  if (!open) {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="mt-1 text-xs"
        onClick={() => setOpen(true)}
      >
        <Plus className="h-3 w-3 mr-1" />
        {t("settings.model.add")}
      </Button>
    );
  }

  return (
    <div className="mt-2 rounded-md border border-black/10 dark:border-white/10 bg-surface/60 p-3 space-y-2">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Field label={t("settings.model.id")}>
          <Input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder={t("settings.model.idPlaceholder")}
            className="h-8 text-sm font-mono"
            autoFocus
          />
        </Field>
        <Field label={t("settings.model.displayName")}>
          <Input
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            placeholder={t("settings.model.displayNamePlaceholder")}
            className="h-8 text-sm"
          />
        </Field>
      </div>
      <Field label={t("settings.model.capabilities")}>
        <div className="flex items-center gap-1.5 flex-wrap">
          {ALL_ROLES.map((role) => {
            const has = form.capabilities.includes(role);
            const meta = roleMeta(t, role);
            return (
              <button
                key={role}
                type="button"
                onClick={() =>
                  setForm((prev) => ({
                    ...prev,
                    capabilities: has
                      ? prev.capabilities.filter((r) => r !== role)
                      : [...prev.capabilities, role],
                  }))
                }
                className={cn(
                  "text-xs px-2 py-1 rounded border transition-colors",
                  has
                    ? "border-brand-500/30 bg-brand-500/15 text-brand-700 dark:text-brand-200"
                    : "border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.02] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"
                )}
              >
                {meta.label}
              </button>
            );
          })}
        </div>
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </Button>
        <Button size="sm" onClick={submit} disabled={!form.name.trim()}>
          {t("common.add")}
        </Button>
      </div>
    </div>
  );
}

// ============== Tavily ==============

function TavilyCard({
  configured,
  preview,
  onSave,
}: {
  configured: boolean;
  preview: string;
  onSave: (key: string) => void;
}) {
  const t = useT();
  const toast = useToast();
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [revealing, setRevealing] = useState(false);

  async function handleToggleShow() {
    if (!show && configured && !value) {
      // Fetch the real key on first reveal.
      setRevealing(true);
      try {
        const r = await api.getTavilyKey();
        if (r.value) setValue(r.value);
      } catch (e: any) {
        toast({
          title: t("settings.provider.fetchKeyFailed"),
          description: e?.message,
          variant: "error",
        });
      } finally {
        setRevealing(false);
      }
    }
    setShow((v) => !v);
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.tavily.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.tavily.subtitle")}
            <a
              href="https://tavily.com"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1.5 inline-flex items-center gap-0.5 text-brand-600 dark:text-brand-400 hover:underline"
            >
              {t("settings.tavily.apply")} <ExternalLink className="h-3 w-3" />
            </a>
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {configured && (
          <div className="flex items-center gap-2 text-xs">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
            <span className="text-zinc-500 dark:text-zinc-400">{t("settings.tavily.current")}</span>
            <span className="font-mono text-zinc-700 dark:text-zinc-300">{preview}</span>
          </div>
        )}
        <div className="flex gap-2">
          <Input
            type={show ? "text" : "password"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={
              configured && !value
                ? t("settings.provider.apiKeyConfiguredHint")
                : "tvly-..."
            }
            autoComplete="off"
            className="font-mono"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={handleToggleShow}
            disabled={revealing}
            title={show ? t("settings.provider.hide") : t("settings.provider.show")}
          >
            {revealing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : show ? (
              <EyeOff className="h-4 w-4" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
          </Button>
          <Button
            onClick={() => {
              onSave(value);
              setValue("");
              setShow(false);
            }}
            disabled={!value.trim()}
          >
            {t("common.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ============== Mineru ==============

function MineruCard({
  configured,
  preview,
  baseUrl,
  onSave,
}: {
  configured: boolean;
  preview: string;
  baseUrl: string;
  onSave: (key: string, baseUrl?: string) => void;
}) {
  const t = useT();
  const toast = useToast();
  const [value, setValue] = useState("");
  const [urlValue, setUrlValue] = useState(baseUrl);
  const [show, setShow] = useState(false);
  const [revealing, setRevealing] = useState(false);

  // Keep the URL field in sync with the server-provided default until the
  // user actually edits it.
  const [urlTouched, setUrlTouched] = useState(false);
  const effectiveUrl = urlTouched ? urlValue : baseUrl;

  async function handleToggleShow() {
    if (!show && configured && !value) {
      setRevealing(true);
      try {
        const r = await api.getMineruKey();
        if (r.value) setValue(r.value);
      } catch (e: any) {
        toast({
          title: t("settings.provider.fetchKeyFailed"),
          description: e?.message,
          variant: "error",
        });
      } finally {
        setRevealing(false);
      }
    }
    setShow((v) => !v);
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.mineru.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.mineru.subtitle")}
            <a
              href="https://mineru.net"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1.5 inline-flex items-center gap-0.5 text-brand-600 dark:text-brand-400 hover:underline"
            >
              {t("settings.mineru.apply")} <ExternalLink className="h-3 w-3" />
            </a>
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {configured && (
          <div className="flex items-center gap-2 text-xs">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
            <span className="text-zinc-500 dark:text-zinc-400">{t("settings.tavily.current")}</span>
            <span className="font-mono text-zinc-700 dark:text-zinc-300">{preview}</span>
          </div>
        )}
        <Field label={t("settings.provider.apiKey")}>
          <div className="flex gap-2">
            <Input
              type={show ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={
                configured && !value
                  ? t("settings.provider.apiKeyConfiguredHint")
                  : "mineru-..."
              }
              autoComplete="off"
              className="font-mono"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleToggleShow}
              disabled={revealing}
              title={show ? t("settings.provider.hide") : t("settings.provider.show")}
            >
              {revealing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : show ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </Button>
          </div>
        </Field>
        <Field
          label={t("settings.mineru.baseUrl")}
          hint={t("settings.mineru.baseUrlHint")}
        >
          <Input
            value={effectiveUrl}
            onChange={(e) => {
              setUrlTouched(true);
              setUrlValue(e.target.value);
            }}
            placeholder="https://mineru.net/api/v4"
            className="font-mono"
          />
        </Field>
        <div className="flex justify-end">
          <Button
            onClick={() => {
              onSave(value, urlTouched ? urlValue : undefined);
              setValue("");
              setUrlTouched(false);
              setShow(false);
            }}
            disabled={!value.trim()}
          >
            {t("common.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ============== SMTP Card ==============

function SmtpCard({
  host,
  port,
  user,
  passwordConfigured,
  passwordPreview,
  fromAddr,
  senderName,
  useTls,
  useSsl,
  onSave,
}: {
  host: string;
  port: number;
  user: string;
  passwordConfigured: boolean;
  passwordPreview: string;
  fromAddr: string;
  senderName: string;
  useTls: boolean;
  useSsl: boolean;
  onSave: (patch: SmtpUpdate) => void;
}) {
  const t = useT();
  const toast = useToast();
  // Local-edit state. We track touched-ness per field so we only send fields
  // the user actually changed (null = leave unchanged).
  const [hostV, setHostV] = useState(host);
  const [portV, setPortV] = useState(String(port));
  const [userV, setUserV] = useState(user);
  const [passwordV, setPasswordV] = useState("");
  const [fromV, setFromV] = useState(fromAddr);
  const [senderNameV, setSenderNameV] = useState(senderName);
  const [tlsV, setTlsV] = useState(useTls);
  const [sslV, setSslV] = useState(useSsl);
  const [hostTouched, setHostTouched] = useState(false);
  const [portTouched, setPortTouched] = useState(false);
  const [userTouched, setUserTouched] = useState(false);
  const [fromTouched, setFromTouched] = useState(false);
  const [senderNameTouched, setSenderNameTouched] = useState(false);
  const [tlsTouched, setTlsTouched] = useState(false);
  const [sslTouched, setSslTouched] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [revealingPw, setRevealingPw] = useState(false);
  // Test-email state — recipient defaults to the SMTP user (most common case),
  // user can override.
  const [testAddr, setTestAddr] = useState(user || "");
  const [testing, setTesting] = useState(false);

  // Re-sync from server when the upstream config changes (e.g. after a save).
  useEffect(() => {
    if (!hostTouched) setHostV(host);
  }, [host, hostTouched]);
  useEffect(() => {
    if (!portTouched) setPortV(String(port));
  }, [port, portTouched]);
  useEffect(() => {
    if (!userTouched) {
      setUserV(user);
      // Keep test recipient in sync with the SMTP user until the user
      // manually overrides it.
      setTestAddr((prev) => (prev ? prev : user));
    }
  }, [user, userTouched]);
  useEffect(() => {
    if (!fromTouched) setFromV(fromAddr);
  }, [fromAddr, fromTouched]);
  useEffect(() => {
    if (!senderNameTouched) setSenderNameV(senderName);
  }, [senderName, senderNameTouched]);
  useEffect(() => {
    if (!tlsTouched) setTlsV(useTls);
  }, [useTls, tlsTouched]);
  useEffect(() => {
    if (!sslTouched) setSslV(useSsl);
  }, [useSsl, sslTouched]);

  const configured = !!host;
  const hasEdit =
    hostTouched ||
    portTouched ||
    userTouched ||
    fromTouched ||
    senderNameTouched ||
    tlsTouched ||
    sslTouched ||
    !!passwordV.trim();

  function buildPatch(): SmtpUpdate {
    const patch: SmtpUpdate = {};
    if (hostTouched) patch.host = hostV.trim();
    if (portTouched) {
      const p = parseInt(portV, 10);
      if (!Number.isNaN(p)) patch.port = p;
    }
    if (userTouched) patch.user = userV.trim();
    if (fromTouched) patch.from_addr = fromV.trim();
    if (senderNameTouched) patch.sender_name = senderNameV.trim();
    if (tlsTouched) patch.use_tls = tlsV;
    if (sslTouched) patch.use_ssl = sslV;
    if (passwordV.trim()) patch.password = passwordV;
    return patch;
  }

  /**
   * Toggle password visibility. On first reveal, fetch the actual password
   * from the backend so the user sees the real value (not just "configured").
   * If they've already typed something, we keep their edit.
   */
  async function handleTogglePw() {
    if (!showPw && passwordConfigured && !passwordV) {
      setRevealingPw(true);
      try {
        const r = await api.getSmtpKey();
        if (r.value) setPasswordV(r.value);
      } catch (e: any) {
        toast({
          title: t("settings.provider.fetchKeyFailed"),
          description: e?.message,
          variant: "error",
        });
      } finally {
        setRevealingPw(false);
      }
    }
    setShowPw((v) => !v);
  }

  async function handleTestEmail() {
    const addr = testAddr.trim();
    if (!addr) {
      toast({
        title: t("settings.smtp.testNeedAddr"),
        variant: "error",
      });
      return;
    }
    setTesting(true);
    try {
      const r = await api.testSmtp(addr);
      if (r.ok) {
        toast({
          title: t("settings.smtp.testOk"),
          description: t("settings.smtp.testOkDesc", { addr }),
          variant: "success",
        });
      } else {
        toast({
          title: t("settings.smtp.testFail"),
          description: r.error ?? t("settings.toast.retryLater"),
          variant: "error",
        });
      }
    } catch (e: any) {
      toast({
        title: t("settings.smtp.testFail"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Mail className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.smtp.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.smtp.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {configured ? (
          <div className="flex items-center gap-2 text-xs">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
            <span className="text-zinc-500 dark:text-zinc-400">
              {user
                ? t("settings.smtp.currentWithUser", { host, port, user })
                : t("settings.smtp.current", { host, port })}
              {passwordConfigured && (
                <span className="text-zinc-600 dark:text-zinc-500 ml-1">
                  {t("settings.smtp.passwordPreview", { preview: passwordPreview })}
                </span>
              )}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>{t("settings.smtp.notConfigured")}</span>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-[2fr_1fr] gap-3">
          <Field label={t("settings.smtp.host")}>
            <Input
              value={hostV}
              onChange={(e) => {
                setHostV(e.target.value);
                setHostTouched(true);
              }}
              placeholder="smtp.gmail.com"
              className="font-mono"
            />
          </Field>
          <Field label={t("settings.smtp.port")}>
            <Input
              value={portV}
              onChange={(e) => {
                setPortV(e.target.value);
                setPortTouched(true);
              }}
              placeholder="587"
              inputMode="numeric"
              className="font-mono"
            />
          </Field>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label={t("settings.smtp.user")} hint={t("settings.smtp.userHint")}>
            <Input
              value={userV}
              onChange={(e) => {
                setUserV(e.target.value);
                setUserTouched(true);
              }}
              placeholder="user@example.com"
              autoComplete="off"
              className="font-mono"
            />
          </Field>
          <Field label={t("settings.smtp.password")}>
            <div className="flex gap-2">
              <Input
                type={showPw ? "text" : "password"}
                value={passwordV}
                onChange={(e) => setPasswordV(e.target.value)}
                placeholder={
                  passwordConfigured && !passwordV
                    ? t("settings.provider.apiKeyConfiguredHint")
                    : t("settings.smtp.passwordPlaceholder")
                }
                autoComplete="off"
                className="font-mono"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={handleTogglePw}
                disabled={revealingPw}
                title={showPw ? t("settings.provider.hide") : t("settings.provider.show")}
              >
                {revealingPw ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : showPw ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </Button>
            </div>
          </Field>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label={t("settings.smtp.from")} hint={t("settings.smtp.fromHint")}>
            <Input
              value={fromV}
              onChange={(e) => {
                setFromV(e.target.value);
                setFromTouched(true);
              }}
              placeholder="notify@lifetree.local"
              className="font-mono"
            />
          </Field>
          <Field label={t("settings.smtp.senderName")}>
            <Input
              value={senderNameV}
              onChange={(e) => {
                setSenderNameV(e.target.value);
                setSenderNameTouched(true);
              }}
              placeholder="LifeTree"
            />
          </Field>
        </div>

        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={tlsV}
                onChange={(e) => {
                  setTlsV(e.target.checked);
                  setTlsTouched(true);
                }}
                className="h-3.5 w-3.5 accent-brand-500"
              />
              <span className="text-xs text-zinc-700 dark:text-zinc-300">{t("settings.smtp.useTls")}</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={sslV}
                onChange={(e) => {
                  setSslV(e.target.checked);
                  setSslTouched(true);
                }}
                className="h-3.5 w-3.5 accent-brand-500"
              />
              <span className="text-xs text-zinc-700 dark:text-zinc-300">{t("settings.smtp.useSSL")}</span>
            </label>
          </div>
          <p className="text-[10px] text-zinc-500 leading-snug">{t("settings.smtp.sslHint")}</p>
        </div>

        {/* Test email section */}
        <div className="rounded-md border border-black/5 dark:border-white/10 bg-black/[0.02] dark:bg-black/20 p-3 space-y-2">
          <div className="flex items-center gap-2">
            <PlugZap className="h-3.5 w-3.5 text-brand-600 dark:text-brand-400" />
            <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
              {t("settings.smtp.testEmailTitle")}
            </span>
          </div>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-snug">
            {t("settings.smtp.testEmailHint")}
          </p>
          <div className="flex gap-2">
            <Input
              type="email"
              value={testAddr}
              onChange={(e) => setTestAddr(e.target.value)}
              placeholder="recipient@example.com"
              className="font-mono h-8 text-sm"
              autoComplete="off"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleTestEmail}
              disabled={testing || !configured || !testAddr.trim()}
              className="h-8"
            >
              {testing ? (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : (
                <Mail className="h-3.5 w-3.5 mr-1.5" />
              )}
              {t("settings.smtp.sendTest")}
            </Button>
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            onClick={() => {
              onSave(buildPatch());
              setPasswordV("");
              setShowPw(false);
            }}
            disabled={!hasEdit}
          >
            {t("common.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ============== Auth Settings (email verification, registration, service address) ==============

function AuthSettingsCard() {
  const t = useT();
  const toast = useToast();
  const [emailVerification, setEmailVerification] = useState(false);
  const [disableRegistration, setDisableRegistration] = useState(false);
  const [serviceAddress, setServiceAddress] = useState("");
  const [passkeyLogin, setPasskeyLogin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingEV, setSavingEV] = useState(false);
  const [savingDR, setSavingDR] = useState(false);
  const [savingAddr, setSavingAddr] = useState(false);
  const [savingPK, setSavingPK] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.getEmailVerification().catch(() => ({ enabled: false })),
      api.getDisableRegistration().catch(() => ({ enabled: false })),
      api.getServiceAddress().catch(() => ({ address: "" })),
      api.getPasskeyLogin().catch(() => ({ enabled: false })),
    ]).then(([ev, dr, addr, pk]) => {
      if (cancelled) return;
      setEmailVerification(ev.enabled);
      setDisableRegistration(dr.enabled);
      setServiceAddress(addr.address);
      setPasskeyLogin(pk.enabled);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggleEmailVerification(enabled: boolean) {
    setSavingEV(true);
    try {
      const r = await api.setEmailVerification(enabled);
      setEmailVerification(r.enabled);
      toast({
        title: r.enabled
          ? t("settings.authSettings.emailVerificationOn")
          : t("settings.authSettings.emailVerificationOff"),
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSavingEV(false);
    }
  }

  async function toggleDisableRegistration(enabled: boolean) {
    setSavingDR(true);
    try {
      const r = await api.setDisableRegistration(enabled);
      setDisableRegistration(r.enabled);
      toast({
        title: r.enabled
          ? t("settings.authSettings.registrationDisabled")
          : t("settings.authSettings.registrationEnabled"),
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSavingDR(false);
    }
  }

  async function togglePasskeyLogin(enabled: boolean) {
    setSavingPK(true);
    try {
      const r = await api.setPasskeyLogin(enabled);
      setPasskeyLogin(r.enabled);
      toast({
        title: r.enabled
          ? t("settings.authSettings.passkeyLoginOn")
          : t("settings.authSettings.passkeyLoginOff"),
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSavingPK(false);
    }
  }

  async function saveServiceAddress() {
    setSavingAddr(true);
    try {
      const r = await api.setServiceAddress(serviceAddress.trim());
      setServiceAddress(r.address);
      toast({ title: t("settings.toast.updated"), variant: "success" });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSavingAddr(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.authSettings.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.authSettings.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {loading ? (
          <div className="flex items-center justify-center py-6 text-zinc-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("common.loading")}
          </div>
        ) : (
          <>
            {/* Email verification */}
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {t("settings.authSettings.emailVerification")}
                </div>
                <div className="mt-0.5 text-[11px] text-zinc-500 leading-snug">
                  {t("settings.authSettings.emailVerificationHint")}
                </div>
              </div>
              <Switch
                checked={emailVerification}
                onChange={() => toggleEmailVerification(!emailVerification)}
                disabled={savingEV}
              />
            </div>

            {/* Disable registration */}
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {t("settings.authSettings.disableRegistration")}
                </div>
                <div className="mt-0.5 text-[11px] text-zinc-500 leading-snug">
                  {t("settings.authSettings.disableRegistrationHint")}
                </div>
              </div>
              <Switch
                checked={disableRegistration}
                onChange={() => toggleDisableRegistration(!disableRegistration)}
                disabled={savingDR}
              />
            </div>

            {/* Passkey login */}
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {t("settings.authSettings.passkeyLogin")}
                </div>
                <div className="mt-0.5 text-[11px] text-zinc-500 leading-snug">
                  {t("settings.authSettings.passkeyLoginHint")}
                </div>
              </div>
              <Switch
                checked={passkeyLogin}
                onChange={() => togglePasskeyLogin(!passkeyLogin)}
                disabled={savingPK}
              />
            </div>

            {/* Service address */}
            <div className="space-y-1.5">
              <Label className="text-xs text-zinc-500 dark:text-zinc-400">
                {t("settings.authSettings.serviceAddress")}
              </Label>
              <div className="flex gap-2">
                <Input
                  value={serviceAddress}
                  onChange={(e) => setServiceAddress(e.target.value)}
                  placeholder="https://lifetree.example.com"
                  className="h-9 text-sm font-mono"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={saveServiceAddress}
                  disabled={savingAddr}
                >
                  {savingAddr ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    t("common.save")
                  )}
                </Button>
              </div>
              <p className="text-[10px] text-zinc-500 leading-snug">
                {t("settings.authSettings.serviceAddressHint")}
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------- Switch (inline toggle) ----------
//
// Small self-contained switch so we don't need to import the shadcn Switch
// (which has a slightly different API) just for this card.

function Switch({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={onChange}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        checked
          ? "bg-brand-500"
          : "bg-zinc-300 dark:bg-zinc-700"
      )}
    >
      <span
        className={cn(
          "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
          checked ? "translate-x-4" : "translate-x-0"
        )}
      />
    </button>
  );
}

// ============== OAuth Providers (admin-configured) ==============

/**
 * OAuth2 provider presets. When the admin picks a preset, name/URLs/scopes
 * are auto-filled (only if the fields are empty or match another preset, so
 * manual overrides are preserved).
 */
const OAUTH_PRESETS: Record<
  string,
  {
    name: string;
    authorize_url: string;
    token_url: string;
    userinfo_url: string;
    scopes: string[];
    // CDN-hosted logo/favicon for the provider. Auto-filled into the
    // avatar_url field so the login dialog shows a recognizable icon
    // without the admin having to upload one manually.
    avatar_url: string;
  }
> = {
  github: {
    name: "GitHub",
    authorize_url: "https://github.com/login/oauth/authorize",
    token_url: "https://github.com/login/oauth/access_token",
    userinfo_url: "https://api.github.com/user",
    scopes: ["read:user", "user:email"],
    avatar_url: "https://github.githubassets.com/favicons/favicon.svg",
  },
  google: {
    name: "Google",
    authorize_url: "https://accounts.google.com/o/oauth2/v2/auth",
    token_url: "https://oauth2.googleapis.com/token",
    userinfo_url: "https://www.googleapis.com/oauth2/v3/userinfo",
    scopes: ["openid", "email", "profile"],
    avatar_url:
      "https://fonts.gstatic.com/s/i/productlogos/googleg/v6/24px.svg",
  },
  microsoft: {
    name: "Microsoft",
    authorize_url:
      "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    token_url: "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    userinfo_url: "https://graph.microsoft.com/oidc/userinfo",
    scopes: ["openid", "email", "profile"],
    avatar_url:
      "https://login.microsoftonline.com/static/$/common/images/favicon.ico",
  },
  gitlab: {
    name: "GitLab",
    authorize_url: "https://gitlab.com/oauth/authorize",
    token_url: "https://gitlab.com/oauth/token",
    userinfo_url: "https://gitlab.com/api/v4/user",
    scopes: ["read_user"],
    avatar_url: "https://gitlab.com/favicon.ico",
  },
  discord: {
    name: "Discord",
    authorize_url: "https://discord.com/api/oauth2/authorize",
    token_url: "https://discord.com/api/oauth2/token",
    userinfo_url: "https://discord.com/api/users/@me",
    scopes: ["identify", "email"],
    avatar_url: "https://discord.com/assets/favicons/favicon.ico",
  },
  linkedin: {
    name: "LinkedIn",
    authorize_url: "https://www.linkedin.com/oauth/v2/authorization",
    token_url: "https://www.linkedin.com/oauth/v2/accessToken",
    userinfo_url: "https://api.linkedin.com/v2/userinfo",
    scopes: ["openid", "profile", "email"],
    avatar_url: "https://www.linkedin.com/favicon.ico",
  },
  facebook: {
    name: "Facebook",
    authorize_url: "https://www.facebook.com/v18.0/dialog/oauth",
    token_url: "https://graph.facebook.com/v18.0/oauth/access_token",
    userinfo_url: "https://graph.facebook.com/me?fields=id,name,email",
    scopes: ["email", "public_profile"],
    avatar_url: "https://www.facebook.com/favicon.ico",
  },
  apple: {
    name: "Apple",
    authorize_url: "https://appleid.apple.com/auth/authorize",
    token_url: "https://appleid.apple.com/auth/token",
    userinfo_url: "",
    // Sign in with Apple returns ID token (JWT) instead of userinfo
    // endpoint — backend needs special handling. Kept here so admins
    // at least get the right authorize/token URLs auto-filled.
    scopes: ["name", "email"],
    avatar_url: "https://www.apple.com/favicon.ico",
  },
  custom: {
    name: "",
    authorize_url: "",
    token_url: "",
    userinfo_url: "",
    scopes: [],
    avatar_url: "",
  },
};

function OAuthProvidersCard() {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const [providers, setProviders] = useState<OAuthProviderView[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<OAuthProviderView | null>(null);
  const [adding, setAdding] = useState(false);

  async function refresh() {
    try {
      const list = await api.listOAuthProviders();
      setProviders(list);
    } catch (e: any) {
      toast({
        title: t("settings.oauth.title"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleDelete(p: OAuthProviderView) {
    const ok = await confirm({
      title: t("settings.oauth.delete"),
      description: t("settings.oauth.deleteConfirm", { name: p.name }),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteOAuthProvider(p.id);
      setProviders((prev) => prev.filter((x) => x.id !== p.id));
      toast({ title: t("settings.toast.deleted"), description: p.name, variant: "success" });
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
            <KeyRound className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.oauth.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.oauth.subtitle")}
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          <Plus className="h-3.5 w-3.5 mr-1.5" />
          {t("settings.oauth.add")}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-zinc-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("common.loading")}
          </div>
        ) : providers.length === 0 ? (
          <EmptyState
            icon={<KeyRound className="h-8 w-8 text-zinc-600" />}
            title={t("settings.oauth.empty")}
            hint={t("settings.oauth.emptyHint")}
          />
        ) : (
          providers.map((p) => (
            <OAuthProviderRow
              key={p.id}
              provider={p}
              onEdit={() => setEditing(p)}
              onDelete={() => handleDelete(p)}
              onUpdated={(updated) => {
                setProviders((prev) =>
                  prev.map((x) => (x.id === updated.id ? updated : x))
                );
              }}
            />
          ))
        )}
      </CardContent>

      {(adding || editing) && (
        <OAuthProviderDialog
          provider={editing}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
          onSaved={(saved) => {
            if (editing) {
              setProviders((prev) =>
                prev.map((x) => (x.id === saved.id ? saved : x))
              );
            } else {
              setProviders((prev) => [...prev, saved]);
            }
            setAdding(false);
            setEditing(null);
          }}
        />
      )}
      {ConfirmRoot}
    </Card>
  );
}

function OAuthProviderRow({
  provider,
  onEdit,
  onDelete,
  onUpdated,
}: {
  provider: OAuthProviderView;
  onEdit: () => void;
  onDelete: () => void;
  onUpdated: (p: OAuthProviderView) => void;
}) {
  const t = useT();
  const toast = useToast();
  const [toggling, setToggling] = useState(false);

  async function handleToggle() {
    setToggling(true);
    try {
      const updated = await api.updateOAuthProvider(provider.id, {
        enabled: !provider.enabled,
      });
      onUpdated(updated);
      toast({
        title: updated.enabled
          ? t("settings.oauth.enabled")
          : t("settings.oauth.disabled"),
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className="rounded-lg border border-black/10 dark:border-white/10 bg-surface/40 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 flex items-start gap-3">
          <div className="h-9 w-9 rounded-md border border-black/10 dark:border-white/10 overflow-hidden bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center shrink-0">
            {provider.avatar_url ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={provider.avatar_url}
                alt=""
                className="h-full w-full object-cover"
              />
            ) : (
              <ImageIcon className="h-4 w-4 text-zinc-400" />
            )}
          </div>
          <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {provider.name}
            </span>
            {provider.enabled ? (
              <Badge className="text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200">
                {t("settings.oauth.enabled")}
              </Badge>
            ) : (
              <Badge className="text-[10px] border-zinc-400/30 dark:border-zinc-700/50 bg-zinc-200/50 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400">
                {t("settings.oauth.disabled")}
              </Badge>
            )}
            {provider.client_id_configured ? (
              <Badge className="text-[10px] border-brand-500/30 bg-brand-500/10 text-brand-700 dark:text-brand-200">
                {t("settings.oauth.clientId")}
              </Badge>
            ) : (
              <Badge className="text-[10px] border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200">
                {t("settings.oauth.secretNotConfigured")}
              </Badge>
            )}
            {provider.client_secret_configured ? (
              <Badge className="text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200">
                {t("settings.oauth.secretConfigured")}
              </Badge>
            ) : (
              <Badge className="text-[10px] border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200">
                {t("settings.oauth.secretNotConfigured")}
              </Badge>
            )}
          </div>
          <div className="mt-1 text-[11px] text-zinc-500 font-mono truncate">
            {provider.authorize_url || "—"}
          </div>
          {provider.redirect_uri && (
            <div className="mt-0.5 text-[10px] text-zinc-500 font-mono truncate">
              {t("settings.oauth.redirectUri")}: {provider.redirect_uri}
            </div>
          )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleToggle}
            disabled={toggling}
            title={
              provider.enabled
                ? t("settings.oauth.disabled")
                : t("settings.oauth.enabled")
            }
          >
            {toggling ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Power className="h-3.5 w-3.5" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onEdit}
            title={t("settings.oauth.edit")}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 hover:text-red-600 dark:hover:text-red-300"
            onClick={onDelete}
            title={t("settings.oauth.delete")}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Resize an image file to a square data URL (cover-fit). Used for OAuth
 * provider avatar uploads — keeps the payload small and avoids any backend
 * image processing. Mirrors the helper in app/profile/page.tsx.
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
  const scale = Math.max(size / bitmap.width, size / bitmap.height);
  const scaledW = bitmap.width * scale;
  const scaledH = bitmap.height * scale;
  const dx = (size - scaledW) / 2;
  const dy = (size - scaledH) / 2;
  ctx.drawImage(bitmap, dx, dy, scaledW, scaledH);
  return canvas.toDataURL("image/jpeg", quality);
}

function OAuthProviderDialog({
  provider,
  onClose,
  onSaved,
}: {
  provider: OAuthProviderView | null;
  onClose: () => void;
  onSaved: (p: OAuthProviderView) => void;
}) {
  const t = useT();
  const toast = useToast();
  const isEdit = !!provider;

  // Current origin — used to auto-fill redirect_uri when a preset is
  // selected. Declared at the top so applyPreset can reference it.
  const origin =
    typeof window !== "undefined" ? window.location.origin : "";

  // Detect preset from provider's authorize_url when editing.
  const detectPreset = (p: OAuthProviderView | null): string => {
    if (!p) return "github";
    for (const [key, preset] of Object.entries(OAUTH_PRESETS)) {
      if (key === "custom") continue;
      if (p.authorize_url === preset.authorize_url) return key;
    }
    return "custom";
  };

  const [preset, setPreset] = useState<string>(() => detectPreset(provider));
  const [form, setForm] = useState({
    name: provider?.name ?? "",
    client_id: provider?.client_id ?? "",
    client_secret: "",
    authorize_url: provider?.authorize_url ?? "",
    token_url: provider?.token_url ?? "",
    userinfo_url: provider?.userinfo_url ?? "",
    scopes: provider?.scopes.join(" ") ?? "",
    redirect_uri: provider?.redirect_uri ?? "",
    enabled: provider?.enabled ?? true,
    avatar_url: provider?.avatar_url ?? "",
  });
  const [showSecret, setShowSecret] = useState(false);
  const [revealingSecret, setRevealingSecret] = useState(false);
  const [saving, setSaving] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  function applyPreset(key: string) {
    setPreset(key);
    const p = OAUTH_PRESETS[key];
    if (!p) return;
    const allPresets = Object.values(OAUTH_PRESETS);
    // Auto-fill redirect_uri too — derived from current origin so the
    // admin can copy-paste it directly into the provider's dashboard.
    const redirectUri = `${origin}/auth/callback/${key === "custom" ? "provider_id" : key}`;
    setForm((prev) => ({
      ...prev,
      name:
        !prev.name.trim() || allPresets.some((x) => x.name === prev.name)
          ? p.name
          : prev.name,
      authorize_url:
        !prev.authorize_url.trim() ||
        allPresets.some((x) => x.authorize_url === prev.authorize_url)
          ? p.authorize_url
          : prev.authorize_url,
      token_url:
        !prev.token_url.trim() ||
        allPresets.some((x) => x.token_url === prev.token_url)
          ? p.token_url
          : prev.token_url,
      userinfo_url:
        !prev.userinfo_url.trim() ||
        allPresets.some((x) => x.userinfo_url === prev.userinfo_url)
          ? p.userinfo_url
          : prev.userinfo_url,
      scopes:
        !prev.scopes.trim() ||
        allPresets.some((x) => x.scopes.join(" ") === prev.scopes)
          ? p.scopes.join(" ")
          : prev.scopes,
      avatar_url:
        !prev.avatar_url.trim() ||
        allPresets.some((x) => x.avatar_url === prev.avatar_url)
          ? p.avatar_url
          : prev.avatar_url,
      // Auto-fill redirect_uri if empty or matches a preset pattern.
      redirect_uri:
        !prev.redirect_uri.trim() ||
        /\/auth\/callback\/[a-z_]+$/.test(prev.redirect_uri)
          ? redirectUri
          : prev.redirect_uri,
    }));
  }

  async function handleToggleSecret() {
    if (
      !showSecret &&
      isEdit &&
      provider?.client_secret_configured &&
      !form.client_secret
    ) {
      setRevealingSecret(true);
      try {
        const r = await api.getOAuthProviderSecret(provider.id);
        if (r.value) setForm((f) => ({ ...f, client_secret: r.value! }));
      } catch (e: any) {
        toast({
          title: t("settings.oauth.fetchSecretFailed"),
          description: e?.message,
          variant: "error",
        });
      } finally {
        setRevealingSecret(false);
      }
    }
    setShowSecret((v) => !v);
  }

  async function handleAvatarChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast({
        title: t("settings.oauth.avatar.invalidType"),
        variant: "error",
      });
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      toast({
        title: t("settings.oauth.avatar.tooLarge"),
        variant: "error",
      });
      return;
    }
    setAvatarBusy(true);
    try {
      const dataUrl = await resizeImageToDataUrl(file, 128, 128);
      setForm((prev) => ({ ...prev, avatar_url: dataUrl }));
    } catch (err: any) {
      toast({
        title: t("settings.oauth.avatar.invalidType"),
        description: err?.message ?? "",
        variant: "error",
      });
    } finally {
      setAvatarBusy(false);
      if (avatarInputRef.current) avatarInputRef.current.value = "";
    }
  }

  function handleAvatarRemove() {
    setForm((prev) => ({ ...prev, avatar_url: "" }));
  }

  async function submit() {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const scopes = form.scopes.trim()
        ? form.scopes.trim().split(/\s+/)
        : [];
      if (isEdit && provider) {
        const body: OAuthProviderUpdate = {
          name: form.name.trim(),
          authorize_url: form.authorize_url.trim(),
          token_url: form.token_url.trim(),
          userinfo_url: form.userinfo_url.trim(),
          scopes,
          redirect_uri: form.redirect_uri.trim(),
          enabled: form.enabled,
          client_id: form.client_id,
          // null = leave unchanged, "" = clear
          client_secret: form.client_secret || null,
          avatar_url: form.avatar_url,
        };
        const updated = await api.updateOAuthProvider(provider.id, body);
        onSaved(updated);
        toast({ title: t("settings.toast.updated"), variant: "success" });
      } else {
        const body: OAuthProviderCreate = {
          name: form.name.trim(),
          client_id: form.client_id.trim(),
          client_secret: form.client_secret.trim(),
          authorize_url: form.authorize_url.trim(),
          token_url: form.token_url.trim(),
          userinfo_url: form.userinfo_url.trim(),
          scopes,
          redirect_uri: form.redirect_uri.trim(),
          enabled: form.enabled,
          avatar_url: form.avatar_url,
        };
        const created = await api.addOAuthProvider(body);
        onSaved(created);
        toast({
          title: t("settings.toast.added"),
          description: body.name,
          variant: "success",
        });
      }
    } catch (e: any) {
      toast({
        title: t("settings.toast.updateFailed"),
        description: e?.message ?? t("settings.toast.retryLater"),
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  // Compute the redirect URI hint with the current origin.
  const redirectHint = t("settings.oauth.redirectUriHint", { origin });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t("settings.oauth.edit") : t("settings.oauth.add")}
          </DialogTitle>
          <DialogDescription>{t("settings.oauth.addHint")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {/* Preset selector */}
          <Field label={t("settings.oauth.preset.custom")}>
            <Select value={preset} onValueChange={(v) => applyPreset(v)}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="github">
                  {t("settings.oauth.preset.github")}
                </SelectItem>
                <SelectItem value="google">
                  {t("settings.oauth.preset.google")}
                </SelectItem>
                <SelectItem value="microsoft">
                  {t("settings.oauth.preset.microsoft")}
                </SelectItem>
                <SelectItem value="gitlab">
                  {t("settings.oauth.preset.gitlab")}
                </SelectItem>
                <SelectItem value="discord">
                  {t("settings.oauth.preset.discord")}
                </SelectItem>
                <SelectItem value="linkedin">
                  {t("settings.oauth.preset.linkedin")}
                </SelectItem>
                <SelectItem value="facebook">
                  {t("settings.oauth.preset.facebook")}
                </SelectItem>
                <SelectItem value="apple">
                  {t("settings.oauth.preset.apple")}
                </SelectItem>
                <SelectItem value="custom">
                  {t("settings.oauth.preset.custom")}
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>

          {/* Avatar / logo upload */}
          <Field label={t("settings.oauth.avatar.label")}>
            <div className="flex items-center gap-3">
              <div className="h-12 w-12 rounded-md border border-black/10 dark:border-white/10 overflow-hidden bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center shrink-0">
                {form.avatar_url ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={form.avatar_url}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <ImageIcon className="h-5 w-5 text-zinc-400" />
                )}
              </div>
              <input
                ref={avatarInputRef}
                type="file"
                accept="image/*"
                onChange={handleAvatarChange}
                className="hidden"
              />
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => avatarInputRef.current?.click()}
                    disabled={avatarBusy}
                  >
                    {avatarBusy ? (
                      <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                    ) : (
                      <Upload className="h-3 w-3 mr-1" />
                    )}
                    {t("settings.oauth.avatar.upload")}
                  </Button>
                  {form.avatar_url && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs hover:text-red-600 dark:hover:text-red-300"
                      onClick={handleAvatarRemove}
                      disabled={avatarBusy}
                    >
                      <X className="h-3 w-3 mr-1" />
                      {t("settings.oauth.avatar.remove")}
                    </Button>
                  )}
                </div>
                <p className="text-[10px] text-zinc-500">
                  {t("settings.oauth.avatar.hint")}
                </p>
              </div>
            </div>
          </Field>

          <Field label={t("settings.oauth.name")}>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={t("settings.oauth.namePlaceholder")}
              className="h-9 text-sm"
              autoFocus
            />
          </Field>

          <Field label={t("settings.oauth.clientId")}>
            <Input
              value={form.client_id}
              onChange={(e) =>
                setForm({ ...form, client_id: e.target.value })
              }
              placeholder="..."
              className="h-9 text-sm font-mono"
            />
          </Field>

          <Field
            label={t("settings.oauth.clientSecret")}
            hint={
              isEdit && provider?.client_secret_configured
                ? t("settings.oauth.secretHint")
                : undefined
            }
          >
            <div className="flex gap-2">
              <Input
                type={showSecret ? "text" : "password"}
                value={form.client_secret}
                onChange={(e) =>
                  setForm({ ...form, client_secret: e.target.value })
                }
                placeholder={
                  isEdit && provider?.client_secret_configured && !form.client_secret
                    ? t("settings.oauth.secretConfigured")
                    : "..."
                }
                autoComplete="off"
                className="h-9 text-sm font-mono"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-9 w-9"
                onClick={handleToggleSecret}
                disabled={revealingSecret}
                title={
                  showSecret ? t("settings.oauth.hide") : t("settings.oauth.show")
                }
              >
                {revealingSecret ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : showSecret ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </Button>
            </div>
          </Field>

          <Field label={t("settings.oauth.authorizeUrl")}>
            <Input
              value={form.authorize_url}
              onChange={(e) =>
                setForm({ ...form, authorize_url: e.target.value })
              }
              placeholder="https://github.com/login/oauth/authorize"
              className="h-9 text-sm font-mono"
            />
          </Field>

          <Field label={t("settings.oauth.tokenUrl")}>
            <Input
              value={form.token_url}
              onChange={(e) =>
                setForm({ ...form, token_url: e.target.value })
              }
              placeholder="https://github.com/login/oauth/access_token"
              className="h-9 text-sm font-mono"
            />
          </Field>

          <Field label={t("settings.oauth.userinfoUrl")}>
            <Input
              value={form.userinfo_url}
              onChange={(e) =>
                setForm({ ...form, userinfo_url: e.target.value })
              }
              placeholder="https://api.github.com/user"
              className="h-9 text-sm font-mono"
            />
          </Field>

          <Field
            label={t("settings.oauth.scopes")}
            hint={t("settings.oauth.scopesHint")}
          >
            <Input
              value={form.scopes}
              onChange={(e) => setForm({ ...form, scopes: e.target.value })}
              placeholder={t("settings.oauth.scopesPlaceholder")}
              className="h-9 text-sm font-mono"
            />
          </Field>

          <Field
            label={t("settings.oauth.redirectUri")}
            hint={redirectHint}
          >
            <Input
              value={form.redirect_uri}
              onChange={(e) =>
                setForm({ ...form, redirect_uri: e.target.value })
              }
              placeholder={`${origin}/auth/callback/${provider?.id ?? "provider_id"}`}
              className="h-9 text-sm font-mono"
            />
          </Field>

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) =>
                setForm({ ...form, enabled: e.target.checked })
              }
              className="h-3.5 w-3.5 accent-brand-500"
            />
            <span className="text-xs text-zinc-700 dark:text-zinc-300">
              {form.enabled
                ? t("settings.oauth.enabled")
                : t("settings.oauth.disabled")}
            </span>
          </label>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm" onClick={onClose}>
              {t("common.cancel")}
            </Button>
          </DialogClose>
          <Button
            size="sm"
            onClick={submit}
            disabled={saving || !form.name.trim()}
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============== Shared bits ==============

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
      <Label className="text-xs text-zinc-500 dark:text-zinc-400">{label}</Label>
      {children}
      {hint && <p className="text-[10px] text-zinc-500 leading-snug">{hint}</p>}
    </div>
  );
}

function EmptyState({
  icon,
  title,
  hint,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      <div className="mb-3">{icon}</div>
      <div className="text-sm text-zinc-800 dark:text-zinc-300">{title}</div>
      {hint && <div className="text-xs text-zinc-500 mt-1">{hint}</div>}
    </div>
  );
}
