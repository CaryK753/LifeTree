"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth, useRuntimeCatalog } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";

export function PersonalServiceKeys() {
  const { isAdmin } = useAuth();
  const { data: catalog, mutate } = useRuntimeCatalog();
  const [tavily, setTavily] = useState("");
  const [mineru, setMineru] = useState("");
  const [mineruUrl, setMineruUrl] = useState("");
  const toast = useToast();
  if (isAdmin || !catalog?.allow_user_service_config) return null;
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-brand-500" />我的检索与解析服务</CardTitle><CardDescription>已保存的密钥不会回显；留空字段不会覆盖现有配置。</CardDescription></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2"><Input type="password" placeholder={catalog.tavily_configured ? "Tavily 已配置" : "Tavily API Key"} value={tavily} onChange={(e) => setTavily(e.target.value)} /><Input type="password" placeholder={catalog.mineru_configured ? "MinerU 已配置" : "MinerU API Key"} value={mineru} onChange={(e) => setMineru(e.target.value)} /><Input className="sm:col-span-2" placeholder={catalog.mineru_base_url || "MinerU Base URL"} value={mineruUrl} onChange={(e) => setMineruUrl(e.target.value)} /><div className="sm:col-span-2 flex justify-end"><Button size="sm" onClick={async () => { try { await api.setUserServices({ tavily_api_key: tavily || null, mineru_api_key: mineru || null, mineru_base_url: mineruUrl || null }); await mutate(); setTavily(""); setMineru(""); toast({ title: "个人服务配置已保存" }); } catch (error) { toast({ title: "保存失败", description: error instanceof Error ? error.message : "请稍后重试", variant: "error" }); } }}>保存</Button></div></CardContent></Card>;
}
