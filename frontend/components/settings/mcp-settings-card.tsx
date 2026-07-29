"use client";

import { useState } from "react";
import { Network, Plus, Trash2, ChevronDown, ChevronUp } from "lucide-react";
import { api, type MCPServerCreate } from "@/lib/api";
import { useMcpServers } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

const EMPTY: MCPServerCreate = { name: "", protocol: "http", description: "", url: "" };

/** Key-value pair editor for headers / extra body fields. */
function KeyValueEditor({
  pairs,
  onChange,
  keyPlaceholder,
  valuePlaceholder,
}: {
  pairs: Array<{ key: string; value: string }>;
  onChange: (pairs: Array<{ key: string; value: string }>) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
}) {
  const t = useT();
  function update(idx: number, field: "key" | "value", v: string) {
    const next = pairs.map((p, i) => (i === idx ? { ...p, [field]: v } : p));
    onChange(next);
  }
  function add() {
    onChange([...pairs, { key: "", value: "" }]);
  }
  function remove(idx: number) {
    onChange(pairs.filter((_, i) => i !== idx));
  }

  return (
    <div className="space-y-1.5">
      {pairs.map((p, idx) => (
        <div key={idx} className="flex items-center gap-1.5">
          <Input
            className="h-8 text-xs flex-1"
            placeholder={keyPlaceholder}
            value={p.key}
            onChange={(e) => update(idx, "key", e.target.value)}
          />
          <Input
            className="h-8 text-xs flex-1"
            placeholder={valuePlaceholder}
            value={p.value}
            onChange={(e) => update(idx, "value", e.target.value)}
          />
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8 shrink-0 text-zinc-400 hover:text-red-500"
            onClick={() => remove(idx)}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      ))}
      <Button size="sm" variant="outline" className="h-7 text-xs w-full" onClick={add}>
        <Plus className="h-3 w-3 mr-1" /> {t("settings.mcp.add")}
      </Button>
    </div>
  );
}

function pairsToRecord(pairs: Array<{ key: string; value: string }>): Record<string, string> | undefined {
  const filtered = pairs.filter((p) => p.key.trim());
  if (filtered.length === 0) return undefined;
  const rec: Record<string, string> = {};
  for (const p of filtered) rec[p.key.trim()] = p.value;
  return rec;
}

function recordToPairs(rec?: Record<string, string>): Array<{ key: string; value: string }> {
  if (!rec) return [];
  return Object.entries(rec).map(([key, value]) => ({ key, value: String(value) }));
}

