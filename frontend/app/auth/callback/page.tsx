"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";

/**
 * OAuth callback page.
 *
 * OAuth providers redirect here with ``?provider=...&code=...&state=...``.
 * We forward the code+state to the backend
 * (``GET /auth/oauth/{provider_id}/callback``) which exchanges it for our
 * JWT pair. On success we redirect to ``/``; on failure we show a toast
 * and redirect to ``/`` so the user can try again.
 *
 * Why a dedicated page (not a dialog hook):
 *   - The provider's redirect is a full-page browser navigation, so the
 *     SPA isn't running at the moment of arrival — a fresh page load is
 *     the only thing that can intercept it.
 *   - Keeping the logic here keeps the LoginDialog pure (form-only),
 *     which simplifies error handling and avoids edge cases around the
 *     dialog being closed when the redirect lands.
 */
export default function OAuthCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const t = useT();
  const toast = useToast();
  const { loginWithOAuth } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    const provider = params.get("provider") || "";
    const code = params.get("code") || "";
    const state = params.get("state") || undefined;
    const oauthError = params.get("error") || params.get("error_description");

    if (oauthError) {
      const msg = t("auth.loginFailed") + ": " + oauthError;
      setError(msg);
      toast({ title: t("auth.loginFailed"), description: msg, variant: "error" });
      setTimeout(() => router.replace("/"), 1500);
      return;
    }

    if (!provider || !code) {
      const msg = "Missing provider or code in OAuth callback";
      setError(msg);
      toast({ title: t("auth.loginFailed"), description: msg, variant: "error" });
      setTimeout(() => router.replace("/"), 1500);
      return;
    }

    loginWithOAuth(provider, code, state)
      .then(() => {
        toast({ title: t("auth.loginSuccess"), variant: "success" });
        router.replace("/");
      })
      .catch((err: unknown) => {
        const detail =
          (err as { details?: { detail?: string } })?.details?.detail ||
          (err as Error)?.message ||
          t("auth.loginFailed");
        setError(detail);
        toast({
          title: t("auth.loginFailed"),
          description: detail,
          variant: "error",
        });
        setTimeout(() => router.replace("/"), 2000);
      });
  }, [params, router, loginWithOAuth, t, toast]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-zinc-50 dark:bg-zinc-950">
      <Loader2 className="h-6 w-6 animate-spin text-brand-600 dark:text-brand-400" />
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        {error ?? t("auth.oauth.processing")}
      </p>
    </div>
  );
}
