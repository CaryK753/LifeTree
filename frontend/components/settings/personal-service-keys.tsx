"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";
import { api } from "@/lib/api";
import { useRuntimeCatalog } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

export function PersonalServiceKeys() {
  const { data: catalog, mutate } = useRuntimeCatalog();
  const [tavily, setTavily] = useState("");
  const [mineru, setMineru] = useState("");
  const [mineruUrl, setMineruUrl] = useState("");
  const toast = useToast();
  const t = useT();
  // Show personal service keys when the admin has enabled the policy,
  // regardless of whether the current user is an admin or not.
  if (!catalog?.allow_user_service_config) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-brand-500" />{t("settings.personalKeys.title")}</CardTitle>
        <CardDescription>{t("settings.personalKeys.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label className="text-xs text-zinc-500">{t("settings.personalKeys.tavilyLabel")}</Label>
            <Input type="password" placeholder={catalog.tavily_configured ? t("settings.personalKeys.tavilyConfigured") : "Tavily API Key"} value={tavily} onChange={(e) => setTavily(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-zinc-500">{t("settings.personalKeys.mineruLabel")}</Label>
            <Input type="password" placeholder={catalog.mineru_configured ? t("settings.personalKeys.mineruConfigured") : "MinerU API Key"} value={mineru} onChange={(e) => setMineru(e.target.value)} />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-zinc-500">{t("settings.personalKeys.mineruUrlLabel")}</Label>
          <Input placeholder={catalog.mineru_base_url || "MinerU Base URL"} value={mineruUrl} onChange={(e) => setMineruUrl(e.target.value)} />
        </div>
        <div className="flex justify-end">
          <Button size="sm" onClick={async () => { try { await api.setUserServices({ tavily_api_key: tavily || null, mineru_api_key: mineru || null, mineru_base_url: mineruUrl || null }); await mutate(); setTavily(""); setMineru(""); toast({ title: t("settings.personalKeys.saved") }); } catch (error) { toast({ title: t("settings.personalKeys.saveFailed"), description: error instanceof Error ? error.message : t("settings.personalKeys.retryLater"), variant: "error" }); } }}>{t("settings.personalKeys.save")}</Button>
        </div>
      </CardContent>
    </Card>
  );
}
