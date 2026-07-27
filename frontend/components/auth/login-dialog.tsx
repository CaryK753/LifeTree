"use client";

import { useEffect, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, LogIn, Mail, ShieldCheck, UserPlus, KeyRound } from "lucide-react";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { useAuth, useAuthConfig } from "@/lib/hooks";
import { api, setTokens } from "@/lib/api";
import { cn } from "@/lib/utils";

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

/**
 * Encode an ArrayBuffer into a base64url string (no padding).
 * Used to convert PublicKeyCredential.rawId → the id field the backend expects.
 */
function uint8ArrayToBase64url(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  const b64 = btoa(bin);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Browser support check — WebAuthn is available in all modern browsers
 * but not in older ones or non-secure contexts (HTTP other than localhost).
 */
function isPasskeySupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    typeof PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.credentials !== "undefined"
  );
}

/**
 * Login dialog with two tabs: login + register.
 *
 * Shown as a modal (no separate page) when the user is unauthenticated.
 * In multi-user mode, also renders:
 *   - OAuth provider buttons (when at least one provider is configured)
 *   - Email verification code field on the register tab (when enabled by admin)
 *
 * ``dismissible`` controls whether the user can close the dialog without
 * logging in. In multi-user mode (no default-user fallback) the dialog is
 * not dismissible — the user must authenticate to use the app. In
 * single-user mode the dialog is dismissible so guest mode keeps working.
 *
 * On success, the parent component decides what to render next.
 */
