"use client";

import { useState } from "react";
import { Boxes, Plus } from "lucide-react";
import { AIAvatar } from "@/components/common/ai-avatar";
import { api, ALL_ROLES, type Protocol, type Role } from "@/lib/api";
import { useRuntimeCatalog } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

const ROLE_KEY: Record<Role, string> = {
  chat: "settings.personalModels.roleChat",
  vision: "settings.personalModels.roleVision",
  embedding: "settings.personalModels.roleEmbedding",
  rerank: "settings.personalModels.roleRerank",
};

export function PersonalModelSettings() {
  const { data: catalog, mutate } = useRuntimeCatalog();
  const [providerOpen, setProviderOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [provider, setProvider] = useState({ name: "", protocol: "openai_compatible" as Protocol, base_url: "", api_key: "" });
  const [model, setModel] = useState({ provider_id: "", name: "", display_name: "", capabilities: ["chat"] as Role[] });
  const toast = useToast();
  const t = useT();
  // Show personal model settings when:
  // - single-user mode (user is admin but there's no /admin page distinction)
  // - multi-user mode + non-admin + admin has enabled the policy
  // - multi-user mode + admin (admin can also have personal configs alongside platform configs)
  if (!catalog?.allow_user_service_config) return null;

  async function addProvider() {
    try { await api.addUserProvider(provider); await mutate(); setProviderOpen(false); setProvider({ name: "", protocol: "openai_compatible", base_url: "", api_key: "" }); }
    catch (error) { toast({ title: t("settings.personalModels.addProviderFailed"), description: error instanceof Error ? error.message : t("settings.personalModels.checkConfig"), variant: "error" }); }
  }
  async function addModel() {
    try { await api.addUserModel(model); await mutate(); setModelOpen(false); setModel({ provider_id: "", name: "", display_name: "", capabilities: ["chat"] }); }
    catch (error) { toast({ title: t("settings.personalModels.addModelFailed"), description: error instanceof Error ? error.message : t("settings.personalModels.checkConfig"), variant: "error" }); }
  }

  const userProviders = catalog.providers.filter((item) => item.managed_by === "user");
  return (
    <Card>
      <CardHeader className="flex-col sm:flex-row"><CardTitle className="flex items-center gap-2"><Boxes className="h-4 w-4 text-brand-500" />{t("settings.personalModels.title")}</CardTitle><CardDescription>{t("settings.personalModels.description")}</CardDescription></CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap gap-2">
          <ProviderDialog open={providerOpen} setOpen={setProviderOpen} form={provider} setForm={setProvider} onSave={addProvider} />
          <ModelDialog open={modelOpen} setOpen={setModelOpen} form={model} setForm={setModel} providers={userProviders} onSave={addModel} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {ALL_ROLES.map((role) => {
            const compatible = catalog.models.filter((item) => item.capabilities.includes(role));
            return <label key={role} className="space-y-1.5 text-xs text-zinc-500"><span>{t("settings.personalModels.defaultModel", { role: t(ROLE_KEY[role]) })}</span><Select value={catalog.role_assignments[role] ?? "__none__"} onValueChange={async (value) => { await api.setUserRoles({ [role]: value === "__none__" ? null : value }); await mutate(); }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__none__">{t("settings.personalModels.followAdmin")}</SelectItem>{compatible.map((item) => { const p = catalog.providers.find((entry) => entry.id === item.provider_id); return <SelectItem key={item.id} value={item.id}><span className="flex items-center gap-2"><AIAvatar protocol={p?.protocol} name={item.name} size={14} />{item.display_name}{item.managed_by === "admin" && <Badge variant="default" className="text-[9px]">{t("settings.personalModels.adminProvided")}</Badge>}</span></SelectItem>; })}</SelectContent></Select></label>;
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function ProviderDialog({ open, setOpen, form, setForm, onSave }: any) {
  const t = useT();
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm" variant="outline"><Plus className="mr-1.5 h-4 w-4" />{t("settings.personalModels.provider")}</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>{t("settings.personalModels.addProviderTitle")}</DialogTitle></DialogHeader><div className="space-y-3"><Input placeholder={t("settings.personalModels.namePlaceholder")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Select value={form.protocol} onValueChange={(protocol) => setForm({ ...form, protocol })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="openai_compatible">OpenAI Compatible</SelectItem><SelectItem value="ollama">Ollama</SelectItem><SelectItem value="anthropic">Anthropic</SelectItem><SelectItem value="bailian">百炼</SelectItem></SelectContent></Select><Input placeholder="Base URL" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /><Input type="password" placeholder="API Key" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></div><DialogFooter><Button disabled={!form.name} onClick={onSave}>{t("settings.personalModels.save")}</Button></DialogFooter></DialogContent></Dialog>;
}

function ModelDialog({ open, setOpen, form, setForm, providers, onSave }: any) {
  const t = useT();
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm" variant="outline" disabled={!providers.length}><Plus className="mr-1.5 h-4 w-4" />{t("settings.personalModels.model")}</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>{t("settings.personalModels.addModelTitle")}</DialogTitle></DialogHeader><div className="space-y-3"><Select value={form.provider_id} onValueChange={(provider_id) => setForm({ ...form, provider_id })}><SelectTrigger><SelectValue placeholder={t("settings.personalModels.selectProvider")} /></SelectTrigger><SelectContent>{providers.map((p: any) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select><Input placeholder={t("settings.personalModels.modelIdPlaceholder")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Input placeholder={t("settings.personalModels.displayNamePlaceholder")} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /><div className="flex flex-wrap gap-2">{ALL_ROLES.map((role) => <label key={role} className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={form.capabilities.includes(role)} onChange={() => setForm({ ...form, capabilities: form.capabilities.includes(role) ? form.capabilities.filter((item: Role) => item !== role) : [...form.capabilities, role] })} />{t(ROLE_KEY[role])}</label>)}</div></div><DialogFooter><Button disabled={!form.provider_id || !form.name || !form.capabilities.length} onClick={onSave}>{t("settings.personalModels.save")}</Button></DialogFooter></DialogContent></Dialog>;
}
