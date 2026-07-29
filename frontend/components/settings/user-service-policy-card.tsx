"use client";

import { useEffect, useState } from "react";
import { UserCog } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

export function UserServicePolicyCard() {
  const [enabled, setEnabled] = useState(false);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const t = useT();

  useEffect(() => {
    api.getUserServicePolicy().then((value) => setEnabled(value.enabled)).catch(() => undefined);
  }, []);

  async function update(next: boolean) {
    setSaving(true);
    try {
      const result = await api.setUserServicePolicy(next);
      setEnabled(result.enabled);
      toast({ title: t("admin.userPolicy.updated") });
    } catch (error) {
      toast({
        title: t("admin.userPolicy.updateFailed"),
        description: error instanceof Error ? error.message : t("admin.userPolicy.retryLater"),
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
          <UserCog className="h-4 w-4 text-brand-500" />{t("admin.userPolicy.title")}
        </CardTitle>
        <CardDescription>
          {t("admin.userPolicy.description")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm font-medium">{t("admin.userPolicy.allowTitle")}</div>
          <div className="mt-1 text-xs text-zinc-500">{t("admin.userPolicy.allowDesc")}</div>
        </div>
        <Switch checked={enabled} disabled={saving} onCheckedChange={update} />
      </CardContent>
    </Card>
  );
}
