"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";

/**
 * Shared OAuth callback body.
 *
 * Receives the ``provider`` id explicitly (either from the URL path in the
 * ``/auth/callback/[provider]`` route, or from the ``?provider=`` query
 * param in the legacy ``/auth/callback`` route). The OAuth 2.0 standard
 * only returns ``code`` and ``state`` in the callback URL — the provider
 * id has to come from the path or be baked into the redirect_uri.
 *
 * Two flows share this callback:
 *   - **Login**: state = ``login:<provider_id>``. After success → redirect to ``/``.
 *   - **Register**: state = ``register:<provider_id>``. After success →
 *     redirect to ``/`` with a register-success toast.
 *   - **Bind**: state = ``bind:<user_id>``. The profile page sets a
 *     ``lifetree.oauth.bind`` sessionStorage flag before redirecting to the
 *     provider so we know to send the user back to ``/profile`` (and show
 *     "binding" messaging instead of "logging in") after the round-trip.
 */
export function OAuthCallbackHandler({ provider }: { provider: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const t = useT();
  const toast = useToast();
  const { loginWithOAuth } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const ranRef = useRef(false);

  // Detect bind/register mode via sessionStorage flags set by the
  // originating page (OAuthBindingCard / /auth page). We read them once
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

    // Allow ?provider=... to override the path-supplied provider (legacy
    // /auth/callback?provider=xxx route). In the dynamic route the prop
    // already carries the provider id and this query param is absent.
    const providerFromQuery = params.get("provider");
    const effectiveProvider = providerFromQuery || provider;
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
      setTimeout(() => router.replace(isBindFlow ? "/profile" : "/"), 1500);
      return;
    }

    if (!effectiveProvider || !code) {
      const msg = isBindFlow
        ? t("auth.oauth.bindFailed")
        : t("auth.loginFailed");
      const desc = t("auth.oauth.missingParams");
      setError(desc);
      toast({ title: msg, description: desc, variant: "error" });
      setTimeout(() => router.replace(isBindFlow ? "/profile" : "/"), 1500);
      return;
    }

    loginWithOAuth(effectiveProvider, code, state)
      .then(() => {
        if (isBindFlow) {
          toast({ title: t("auth.oauth.bindSuccess"), variant: "success" });
          router.replace("/profile");
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
        setTimeout(() => router.replace(isBindFlow ? "/profile" : "/"), 2000);
      });
  }, [params, router, loginWithOAuth, t, toast, isBindFlow, isRegisterFlow, provider]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-zinc-50 dark:bg-zinc-950">
      <Loader2 className="h-6 w-6 animate-spin text-brand-600 dark:text-brand-400" />
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        {error ?? (isBindFlow ? t("auth.oauth.bindProcessing") : t("auth.oauth.processing"))}
      </p>
    </div>
  );
}
