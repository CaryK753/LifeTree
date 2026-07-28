"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import {
  CheckCircle2,
  KeyRound,
  Link2,
  Loader2,
  Unlink,
} from "lucide-react";
import { api, type OAuthBindingRead, swrConfig } from "@/lib/api";
import { useAuthConfig } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";

/**
 * OAuthBindingCard — lets the current user bind/unbind admin-configured
 * OAuth providers to their account. Shown only in multi-user mode.
 *
 * Moved from /settings to /profile (it's user-account-level config, not
 * system-level). The redirect after a successful OAuth bind round-trip
 * now points to /profile instead of /settings.
 *
 * Bind flow:
 *   1. User clicks "Bind" → call /auth/oauth/{id}/bind-start (requires auth)
 *   2. Backend returns authorize_url with state=bind:<user_id>
 *   3. We set a sessionStorage flag so /auth/callback knows it's a bind
 *      callback (and can redirect back to /profile instead of /)
 *   4. Redirect browser to authorize_url
 *   5. Provider redirects to /auth/callback?provider=...&code=...&state=...
 *   6. /auth/callback calls /auth/oauth/{id}/callback which detects bind
 *      mode from state, links external_sub to user, returns JWT pair
 *   7. /auth/callback sees bind flag → redirects to /profile
 *
 * Bug fix: previously used a plain useState + useEffect with [] deps,
 * which meant the binding list was only fetched once on mount. When the
 * user returned from the OAuth callback, the component re-mounted but
 * the fetch could race with the callback's database write, or the
 * Next.js router cache served a stale component. Now we use SWR with
 * revalidateOnMount + revalidateOnFocus so the list always reflects the
 * current DB state when the user lands back on /profile.
 */
export function OAuthBindingCard() {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data: authConfig } = useAuthConfig();
  const [bindingId, setBindingId] = useState<string | null>(null);
  const [unbindingId, setUnbindingId] = useState<string | null>(null);

  const providers = authConfig?.oauth_providers ?? [];

  // SWR fetcher for the user's current OAuth bindings.
  // revalidateOnMount ensures we always fetch fresh data on mount (fixes
  // the "still shows unbound after bind" bug), and revalidateOnFocus
  // catches the case where the user tabs back from the OAuth popup.
  const { data: bindings, mutate: revalidateBindings } = useSWR<OAuthBindingRead[]>(
    "oauth-bindings",
    () => api.listOAuthBindings(),
    { ...swrConfig, revalidateOnMount: true, revalidateOnFocus: true }
  );

  async function handleBind(providerId: string) {
    setBindingId(providerId);
    try {
      const { authorize_url } = await api.oauthBindStart(providerId);
      // Mark this as a bind flow so /auth/callback redirects back to /profile
      // after the OAuth round-trip.
      try {
        sessionStorage.setItem("lifetree.oauth.bind", providerId);
      } catch {
        // sessionStorage might be unavailable (private mode) — non-fatal.
      }
      // Full-page redirect to the provider's authorize URL.
      window.location.href = authorize_url;
    } catch (e: any) {
      const detail =
        (e as { details?: { detail?: string } })?.details?.detail ||
        (e as Error)?.message ||
        t("settings.oauthBinding.bindFailed");
      toast({
        title: t("settings.oauthBinding.bindFailed"),
        description: detail,
        variant: "error",
      });
      setBindingId(null);
    }
  }

  async function handleUnbind(providerId: string, providerName: string) {
    const ok = await confirm({
      title: t("settings.oauthBinding.unbind"),
      description: t("settings.oauthBinding.unbindConfirm", { name: providerName }),
      confirmLabel: t("settings.oauthBinding.unbind"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (!ok) return;
    setUnbindingId(providerId);
    try {
      await api.unbindOAuth(providerId);
      // Optimistically remove from local cache, then revalidate.
      await revalidateBindings();
      toast({ title: t("settings.oauthBinding.unbind"), variant: "success" });
    } catch (e: any) {
      const detail =
        (e as { details?: { detail?: string } })?.details?.detail ||
        (e as Error)?.message ||
        t("settings.oauthBinding.unbindFailed");
      toast({
        title: t("settings.oauthBinding.unbindFailed"),
        description: detail,
        variant: "error",
      });
    } finally {
      setUnbindingId(null);
    }
  }

  // Build a provider_id → binding map for quick lookup.
  const bindingMap = new Map((bindings ?? []).map((b) => [b.provider_id, b]));
  const loading = bindings === undefined;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-brand-600 dark:text-brand-400" />
            {t("settings.oauthBinding.title")}
          </CardTitle>
          <CardDescription className="mt-1">
            {t("settings.oauthBinding.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-zinc-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("common.loading")}
          </div>
        ) : providers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <KeyRound className="h-8 w-8 text-zinc-600 mb-3" />
            <div className="text-sm text-zinc-800 dark:text-zinc-300">
              {t("settings.oauthBinding.empty")}
            </div>
          </div>
        ) : (
          providers.map((p) => {
            const binding = bindingMap.get(p.id);
            const isBound = !!binding;
            return (
              <div
                key={p.id}
                className="flex items-center justify-between gap-3 p-3 rounded-lg border border-black/5 dark:border-white/5 bg-surface/30"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    {p.avatar_url ? (
                      /* eslint-disable-next-line @next/next/no-img-element */
                      <img
                        src={p.avatar_url}
                        alt=""
                        className="h-5 w-5 rounded-sm object-cover"
                      />
                    ) : null}
                    <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                      {p.name}
                    </span>
                    {isBound ? (
                      <Badge className="text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200">
                        <CheckCircle2 className="h-2.5 w-2.5 mr-0.5" />
                        {t("settings.oauthBinding.bound")}
                      </Badge>
                    ) : (
                      <Badge className="text-[10px] border-zinc-400/30 dark:border-zinc-700/50 bg-zinc-200/50 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400">
                        {t("settings.oauthBinding.notBound")}
                      </Badge>
                    )}
                  </div>
                  {isBound && binding?.created_at && (
                    <div className="mt-1 text-[10px] text-zinc-500">
                      {t("settings.oauthBinding.boundAt", {
                        date: new Date(binding.created_at).toLocaleString(),
                      })}
                    </div>
                  )}
                </div>
                <div className="shrink-0">
                  {isBound ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 text-xs hover:text-red-600 dark:hover:text-red-300"
                      onClick={() => handleUnbind(p.id, p.name)}
                      disabled={unbindingId !== null}
                    >
                      {unbindingId === p.id ? (
                        <Loader2 className="h-3 w-3 mr-1.5 animate-spin" />
                      ) : (
                        <Unlink className="h-3 w-3 mr-1.5" />
                      )}
                      {t("settings.oauthBinding.unbind")}
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 text-xs"
                      onClick={() => handleBind(p.id)}
                      disabled={bindingId !== null}
                    >
                      {bindingId === p.id ? (
                        <Loader2 className="h-3 w-3 mr-1.5 animate-spin" />
                      ) : (
                        <Link2 className="h-3 w-3 mr-1.5" />
                      )}
                      {bindingId === p.id
                        ? t("settings.oauthBinding.processing")
                        : t("settings.oauthBinding.bind")}
                    </Button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </CardContent>
      {ConfirmRoot}
    </Card>
  );
}
