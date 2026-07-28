"use client";

import { useState } from "react";
import { Boxes, Plus } from "lucide-react";
import { AIAvatar } from "@/components/common/ai-avatar";
import { api, ALL_ROLES, type Protocol, type Role } from "@/lib/api";
import { useAuth, useRuntimeCatalog } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";

const ROLE_LABEL: Record<Role, string> = { chat: "对话", vision: "多模态", embedding: "嵌入", rerank: "重排序" };

export function PersonalModelSettings() {
  const { isAdmin } = useAuth();
  const { data: catalog, mutate } = useRuntimeCatalog();
  const [providerOpen, setProviderOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [provider, setProvider] = useState({ name: "", protocol: "openai_compatible" as Protocol, base_url: "", api_key: "" });
  const [model, setModel] = useState({ provider_id: "", name: "", display_name: "", capabilities: ["chat"] as Role[] });
  const toast = useToast();
  if (isAdmin || !catalog?.allow_user_service_config) return null;

  async function addProvider() {
    try { await api.addUserProvider(provider); await mutate(); setProviderOpen(false); setProvider({ name: "", protocol: "openai_compatible", base_url: "", api_key: "" }); }
    catch (error) { toast({ title: "添加供应商失败", description: error instanceof Error ? error.message : "请检查配置", variant: "error" }); }
  }
  async function addModel() {
    try { await api.addUserModel(model); await mutate(); setModelOpen(false); setModel({ provider_id: "", name: "", display_name: "", capabilities: ["chat"] }); }
    catch (error) { toast({ title: "添加模型失败", description: error instanceof Error ? error.message : "请检查配置", variant: "error" }); }
  }

  const userProviders = catalog.providers.filter((item) => item.managed_by === "user");
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Boxes className="h-4 w-4 text-brand-500" />我的模型服务</CardTitle><CardDescription>管理员模型只提供使用权；你自己的地址、密钥和默认模型与其他用户隔离。</CardDescription></CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap gap-2">
          <ProviderDialog open={providerOpen} setOpen={setProviderOpen} form={provider} setForm={setProvider} onSave={addProvider} />
          <ModelDialog open={modelOpen} setOpen={setModelOpen} form={model} setForm={setModel} providers={userProviders} onSave={addModel} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {ALL_ROLES.map((role) => {
            const compatible = catalog.models.filter((item) => item.capabilities.includes(role));
            return <label key={role} className="space-y-1.5 text-xs text-zinc-500"><span>{ROLE_LABEL[role]}默认模型</span><Select value={catalog.role_assignments[role] ?? "__none__"} onValueChange={async (value) => { await api.setUserRoles({ [role]: value === "__none__" ? null : value }); await mutate(); }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__none__">跟随管理员默认</SelectItem>{compatible.map((item) => { const p = catalog.providers.find((entry) => entry.id === item.provider_id); return <SelectItem key={item.id} value={item.id}><span className="flex items-center gap-2"><AIAvatar protocol={p?.protocol} name={item.name} size={14} />{item.display_name}{item.managed_by === "admin" && <Badge variant="default" className="text-[9px]">管理员提供</Badge>}</span></SelectItem>; })}</SelectContent></Select></label>;
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function ProviderDialog({ open, setOpen, form, setForm, onSave }: any) { return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm" variant="outline"><Plus className="mr-1.5 h-4 w-4" />供应商</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>添加个人供应商</DialogTitle></DialogHeader><div className="space-y-3"><Input placeholder="名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Select value={form.protocol} onValueChange={(protocol) => setForm({ ...form, protocol })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="openai_compatible">OpenAI Compatible</SelectItem><SelectItem value="ollama">Ollama</SelectItem><SelectItem value="anthropic">Anthropic</SelectItem><SelectItem value="bailian">百炼</SelectItem></SelectContent></Select><Input placeholder="Base URL" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /><Input type="password" placeholder="API Key" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></div><DialogFooter><Button disabled={!form.name} onClick={onSave}>保存</Button></DialogFooter></DialogContent></Dialog>; }
function ModelDialog({ open, setOpen, form, setForm, providers, onSave }: any) { return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm" variant="outline" disabled={!providers.length}><Plus className="mr-1.5 h-4 w-4" />模型</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>添加个人模型</DialogTitle></DialogHeader><div className="space-y-3"><Select value={form.provider_id} onValueChange={(provider_id) => setForm({ ...form, provider_id })}><SelectTrigger><SelectValue placeholder="选择供应商" /></SelectTrigger><SelectContent>{providers.map((p: any) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select><Input placeholder="模型 ID" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Input placeholder="显示名称" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /><div className="flex flex-wrap gap-2">{ALL_ROLES.map((role) => <label key={role} className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={form.capabilities.includes(role)} onChange={() => setForm({ ...form, capabilities: form.capabilities.includes(role) ? form.capabilities.filter((item: Role) => item !== role) : [...form.capabilities, role] })} />{ROLE_LABEL[role]}</label>)}</div></div><DialogFooter><Button disabled={!form.provider_id || !form.name || !form.capabilities.length} onClick={onSave}>保存</Button></DialogFooter></DialogContent></Dialog>; }