export function McpSettingsCard() {
  const { data: servers = [], mutate } = useMcpServers();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<MCPServerCreate>(EMPTY);
  const [headerPairs, setHeaderPairs] = useState<Array<{ key: string; value: string }>>([]);
  const [bodyPairs, setBodyPairs] = useState<Array<{ key: string; value: string }>>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const toast = useToast();
  const t = useT();

  function resetForm() {
    setForm(EMPTY);
    setHeaderPairs([]);
    setBodyPairs([]);
    setShowAdvanced(false);
  }

  async function add() {
    setSaving(true);
    try {
      const payload: MCPServerCreate = {
        ...form,
        headers: pairsToRecord(headerPairs),
        extra_body: pairsToRecord(bodyPairs),
      };
      await api.addMcpServer(payload);
      await mutate();
      resetForm();
      setOpen(false);
      toast({ title: t("settings.mcp.added") });
    } catch (error) {
      toast({ title: t("settings.mcp.addFailed"), description: error instanceof Error ? error.message : t("settings.mcp.checkConfig"), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2"><Network className="h-4 w-4 text-brand-500" />{t("settings.mcp.title")}</CardTitle>
            <CardDescription className="mt-1">{t("settings.mcp.description")}</CardDescription>
          </div>
          <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) resetForm(); }}>
            <DialogTrigger asChild><Button size="sm"><Plus className="mr-1.5 h-4 w-4" />{t("settings.mcp.add")}</Button></DialogTrigger>
            <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
              <DialogHeader><DialogTitle>{t("settings.mcp.addTitle")}</DialogTitle></DialogHeader>
              <div className="space-y-3">
                <Input placeholder={t("settings.mcp.namePlaceholder")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                <Input placeholder={t("settings.mcp.descPlaceholder")} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                <Select value={form.protocol} onValueChange={(protocol: "http" | "sse" | "stdio") => { setForm({ ...EMPTY, name: form.name, description: form.description, protocol }); setHeaderPairs([]); setBodyPairs([]); }}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="http">HTTP</SelectItem><SelectItem value="sse">SSE</SelectItem><SelectItem value="stdio">stdio</SelectItem>
                  </SelectContent>
                </Select>
                {form.protocol === "stdio" ? (
                  <>
                    <Input placeholder={t("settings.mcp.commandPlaceholder")} value={form.command ?? ""} onChange={(e) => setForm({ ...form, command: e.target.value })} />
                    <Input placeholder={t("settings.mcp.argsPlaceholder")} value={(form.args ?? []).join(" ")} onChange={(e) => setForm({ ...form, args: e.target.value.split(/\s+/).filter(Boolean) })} />
                  </>
                ) : (
                  <Input type="url" placeholder="https://example.com/mcp" value={form.url ?? ""} onChange={(e) => setForm({ ...form, url: e.target.value })} />
                )}

                {/* Advanced: custom headers + extra body fields (HTTP/SSE only) */}
                {form.protocol !== "stdio" && (
                  <div className="rounded-md border border-black/5 dark:border-white/5">
                    <button
                      type="button"
                      className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-zinc-600 dark:text-zinc-300"
                      onClick={() => setShowAdvanced(!showAdvanced)}
                    >
                      <span>{t("settings.mcp.advanced")}</span>
                      {showAdvanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </button>
                    {showAdvanced && (
                      <div className="space-y-4 px-3 pb-3">
                        <div className="space-y-1.5">
                          <Label className="text-xs text-zinc-500">{t("settings.mcp.headers")}</Label>
                          <KeyValueEditor
                            pairs={headerPairs}
                            onChange={setHeaderPairs}
                            keyPlaceholder={t("settings.mcp.headerKeyPlaceholder")}
                            valuePlaceholder={t("settings.mcp.headerValuePlaceholder")}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs text-zinc-500">{t("settings.mcp.extraBody")}</Label>
                          <KeyValueEditor
                            pairs={bodyPairs}
                            onChange={setBodyPairs}
                            keyPlaceholder={t("settings.mcp.bodyKeyPlaceholder")}
                            valuePlaceholder={t("settings.mcp.bodyValuePlaceholder")}
                          />
                          <p className="text-[10px] text-zinc-400">
                            {t("settings.mcp.extraBodyHint")}
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
              <DialogFooter><Button onClick={add} disabled={saving || !form.name || (form.protocol === "stdio" ? !form.command : !form.url)}>{t("settings.mcp.save")}</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {servers.length === 0 ? <div className="py-6 text-center text-sm text-zinc-500">{t("settings.mcp.empty")}</div> : servers.map((server) => (
          <div key={server.id} className="flex items-center gap-3 rounded-md border border-black/10 px-3 py-2 dark:border-white/10">
            <Badge variant="default" className="font-mono text-[10px] uppercase">{server.protocol}</Badge>
            <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{server.name}</div><div className="truncate text-xs text-zinc-500">{server.description || t("settings.mcp.noDesc")}</div></div>
            <Switch checked={server.enabled} onCheckedChange={async (enabled) => { await api.toggleMcpServer(server.id, enabled); await mutate(); }} />
            <Button variant="ghost" size="icon" title={t("settings.mcp.delete")} onClick={async () => { await api.deleteMcpServer(server.id); await mutate(); }}><Trash2 className="h-4 w-4 text-red-500" /></Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
