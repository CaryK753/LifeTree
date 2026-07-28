"use client";

import { useEffect, useRef, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Loader2,
  LogIn,
  Mail,
  ShieldCheck,
  UserPlus,
  KeyRound,
  ArrowLeft,
} from "lucide-react";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { useAuth, useAuthConfig } from "@/lib/hooks";
import { api, setTokens } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AsciiTreeBackground } from "@/components/auth/ascii-tree-bg";

async function switchToSingleMode() {
  try {
    await api.setUseMode("single");
    window.location.href = "/";
  } catch (err) {
    console.error("Failed to switch to single mode:", err);
    window.location.reload();
  }
}

/**
 * Decode a base64url string into a Uint8Array. WebAuthn API requires
 * ArrayBuffer inputs for challenge / credential_id fields.
 */
function base64urlToUint8Array(b64: string): Uint8Array {
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const b64std = padded.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64std);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function uint8ArrayToBase64url(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  const b64 = btoa(bin);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function isPasskeySupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    typeof PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.credentials !== "undefined"
  );
}

function AuthPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useT();
  const toast = useToast();
  const { login, register, registerWithCode, user, isAuthenticated } = useAuth();
  const { data: authConfig } = useAuthConfig();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [loading, setLoading] = useState(false);
  const [oauthLoadingId, setOauthLoadingId] = useState<string | null>(null);
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const [form, setForm] = useState({
    displayName: "",
    email: "",
    password: "",
    code: "",
  });
  const [codeSending, setCodeSending] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const cooldownTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // first-admin setup: when no users exist yet, force register mode.
  // Also triggered by ?first_admin=1 query param (from AuthGate redirect).
  const hasUsers = authConfig?.has_users ?? true;
  const firstAdminQuery = searchParams.get("first_admin") === "1";
  const firstAdminSetup = !hasUsers || firstAdminQuery;
  const effectiveMode = firstAdminSetup ? "register" : mode;
  const useMode = authConfig?.use_mode ?? (authConfig?.multi_user_mode ? "multi" : "single");

  const emailVerificationEnabled = !!authConfig?.email_verification_enabled;
  const disableRegistration =
    (!!authConfig?.disable_registration && !firstAdminSetup);
  const oauthProviders = authConfig?.oauth_providers ?? [];

  // ?mode=register 初始进入注册
  useEffect(() => {
    const initial = searchParams.get("mode");
    if (initial === "register" && !disableRegistration && !firstAdminSetup) {
      setMode("register");
    }
  }, [searchParams, disableRegistration, firstAdminSetup]);

  // 已登录则自动跳回首页
  useEffect(() => {
    if (isAuthenticated && user) {
      router.replace("/");
    }
  }, [isAuthenticated, user, router]);

  useEffect(() => {
    if (firstAdminSetup) setMode("register");
    else if (disableRegistration) setMode("login");
  }, [firstAdminSetup, disableRegistration]);

  useEffect(() => {
    return () => {
      if (cooldownTimer.current) clearInterval(cooldownTimer.current);
    };
  }, []);

  async function sendCode() {
    const email = form.email.trim();
    if (!email) {
      toast({
        title: t("auth.verifyCode.required"),
        description: t("auth.email"),
        variant: "error",
      });
      return;
    }
    setCodeSending(true);
    try {
      const res = await api.sendCode(email);
      if (res.ok) {
        toast({
          title: t("auth.verifyCode.sent", { email }),
          variant: "success",
        });
        setCodeCooldown(60);
        cooldownTimer.current = setInterval(() => {
          setCodeCooldown((s) => {
            if (s <= 1) {
              if (cooldownTimer.current) {
                clearInterval(cooldownTimer.current);
                cooldownTimer.current = null;
              }
              return 0;
            }
            return s - 1;
          });
        }, 1000);
      } else {
        toast({
          title: t("auth.loginFailed"),
          description: res.error || t("auth.verifyCode.invalid"),
          variant: "error",
        });
      }
    } catch (err: unknown) {
      const detail =
        (err as { details?: { detail?: string } })?.details?.detail ||
        (err as Error)?.message ||
        t("auth.loginFailed");
      toast({
        title: t("auth.loginFailed"),
        description: detail,
        variant: "error",
      });
    } finally {
      setCodeSending(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      if (effectiveMode === "login") {
        await login(form.email.trim(), form.password);
        toast({ title: t("auth.loginSuccess"), variant: "success" });
      } else {
        if (emailVerificationEnabled) {
          if (!form.code.trim()) {
            toast({
              title: t("auth.verifyCode.required"),
              description: t("auth.verifyCode.field"),
              variant: "error",
            });
            return;
          }
          await registerWithCode({
            display_name: form.displayName.trim(),
            email: form.email.trim(),
            code: form.code.trim(),
            password: form.password ? form.password : undefined,
          });
        } else {
          await register(
            form.displayName.trim(),
            form.email.trim(),
            form.password
          );
        }
        toast({ title: t("auth.registerSuccess"), variant: "success" });
      }
      // Force a full page reload so all SWR caches refetch.
      window.location.href = "/";
    } catch (err: unknown) {
      const message =
        (err as { details?: { detail?: string } })?.details?.detail ||
        (err as Error)?.message ||
        t("auth.loginFailed");
      toast({
        title: t("auth.loginFailed"),
        description: message,
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleOAuth(
    providerId: string,
    oauthMode: "login" | "register" = "login"
  ) {
    setOauthLoadingId(providerId);
    try {
      const { authorize_url } = await api.oauthStart(providerId, oauthMode);
      if (oauthMode === "register") {
        try {
          sessionStorage.setItem("lifetree.oauth.register", providerId);
        } catch {
          /* non-fatal */
        }
      }
      window.location.href = authorize_url;
    } catch (err: unknown) {
      const detail =
        (err as { details?: { detail?: string } })?.details?.detail ||
        (err as Error)?.message ||
        t("auth.loginFailed");
      toast({
        title: t("auth.loginFailed"),
        description: detail,
        variant: "error",
      });
      setOauthLoadingId(null);
    }
  }

  async function handlePasskeyLogin() {
    if (!isPasskeySupported()) {
      toast({
        title: t("auth.passkeyUnsupported"),
        variant: "error",
      });
      return;
    }
    setPasskeyLoading(true);
    try {
      const { options } = await api.passkeyAuthOptions();
      const publicKey: PublicKeyCredentialRequestOptions = {
        ...options,
        challenge: base64urlToUint8Array(
          (options as { challenge?: string }).challenge ?? ""
        ),
        allowCredentials: (
          (options as { allowCredentials?: Array<{ id: string }> })
            .allowCredentials ?? []
        ).map((c) => ({
          ...c,
          id: base64urlToUint8Array(c.id),
          type: "public-key" as PublicKeyCredentialType,
        })),
      };
      const credential = (await navigator.credentials.get({
        publicKey,
      })) as PublicKeyCredential | null;
      if (!credential) {
        toast({
          title: t("auth.passkeyLoginCanceled"),
          variant: "error",
        });
        return;
      }
      const response = credential.response as AuthenticatorAssertionResponse;
      const serializedCredential = {
        id: credential.id,
        rawId: uint8ArrayToBase64url(credential.rawId),
        type: credential.type,
        response: {
          authenticatorData: uint8ArrayToBase64url(response.authenticatorData),
          clientDataJSON: uint8ArrayToBase64url(response.clientDataJSON),
          signature: uint8ArrayToBase64url(response.signature),
          userHandle: response.userHandle
            ? uint8ArrayToBase64url(response.userHandle)
            : null,
        },
        clientExtensionResults:
          credential.getClientExtensionResults?.() ?? {},
      };
      const res = await api.passkeyAuthVerify(serializedCredential);
      setTokens(res.access_token, res.refresh_token);
      toast({ title: t("auth.loginSuccess"), variant: "success" });
      window.location.href = "/";
    } catch (e: unknown) {
      const err = e as { name?: string; message?: string };
      const name = err?.name ?? "";
      if (name === "NotAllowedError" || name === "AbortError") {
        toast({
          title: t("auth.passkeyLoginCanceled"),
          variant: "error",
        });
      } else {
        toast({
          title: t("auth.passkeyLoginFailed"),
          description: err?.message,
          variant: "error",
        });
      }
    } finally {
      setPasskeyLoading(false);
    }
  }

  const passwordRequired = effectiveMode === "login" || !emailVerificationEnabled;

  return (
    <div className="relative min-h-screen overflow-hidden bg-zinc-50 dark:bg-[#0b0d12]">
      {/* ASCII 动态生长树背景 */}
      <div className="absolute inset-0">
        <AsciiTreeBackground />
      </div>

      {/* 顶部返回首页链接 */}
      <div className="absolute left-4 top-4 z-10 safe-top">
        <button
          type="button"
          onClick={() => router.push("/")}
          className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {t("app.name")}
        </button>
      </div>

      {/* 居中登录卡片 */}
      <div className="relative z-10 flex min-h-screen items-center justify-center p-4 safe-top safe-bottom">
        <div className="w-full max-w-md rounded-xl border border-zinc-200/80 bg-white/80 p-6 shadow-2xl backdrop-blur-md dark:border-white/10 dark:bg-[#13161c]/85 sm:p-7">
          {/* 标题 */}
          <div className="mb-5">
            <h1 className="flex items-center gap-2 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
              {firstAdminSetup ? (
                <ShieldCheck className="h-5 w-5 text-amber-500" />
              ) : (
                <LogIn className="h-5 w-5 text-brand-600 dark:text-brand-400" />
              )}
              {firstAdminSetup
                ? t("auth.firstAdminTitle")
                : effectiveMode === "login"
                  ? t("auth.loginTitle")
                  : t("auth.registerTitle")}
            </h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              {firstAdminSetup
                ? t("auth.firstAdminDesc")
                : effectiveMode === "login"
                  ? t("auth.loginDesc")
                  : t("auth.registerDesc")}
            </p>
          </div>

          {/* Tabs */}
          {!firstAdminSetup && !disableRegistration && (
            <div className="mb-4 flex gap-1 rounded-md bg-black/[0.04] p-1 dark:bg-white/[0.04]">
              <button
                type="button"
                onClick={() => setMode("login")}
                className={cn(
                  "flex-1 rounded px-3 py-1.5 text-sm font-medium transition-colors",
                  mode === "login"
                    ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-900 dark:text-zinc-100"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                )}
              >
                {t("auth.tabLogin")}
              </button>
              <button
                type="button"
                onClick={() => setMode("register")}
                className={cn(
                  "flex-1 rounded px-3 py-1.5 text-sm font-medium transition-colors",
                  mode === "register"
                    ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-900 dark:text-zinc-100"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                )}
              >
                {t("auth.tabRegister")}
              </button>
            </div>
          )}

          <form onSubmit={submit} className="space-y-3">
            {effectiveMode === "register" && (
              <Field label={t("auth.displayName")}>
                <Input
                  value={form.displayName}
                  onChange={(e) =>
                    setForm({ ...form, displayName: e.target.value })
                  }
                  placeholder={t("auth.displayNamePlaceholder")}
                  className="h-9 text-sm"
                  required
                  autoFocus
                />
              </Field>
            )}
            <Field label={t("auth.email")}>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="you@example.com"
                className="h-9 text-sm"
                required
                autoFocus={effectiveMode === "login"}
              />
            </Field>
            <Field label={t("auth.password")}>
              <Input
                type="password"
                value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })
                }
                placeholder="••••••••"
                className="h-9 text-sm"
                required={passwordRequired}
                minLength={passwordRequired ? 6 : undefined}
              />
              {effectiveMode === "register" && emailVerificationEnabled && (
                <p className="text-[10px] leading-snug text-zinc-500">
                  {t("auth.passwordOptionalHint")}
                </p>
              )}
            </Field>

            {effectiveMode === "register" && emailVerificationEnabled && (
              <Field label={t("auth.verifyCode.field")}>
                <div className="flex gap-2">
                  <Input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={8}
                    value={form.code}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        code: e.target.value.replace(/\D/g, ""),
                      })
                    }
                    placeholder={t("auth.verifyCode.placeholder")}
                    className="h-9 flex-1 text-sm"
                    required
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={sendCode}
                    disabled={
                      codeSending ||
                      codeCooldown > 0 ||
                      !form.email.trim()
                    }
                    className="h-9 shrink-0 px-3"
                  >
                    {codeSending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : codeCooldown > 0 ? (
                      t("auth.verifyCode.resend", { seconds: codeCooldown })
                    ) : (
                      t("auth.verifyCode.send")
                    )}
                  </Button>
                </div>
              </Field>
            )}

            <Button type="submit" disabled={loading} className="h-9 w-full">
              {loading ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : firstAdminSetup ? (
                <ShieldCheck className="mr-1.5 h-4 w-4" />
              ) : effectiveMode === "login" ? (
                <LogIn className="mr-1.5 h-4 w-4" />
              ) : (
                <UserPlus className="mr-1.5 h-4 w-4" />
              )}
              {firstAdminSetup
                ? t("auth.firstAdminButton")
                : effectiveMode === "login"
                  ? t("auth.login")
                  : emailVerificationEnabled
                    ? t("auth.verifyCode.register")
                    : t("auth.register")}
            </Button>

            {/* Passkey login — login tab only */}
            {!firstAdminSetup &&
              effectiveMode === "login" &&
              authConfig?.passkey_login_enabled &&
              isPasskeySupported() && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={handlePasskeyLogin}
                  disabled={passkeyLoading || loading || oauthLoadingId !== null}
                  className="h-9 w-full"
                >
                  {passkeyLoading ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <KeyRound className="mr-1.5 h-4 w-4" />
                  )}
                  {passkeyLoading
                    ? t("auth.passkeyDiscovering")
                    : t("auth.passkeyLogin")}
                </Button>
              )}
          </form>

          {/* OAuth */}
          {oauthProviders.length > 0 &&
            !(effectiveMode === "register" && disableRegistration) && (
              <div className="mt-4 space-y-2">
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t border-zinc-200 dark:border-zinc-800" />
                  </div>
                  <div className="relative flex justify-center">
                    <span className="bg-white/80 px-2 text-[11px] text-zinc-500 backdrop-blur-sm dark:bg-[#13161c]/85">
                      {t("auth.oauth.sectionTitle")}
                    </span>
                  </div>
                </div>
                <div className="space-y-2">
                  {oauthProviders.map((p) => (
                    <Button
                      key={p.id}
                      type="button"
                      variant="outline"
                      onClick={() => handleOAuth(p.id, effectiveMode)}
                      disabled={oauthLoadingId !== null}
                      className="h-9 w-full"
                    >
                      {oauthLoadingId === p.id ? (
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      ) : p.avatar_url ? (
                        /* eslint-disable-next-line @next/next/no-img-element */
                        <img
                          src={p.avatar_url}
                          alt=""
                          className="mr-1.5 h-4 w-4 rounded-sm object-cover"
                        />
                      ) : (
                        <Mail className="mr-1.5 h-4 w-4" />
                      )}
                      {effectiveMode === "register"
                        ? t("auth.oauth.registerWith", { provider: p.name })
                        : t("auth.oauth.loginWith", { provider: p.name })}
                    </Button>
                  ))}
                </div>
              </div>
            )}

          {/* Switch-to-single-mode link — shown in first-admin setup when the
              current mode is "multi". Lets the user skip registration and use
              the app in single mode instead (the default-user fallback has
              admin rights). This breaks the circular dependency where multi
              mode + no users = stuck on the auth page. */}
          {firstAdminSetup && useMode === "multi" && (
            <div className="mt-4 text-center">
              <button
                type="button"
                onClick={switchToSingleMode}
                className="text-xs text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200 underline underline-offset-2 transition-colors"
              >
                {t("auth.firstAdminSwitchToSingle")}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-zinc-700 dark:text-zinc-300">{label}</Label>
      {children}
    </div>
  );
}

export default function AuthPage() {
  return (
    <Suspense fallback={null}>
      <AuthPageInner />
    </Suspense>
  );
}
