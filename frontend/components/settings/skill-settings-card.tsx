"use client";

import { useState } from "react";
import { BookOpen, FolderUp, Github, Plus, Trash2, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { useUserSkills } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";

export function SkillSettingsCard() {
  const { data: skills = [], mutate } = useUserSkills();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [github, setGithub] = useState("");
  const [archive, setArchive] = useState<File | null>(null);
  const [folder, setFolder] = useState<File[]>([]);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  async function importSkill(mode: string) {
    setSaving(true);
    try {
      if (mode === "text") await api.addTextSkill(name, text);
      if (mode === "github") await api.addGithubSkill(name, github);
      if (mode === "archive" && archive) await api.addArchiveSkill(name, archive);
      if (mode === "folder" && folder.length) await api.addFolderSkill(name, folder);
      await mutate();
      setOpen(false); setName(""); setText(""); setGithub(""); setArchive(null); setFolder([]);
      toast({ title: "Skill 已导入" });
    } catch (error) {
      toast({ title: "导入失败", description: error instanceof Error ? error.message : "请检查内容", variant: "error" });
    } finally { setSaving(false); }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div><CardTitle className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-brand-500" />Skills</CardTitle><CardDescription className="mt-1">作为用户上下文参与任务规划，不能覆盖系统安全规则。</CardDescription></div>
          <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm"><Plus className="mr-1.5 h-4 w-4" />导入</Button></DialogTrigger>
            <DialogContent className="max-w-xl"><DialogHeader><DialogTitle>导入 Skill</DialogTitle></DialogHeader>
              <Input placeholder="Skill 名称" value={name} onChange={(e) => setName(e.target.value)} />
              <Tabs defaultValue="text" className="mt-3">
                <TabsList className="grid grid-cols-4"><TabsTrigger value="text">文本</TabsTrigger><TabsTrigger value="archive">压缩包</TabsTrigger><TabsTrigger value="folder">文件夹</TabsTrigger><TabsTrigger value="github">GitHub</TabsTrigger></TabsList>
                <TabsContent value="text" className="space-y-3"><textarea className="min-h-40 w-full rounded-md border border-black/10 bg-transparent p-3 text-sm dark:border-white/10" placeholder="粘贴 SKILL.md 或说明文本" value={text} onChange={(e) => setText(e.target.value)} /><ImportButton disabled={!name || !text} saving={saving} onClick={() => importSkill("text")} /></TabsContent>
                <TabsContent value="archive" className="space-y-3"><FileDrop icon={Upload} label={archive?.name || "选择 ZIP / TAR 压缩包"}><input type="file" accept=".zip,.tar,.gz,.tgz" onChange={(e) => setArchive(e.target.files?.[0] ?? null)} /></FileDrop><ImportButton disabled={!name || !archive} saving={saving} onClick={() => importSkill("archive")} /></TabsContent>
                <TabsContent value="folder" className="space-y-3"><FileDrop icon={FolderUp} label={folder.length ? `已选择 ${folder.length} 个文件` : "选择一个文件夹"}><input ref={(node) => node?.setAttribute("webkitdirectory", "")} type="file" multiple onChange={(e) => setFolder(Array.from(e.target.files ?? []))} /></FileDrop><ImportButton disabled={!name || !folder.length} saving={saving} onClick={() => importSkill("folder")} /></TabsContent>
                <TabsContent value="github" className="space-y-3"><div className="flex items-center gap-2"><Github className="h-4 w-4" /><Input type="url" placeholder="https://github.com/owner/repo" value={github} onChange={(e) => setGithub(e.target.value)} /></div><ImportButton disabled={!name || !github} saving={saving} onClick={() => importSkill("github")} /></TabsContent>
              </Tabs>
            </DialogContent></Dialog>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">{skills.length === 0 ? <div className="py-6 text-center text-sm text-zinc-500">尚未导入 Skill</div> : skills.map((skill) => <div key={skill.id} className="flex items-center gap-3 rounded-md border border-black/10 px-3 py-2 dark:border-white/10"><Badge variant="default" className="text-[10px]">{skill.source_type}</Badge><div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{skill.name}</div><div className="truncate text-xs text-zinc-500">{skill.content_preview}</div></div><Switch checked={skill.enabled} onCheckedChange={async (enabled) => { await api.toggleSkill(skill.id, enabled); await mutate(); }} /><Button variant="ghost" size="icon" title="删除" onClick={async () => { await api.deleteSkill(skill.id); await mutate(); }}><Trash2 className="h-4 w-4 text-red-500" /></Button></div>)}</CardContent>
    </Card>
  );
}

function ImportButton({ disabled, saving, onClick }: { disabled: boolean; saving: boolean; onClick: () => void }) { return <DialogFooter><Button disabled={disabled || saving} onClick={onClick}>导入</Button></DialogFooter>; }
function FileDrop({ icon: Icon, label, children }: { icon: typeof Upload; label: string; children: React.ReactNode }) { return <label className="flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed border-black/20 p-8 text-sm text-zinc-500 hover:bg-black/[0.02] dark:border-white/20 dark:hover:bg-white/[0.02]"><Icon className="h-6 w-6" /><span>{label}</span><span className="sr-only">{children}</span></label>; }
