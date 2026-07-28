"use client";

import { useState } from "react";
import { Network, Plus, Trash2 } from "lucide-react";
import { api, type MCPServerCreate } from "@/lib/api";
import { useMcpServers } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";

const EMPTY: MCPServerCreate = { name: "", protocol: "http", description: "", url: "" };

export function McpSettingsCard() {
  const { data: servers = [], mutate } = useMcpServers();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<MCPServerCreate>(EMPTY);
  const toast = useToast();

  async function add() {
    setSaving(true);
    try {
      await api.addMcpServer(form);
      await mutate();
      setForm(EMPTY);
      setOpen(false);
      toast({ title: "MCP 服务已添加" });
    } catch (error) {
      toast({ title: "添加失败", description: error instanceof Error ? error.message : "请检查配置", variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2"><Network className="h-4 w-4 text-brand-500" />MCP 服务</CardTitle>
            <CardDescription className="mt-1">启用后，智能助手会在任务需要时调用这些工具。</CardDescription>
          </div>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild><Button size="sm"><Plus className="mr-1.5 h-4 w-4" />添加</Button></DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader><DialogTitle>添加 MCP 服务</DialogTitle></DialogHeader>
              <div className="space-y-3">
                <Input placeholder="服务名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                <Input placeholder="用途描述（帮助助手判断何时调用）" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                <Select value={form.protocol} onValueChange={(protocol: "http" | "sse" | "stdio") => setForm({ ...EMPTY, name: form.name, description: form.description, protocol })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="http">HTTP</SelectItem><SelectItem value="sse">SSE</SelectItem><SelectItem value="stdio">stdio</SelectItem>
                  </SelectContent>
                </Select>
                {form.protocol === "stdio" ? (
                  <>
                    <Input placeholder="可执行命令，例如 npx" value={form.command ?? ""} onChange={(e) => setForm({ ...form, command: e.target.value })} />
                    <Input placeholder="参数，以空格分隔" value={(form.args ?? []).join(" ")} onChange={(e) => setForm({ ...form, args: e.target.value.split(/\s+/).filter(Boolean) })} />
                  </>
                ) : (
                  <Input type="url" placeholder="https://example.com/mcp" value={form.url ?? ""} onChange={(e) => setForm({ ...form, url: e.target.value })} />
                )}
              </div>
              <DialogFooter><Button onClick={add} disabled={saving || !form.name || (form.protocol === "stdio" ? !form.command : !form.url)}>保存</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {servers.length === 0 ? <div className="py-6 text-center text-sm text-zinc-500">尚未配置 MCP 服务</div> : servers.map((server) => (
          <div key={server.id} className="flex items-center gap-3 rounded-md border border-black/10 px-3 py-2 dark:border-white/10">
            <Badge variant="default" className="font-mono text-[10px] uppercase">{server.protocol}</Badge>
            <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{server.name}</div><div className="truncate text-xs text-zinc-500">{server.description || "未填写描述"}</div></div>
            <Switch checked={server.enabled} onCheckedChange={async (enabled) => { await api.toggleMcpServer(server.id, enabled); await mutate(); }} />
            <Button variant="ghost" size="icon" title="删除" onClick={async () => { await api.deleteMcpServer(server.id); await mutate(); }}><Trash2 className="h-4 w-4 text-red-500" /></Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
