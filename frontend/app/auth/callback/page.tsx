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
 * Two flows share this callback:
 *   - **Login**: state = ``<provider_id>``. After success → redirect to ``/``.
 *   - **Bind**: state = ``bind:<user_id>``. The settings page sets a
 *     ``lifetree.oauth.bind`` sessionStorage flag before redirecting to the
 *     provider so we know to send the user back to ``/settings`` (and show
 *     "binding" messaging instead of "logging in") after the round-trip.
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

  // Detect bind/register mode via sessionStorage flags set by the
  // originating page (OAuthBindingCard / LoginDialog). We read them once
  // on mount (before the callback fires) so we can pick the right
  // success message and redirect target.
  const isBindFlow = (() => {
    try {
      return !!sessionStorage.getItem("lifetree.oauth.bind");
    } catch {
      return false;
    }
  })();
  const isRegisterFlow = (() => {
    try {
      return !!sessionStorage.getItem("lifetree.oauth.register");
    } catch {
      return false;
    }
  })();

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    const provider = params.get("provider") || "";
    const code = params.get("code") || "";
    const state = params.get("state") || undefined;
    const oauthError = params.get("error") || params.get("error_description");

    // Always clear the bind/register flags — whether success or failure —
    // so stale flags don't bleed into a later flow.
    try {
      sessionStorage.removeItem("lifetree.oauth.bind");
      sessionStorage.removeItem("lifetree.oauth.register");
    } catch {
      // ignore
    }

    if (oauthError) {
      const base = isBindFlow ? t("auth.oauth.bindFailed") : t("auth.loginFailed");
      const msg = base + ": " + oauthError;
      setError(msg);
      toast({ title: base, description: msg, variant: "error" });
      setTimeout(() => router.replace(isBindFlow ? "/settings" : "/"), 1500);
      return;
    }

    if (!provider || !code) {
      const msg = "Missing provider or code in OAuth callback";
      setError(msg);
      const base = isBindFlow ? t("auth.oauth.bindFailed") : t("auth.loginFailed");
      toast({ title: base, description: msg, variant: "error" });
      setTimeout(() => router.replace(isBindFlow ? "/settings" : "/"), 1500);
      return;
    }

    loginWithOAuth(provider, code, state)
      .then(() => {
        if (isBindFlow) {
          toast({ title: t("auth.oauth.bindSuccess"), variant: "success" });
          router.replace("/settings");
        } else if (isRegisterFlow) {
          toast({ title: t("auth.registerSuccess"), variant: "success" });
          router.replace("/");
        } else {
          toast({ title: t("auth.loginSuccess"), variant: "success" });
          router.replace("/");
        }
      })
      .catch((err: unknown) => {
        const detail =
          (err as { details?: { detail?: string } })?.details?.detail ||
          (err as Error)?.message ||
          (isBindFlow ? t("auth.oauth.bindFailed") : t("auth.loginFailed"));
        setError(detail);
        toast({
          title: isBindFlow ? t("auth.oauth.bindFailed") : t("auth.loginFailed"),
          description: detail,
          variant: "error",
        });
        setTimeout(() => router.replace(isBindFlow ? "/settings" : "/"), 2000);
      });
  }, [params, router, loginWithOAuth, t, toast, isBindFlow, isRegisterFlow]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-zinc-50 dark:bg-zinc-950">
      <Loader2 className="h-6 w-6 animate-spin text-brand-600 dark:text-brand-400" />
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        {error ?? (isBindFlow ? t("auth.oauth.bindProcessing") : t("auth.oauth.processing"))}
      </p>
    </div>
  );
}
