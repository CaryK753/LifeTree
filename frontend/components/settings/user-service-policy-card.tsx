"use client";

import { useEffect, useState } from "react";
import { UserCog } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

export function UserServicePolicyCard() {
  const [enabled, setEnabled] = useState(false);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api.getUserServicePolicy().then((value) => setEnabled(value.enabled)).catch(() => undefined);
  }, []);

  async function update(next: boolean) {
    setSaving(true);
    try {
      const result = await api.setUserServicePolicy(next);
      setEnabled(result.enabled);
      toast({ title: "用户服务配置权限已更新" });
    } catch (error) {
      toast({
        title: "更新失败",
        description: error instanceof Error ? error.message : "请稍后重试",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <UserCog className="h-4 w-4 text-brand-500" />普通用户服务配置
        </CardTitle>
        <CardDescription>
          管理员服务仅展示公开模型与“管理员提供”标签，不向普通用户暴露地址或密钥。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm font-medium">允许普通用户自己配置服务</div>
          <div className="mt-1 text-xs text-zinc-500">LLM、Tavily、MinerU 与默认模型按用户隔离。</div>
        </div>
        <Switch checked={enabled} disabled={saving} onCheckedChange={update} />
      </CardContent>
    </Card>
  );
}