export function LoginDialog({
  open,
  onOpenChange,
  dismissible = true,
  firstAdminSetup = false,
  useMode,
  onSwitchToSingle,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dismissible?: boolean;
  firstAdminSetup?: boolean;
  useMode?: string;
  onSwitchToSingle?: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const { login, register, registerWithCode } = useAuth();
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

  // In first-admin setup mode, force the register tab and hide the tabs.
  const effectiveMode = firstAdminSetup ? "register" : mode;

  // Email-verification-code "send" button state.
  const [codeSending, setCodeSending] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0); // seconds remaining
  const cooldownTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const emailVerificationEnabled = !!authConfig?.email_verification_enabled;
  const disableRegistration = !!authConfig?.disable_registration && !firstAdminSetup;
  const oauthProviders = authConfig?.oauth_providers ?? [];

  // Reset form when dialog closes.
  useEffect(() => {
    if (!open) {
      setForm({ displayName: "", email: "", password: "", code: "" });
      setMode("login");
      setLoading(false);
      setOauthLoadingId(null);
      setPasskeyLoading(false);
      setCodeSending(false);
      setCodeCooldown(0);
      if (cooldownTimer.current) {
        clearInterval(cooldownTimer.current);
        cooldownTimer.current = null;
      }
    }
  }, [open]);

  // When firstAdminSetup is active, ensure we're always in register mode.
  // When registration is disabled, force login mode.
  useEffect(() => {
    if (firstAdminSetup) setMode("register");
    else if (disableRegistration) setMode("login");
  }, [firstAdminSetup, disableRegistration]);

  // Clean up cooldown timer on unmount.
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
        // Start 60s cooldown.
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
        // Register: choose flow based on email-verification flag.
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
            // Password is optional when verification is enabled — but
            // if the user typed one, send it so they can also log in
            // via /auth/login later.
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
      onOpenChange(false);
      // Force a full page reload so all SWR caches (profile, goals,
      // memories, sources, …) refetch with the new auth token. Without
      // this, stale unauthenticated data would linger until each cache
      // is individually revalidated.
      window.location.reload();
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

  async function handleOAuth(providerId: string, oauthMode: "login" | "register" = "login") {
    setOauthLoadingId(providerId);
    try {
      const { authorize_url } = await api.oauthStart(providerId, oauthMode);
      // Mark the register flow via sessionStorage so /auth/callback can
      // show the right success message and pick the right redirect target.
      if (oauthMode === "register") {
        try {
          sessionStorage.setItem("lifetree.oauth.register", providerId);
        } catch {
          // sessionStorage may be unavailable — non-fatal.
        }
      }
      // Full-page redirect to the provider's authorize URL.
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

  /**
   * Passkey (WebAuthn) login — passwordless authentication using a
   * device-bound credential. The flow is:
   *   1. POST /auth/passkey/auth/options → get challenge + allowCredentials
   *   2. navigator.credentials.get() → prompt user to touch authenticator
   *   3. POST /auth/passkey/auth/verify → backend verifies signature,
   *      returns JWT access/refresh tokens
   *
   * Only available on the login tab (not register) when the admin has
   * enabled passkey login. Requires HTTPS or localhost.
   */
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
      // 1. Fetch authentication options from the backend.
      const { options } = await api.passkeyAuthOptions();

      // 2. Convert the JSON-serializable options back into the format
      //    navigator.credentials.get() expects (ArrayBuffer for challenge
      //    and allowCredentials[].id).
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

      // 3. Prompt the user to unlock their authenticator.
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

      // 4. Serialize the credential into the JSON format the backend
      //    expects. The rawId and response fields are ArrayBuffers —
      //    they need to be base64url-encoded.
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

      // 5. Send to backend for verification → receive JWT tokens.
      const res = await api.passkeyAuthVerify(serializedCredential);
      setTokens(res.access_token, res.refresh_token);
      toast({ title: t("auth.loginSuccess"), variant: "success" });
      onOpenChange(false);
      // Force a full page reload so all SWR caches refetch with the
      // new auth token (same pattern as email/password login above).
      window.location.reload();
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

  // Whether the password field is required on the register tab.
  // When email verification is enabled, password is optional.
  const passwordRequired = effectiveMode === "login" || !emailVerificationEnabled;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // When not dismissible, ignore any attempt to close the dialog
        // except via successful auth (which calls onOpenChange(false)
        // directly from submit()).
        if (!dismissible && !next) return;
        onOpenChange(next);
      }}
    >
      <DialogContent
        className="max-w-md"
        hideClose={!dismissible}
        onEscapeKeyDown={(e) => {
          if (!dismissible) e.preventDefault();
        }}
        onPointerDownOutside={(e) => {
          if (!dismissible) e.preventDefault();
        }}
        onInteractOutside={(e) => {
          if (!dismissible) e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
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
          </DialogTitle>
          <DialogDescription>
            {firstAdminSetup
              ? t("auth.firstAdminDesc")
              : effectiveMode === "login"
                ? t("auth.loginDesc")
                : t("auth.registerDesc")}
          </DialogDescription>
        </DialogHeader>

        {/* Tabs — hidden in first-admin setup mode (register only) and
            when registration is disabled by admin (login only). */}
        {!firstAdminSetup && !disableRegistration && (
        <div className="flex gap-1 p-1 rounded-md bg-black/[0.04] dark:bg-white/[0.04]">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={cn(
              "flex-1 px-3 py-1.5 text-sm font-medium rounded transition-colors",
              mode === "login"
                ? "bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-sm"
                : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
            )}
          >
            {t("auth.tabLogin")}
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            className={cn(
              "flex-1 px-3 py-1.5 text-sm font-medium rounded transition-colors",
              mode === "register"
                ? "bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-sm"
                : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
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
              <p className="text-[10px] text-zinc-500 leading-snug">
                {t("auth.passwordOptionalHint")}
              </p>
            )}
          </Field>

          {/* Email verification code field — only on register tab when admin enabled it. */}
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
                    setForm({ ...form, code: e.target.value.replace(/\D/g, "") })
                  }
                  placeholder={t("auth.verifyCode.placeholder")}
                  className="h-9 text-sm flex-1"
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
                  className="h-9 px-3 shrink-0"
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

          <Button
            type="submit"
            disabled={loading}
            className="w-full h-9"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
            ) : firstAdminSetup ? (
              <ShieldCheck className="h-4 w-4 mr-1.5" />
            ) : effectiveMode === "login" ? (
              <LogIn className="h-4 w-4 mr-1.5" />
            ) : (
              <UserPlus className="h-4 w-4 mr-1.5" />
            )}
            {firstAdminSetup
              ? t("auth.firstAdminButton")
              : effectiveMode === "login"
                ? t("auth.login")
                : emailVerificationEnabled
                  ? t("auth.verifyCode.register")
                  : t("auth.register")}
          </Button>

          {/* Passkey login button — only on the login tab (not register)
              when the admin has enabled it and the browser supports
              WebAuthn. Uses type="button" so it doesn't submit the form. */}
          {!firstAdminSetup &&
            effectiveMode === "login" &&
            authConfig?.passkey_login_enabled &&
            isPasskeySupported() && (
              <Button
                type="button"
                variant="outline"
                onClick={handlePasskeyLogin}
                disabled={passkeyLoading || loading || oauthLoadingId !== null}
                className="w-full h-9"
              >
                {passkeyLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                ) : (
                  <KeyRound className="h-4 w-4 mr-1.5" />
                )}
                {passkeyLoading
                  ? t("auth.passkeyDiscovering")
                  : t("auth.passkeyLogin")}
              </Button>
            )}
        </form>

        {/* Switch-to-single-mode link — shown in first-admin setup when the
            current mode is "multi". Lets the user skip registration and use
            the app in single mode instead (the default-user fallback has
            admin rights). This breaks the circular dependency where multi
            mode + no users = stuck on a non-dismissible dialog. */}
        {firstAdminSetup && useMode === "multi" && onSwitchToSingle && (
          <div className="text-center">
            <button
              type="button"
              onClick={onSwitchToSingle}
              className="text-xs text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200 underline underline-offset-2 transition-colors"
            >
              {t("auth.firstAdminSwitchToSingle")}
            </button>
          </div>
        )}

        {/* OAuth section — only render when at least one provider is configured
            and registration is not disabled (register tab) or always (login tab). */}
        {oauthProviders.length > 0 &&
          !(effectiveMode === "register" && disableRegistration) && (
          <div className="space-y-2">
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-zinc-200 dark:border-zinc-800" />
              </div>
              <div className="relative flex justify-center">
                <span className="bg-white dark:bg-zinc-950 px-2 text-[11px] text-zinc-500">
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
                  className="w-full h-9"
                >
                  {oauthLoadingId === p.id ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                  ) : p.avatar_url ? (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={p.avatar_url}
                      alt=""
                      className="h-4 w-4 mr-1.5 rounded-sm object-cover"
                    />
                  ) : (
                    <Mail className="h-4 w-4 mr-1.5" />
                  )}
                  {effectiveMode === "register"
                    ? t("auth.oauth.registerWith", { provider: p.name })
                    : t("auth.oauth.loginWith", { provider: p.name })}
                </Button>
              ))}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
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
