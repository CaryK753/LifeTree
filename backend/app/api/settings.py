"""Settings API: multi-provider / multi-model LLM configuration.

Storage is ``backend/.llm_config.json`` (managed by ``app.llm.registry``).
The endpoints here are thin HTTP wrappers around registry mutations:

    GET    /settings                       — full config view (masked)
    POST   /settings/providers             — add provider
    PATCH  /settings/providers/{id}        — update provider
    DELETE /settings/providers/{id}        — delete provider (+ its models)
    POST   /settings/models                — add model
    PATCH  /settings/models/{id}           — update model
    DELETE /settings/models/{id}           — delete model
    PUT    /settings/roles                 — set role→model assignments
    PUT    /settings/tavily                — set Tavily API key
    POST   /settings/test/{role}           — smoke-test the model for a role
    POST   /settings/test/provider/{id}    — smoke-test a provider's auth

The legacy single-LLM endpoints (``GET /settings`` / ``POST /settings``) are
kept as thin shims that map to the new schema so old clients don't break.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.tenant import AdminUser, CurrentUser
from app.llm.registry import (
    ALL_ROLES,
    LLMConfig,
    LLMConfigView,
    OAuthProviderView,
    Protocol,
    Role,
    add_model,
    add_oauth_provider,
    add_provider,
    delete_model,
    delete_oauth_provider,
    delete_provider,
    get_disable_registration,
    get_email_verification_enabled,
    get_oauth_provider_by_id,
    get_oauth_providers,
    get_service_address,
    get_use_mode,
    load_config,
    resolve_role,
    save_config,
    set_disable_registration,
    set_email_verification_enabled,
    set_mineru_key,
    set_role_assignment,
    set_service_address,
    set_smtp_config,
    set_tavily_key,
    set_use_mode,
    to_view,
    update_model,
    update_oauth_provider,
    update_provider,
)

log = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# ---------- Schemas ----------

class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Display name, e.g. 'OpenAI' / 'DeepSeek'")
    protocol: Protocol = "openai_compatible"
    base_url: str | None = Field(None, description="OpenAI-compatible base URL")
    api_key: str = Field("", description="API key. Send empty string if setting later.")


class ProviderUpdate(BaseModel):
    name: str | None = None
    protocol: Protocol | None = None
    base_url: str | None = Field(
        None, description="Empty string clears; null leaves unchanged."
    )
    api_key: str | None = Field(
        None, description="Empty string clears; null leaves unchanged."
    )


class ModelCreate(BaseModel):
    provider_id: str
    name: str = Field(..., min_length=1, description="Model id sent to the API, e.g. 'gpt-4o-mini'")
    display_name: str | None = None
    capabilities: list[Role] = Field(default_factory=list)


class ModelUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    capabilities: list[Role] | None = None


class RoleAssignments(BaseModel):
    """Partial update — only the supplied roles are changed."""

    assignments: dict[Role, str | None] = Field(
        ...,
        description="Map of role → model_id. Null clears the role.",
    )


class TavilyUpdate(BaseModel):
    api_key: str = Field("", description="Empty string clears.")


class MineruUpdate(BaseModel):
    api_key: str = Field("", description="Empty string clears.")
    base_url: str | None = Field(
        None,
        description="Optional override. Null leaves unchanged; empty string resets to default.",
    )


class SmtpUpdate(BaseModel):
    """Partial SMTP update — None leaves a field unchanged."""

    host: str | None = Field(None, description="SMTP server host. Empty string clears.")
    port: int | None = Field(None, description="SMTP server port (typically 587 / 465).")
    user: str | None = Field(None, description="SMTP auth username. Empty string clears.")
    password: str | None = Field(
        None,
        description="SMTP auth password. Empty string clears; null leaves unchanged.",
    )
    from_addr: str | None = Field(
        None,
        description="From address. Empty string resets to notify@lifetree.local.",
    )
    sender_name: str | None = Field(
        None,
        description="Sender display name. Empty string resets to 'LifeTree'.",
    )
    use_tls: bool | None = Field(None, description="Whether to use STARTTLS.")
    use_ssl: bool | None = Field(
        None, description="Use SSL (port 465) instead of STARTTLS."
    )


class TestResult(BaseModel):
    ok: bool
    role: Role | None = None
    model: str | None = None
    provider: str | None = None
    error: str | None = None
    available_count: int | None = None


class UseModeUpdate(BaseModel):
    """Switch usage mode (admin only).

    ``single``: self-use, no login required (default-user fallback on).
    ``multi``: multi-user, login required, admin promotes users via env.
    """

    mode: str = Field(..., description='"single" or "multi"')


# ---------- Helpers ----------


def _is_multi_user_mode() -> bool:
    """True when the platform is running in multi-user mode."""
    return get_use_mode() == "multi"


def _restricted_view(cfg: LLMConfig) -> LLMConfigView:
    """Build a restricted view for non-admin users in multi-user mode.

    Hides all admin-configured secrets:
      - All provider ``api_key_configured`` → False, ``api_key_preview`` → ""
      - Tavily / Mineru / SMTP ``*_configured`` → False, ``*_preview`` → ""
      - Provider ``base_url`` retained (so the user knows the endpoint)
      - Models, role_assignments, roles_configured retained (so the user
        knows which model is used for each role)

    The non-admin user can therefore *see* the platform configuration
    shape (which providers/models exist, which roles are assigned) but
    cannot see any of the actual keys configured by the admin.
    """
    view = to_view(cfg)
    for p in view.providers:
        p.api_key_configured = False
        p.api_key_preview = ""
    view.tavily_api_key_configured = False
    view.tavily_api_key_preview = ""
    view.mineru_api_key_configured = False
    view.mineru_api_key_preview = ""
    view.smtp_password_configured = False
    view.smtp_password_preview = ""
    return view


class SecretReveal(BaseModel):
    """Full (unmasked) secret value returned by the reveal endpoints.

    The frontend uses this to populate the API-key input field when the user
    clicks the eye button, so they can see and copy the actual stored key
    instead of just a masked preview.
    """

    value: str | None = None
    configured: bool = False


class SmtpTestRequest(BaseModel):
    """Send a test email using the currently-configured SMTP settings."""

    to_addr: str = Field(..., description="Recipient address for the test email.")


class SmtpTestResult(BaseModel):
    ok: bool
    error: str | None = None


# ---------- Helpers ----------

def _load_and_save(fn) -> LLMConfigView:
    """Load → mutate → save → return the new view. ``fn`` mutates the cfg in place."""
    cfg = load_config()
    fn(cfg)
    save_config(cfg)
    return to_view(cfg)


# ---------- Read ----------

@router.get("", response_model=LLMConfigView)
async def get_settings(user: CurrentUser) -> LLMConfigView:
    """Return the full LLM configuration.

    In multi-user mode, non-admin users get a restricted view with all
    admin-configured API keys / SMTP password / Tavily / Mineru secrets
    hidden (``*_configured`` returns False, ``*_preview`` returns "").
    Admin users always see the full masked view. In single-user mode
    everyone sees the full masked view (there's only one user anyway).
    """
    cfg = load_config()
    if _is_multi_user_mode() and user.role != "admin":
        return _restricted_view(cfg)
    return to_view(cfg)


# ---------- Use mode ----------

@router.put("/use-mode", response_model=UseModeUpdate)
def put_use_mode(user: CurrentUser, payload: UseModeUpdate) -> UseModeUpdate:
    """Switch the platform usage mode.

    ``single``: self-use, no login required (default-user fallback on).
    ``multi``: multi-user, login required, admin promotes users via env.

    Access rules:
      - In **single-user mode**, anyone (including the default-user fallback)
        can switch — there's only one user, so they're effectively the admin.
      - In **multi-user mode**, only admins can switch.

    The change is persisted to DB (``app_config.use_mode``) and takes
    effect immediately — no process restart required. The next unauthenticated
    request will be treated according to the new mode (single → default-user
    fallback; multi → 401).
    """
    if payload.mode not in ("single", "multi"):
        raise HTTPException(400, f"use_mode must be 'single' or 'multi', got {payload.mode!r}")

    current_mode = get_use_mode()
    # Allow anyone to switch modes during bootstrap (no real users exist yet,
    # so there's nothing to protect). This breaks the circular dependency
    # where switching from multi→single requires admin, but becoming admin
    # in multi mode requires registering, which the non-dismissible first-admin
    # dialog blocks.
    from app.api.auth import _should_promote_first_admin
    from app.db.postgres import SessionLocal
    with SessionLocal() as session:
        bootstrap = _should_promote_first_admin(session)
    if current_mode == "multi" and user.role != "admin" and not bootstrap:
        raise HTTPException(
            403,
            "Admin access required to switch usage mode in multi-user mode",
        )

    set_use_mode(payload.mode)
    log.info("use_mode switched from %s to %s by user %s", current_mode, payload.mode, user.id)
    return UseModeUpdate(mode=payload.mode)


# ---------- Providers ----------

@router.post("/providers", response_model=LLMConfigView)
async def create_provider(payload: ProviderCreate, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    return _load_and_save(
        lambda cfg: add_provider(
            cfg,
            name=payload.name,
            protocol=payload.protocol,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
    )


@router.patch("/providers/{provider_id}", response_model=LLMConfigView)
async def patch_provider(provider_id: str, payload: ProviderUpdate, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    def _mut(cfg):
        updated = update_provider(
            cfg,
            provider_id,
            name=payload.name,
            protocol=payload.protocol,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
        if updated is None:
            raise HTTPException(404, f"Provider {provider_id} not found")

    return _load_and_save(_mut)


@router.delete("/providers/{provider_id}", response_model=LLMConfigView)
async def remove_provider(provider_id: str, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    def _mut(cfg):
        n = delete_provider(cfg, provider_id)
        if n == 0 and not any(p.id == provider_id for p in cfg.providers):
            raise HTTPException(404, f"Provider {provider_id} not found")

    return _load_and_save(_mut)


# ---------- Models ----------

@router.post("/models", response_model=LLMConfigView)
async def create_model(payload: ModelCreate, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    def _mut(cfg):
        m = add_model(
            cfg,
            provider_id=payload.provider_id,
            name=payload.name,
            display_name=payload.display_name,
            capabilities=payload.capabilities,
        )
        if m is None:
            raise HTTPException(404, f"Provider {payload.provider_id} not found")

    return _load_and_save(_mut)


@router.patch("/models/{model_id}", response_model=LLMConfigView)
async def patch_model(model_id: str, payload: ModelUpdate, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    def _mut(cfg):
        updated = update_model(
            cfg,
            model_id,
            name=payload.name,
            display_name=payload.display_name,
            capabilities=payload.capabilities,
        )
        if updated is None:
            raise HTTPException(404, f"Model {model_id} not found")

    return _load_and_save(_mut)


@router.delete("/models/{model_id}", response_model=LLMConfigView)
async def remove_model(model_id: str, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    def _mut(cfg):
        if not delete_model(cfg, model_id):
            raise HTTPException(404, f"Model {model_id} not found")

    return _load_and_save(_mut)


# ---------- Role assignments ----------

@router.put("/roles", response_model=LLMConfigView)
async def put_roles(payload: RoleAssignments, user: CurrentUser) -> LLMConfigView:
    """Set which model serves each role. Only the supplied roles are touched."""
    _require_admin_in_multi_user(user)
    def _mut(cfg):
        for role, model_id in payload.assignments.items():
            if role not in ALL_ROLES:
                raise HTTPException(400, f"Unknown role: {role}")
            if not set_role_assignment(cfg, role, model_id):
                raise HTTPException(
                    400,
                    f"Model {model_id} cannot serve role '{role}' "
                    "(does not exist or lacks the capability)",
                )

    return _load_and_save(_mut)


# ---------- Tavily ----------

@router.put("/tavily", response_model=LLMConfigView)
async def put_tavily(payload: TavilyUpdate, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    return _load_and_save(lambda cfg: set_tavily_key(cfg, payload.api_key))


@router.put("/mineru", response_model=LLMConfigView)
async def put_mineru(payload: MineruUpdate, user: CurrentUser) -> LLMConfigView:
    _require_admin_in_multi_user(user)
    return _load_and_save(
        lambda cfg: set_mineru_key(cfg, payload.api_key, payload.base_url)
    )


@router.put("/smtp", response_model=LLMConfigView)
async def put_smtp(payload: SmtpUpdate, user: CurrentUser) -> LLMConfigView:
    """Update SMTP settings for risk-warning email notifications (§4.5).

    All fields are optional — pass null to leave a field unchanged, empty
    string to clear it (for password/host/user/from_addr).
    """
    _require_admin_in_multi_user(user)
    return _load_and_save(
        lambda cfg: set_smtp_config(
            cfg,
            host=payload.host,
            port=payload.port,
            user=payload.user,
            password=payload.password,
            from_addr=payload.from_addr,
            sender_name=payload.sender_name,
            use_tls=payload.use_tls,
            use_ssl=payload.use_ssl,
        )
    )


# ---------- Secret reveal ----------
#
# These endpoints return the FULL (unmasked) secret value so the frontend
# can populate the API-key input field when the user clicks the eye button.
# The masked preview is fine for "is it configured?" status display, but
# users need the actual value to verify, copy, or migrate keys.
#
# In multi-user mode, only admins may call these endpoints — non-admin
# users get 403 (their GET /settings already returns ``*_configured=False``
# so the eye-toggle UI is hidden anyway).

def _require_admin_in_multi_user(user: CurrentUser) -> None:
    """Block non-admin users from secret-reveal endpoints in multi-user mode."""
    if _is_multi_user_mode() and user.role != "admin":
        raise HTTPException(403, "Admin access required to view secrets in multi-user mode")


@router.get("/providers/{provider_id}/key", response_model=SecretReveal)
def get_provider_key(provider_id: str, user: CurrentUser) -> SecretReveal:
    """Return the full API key for a provider (for the eye-toggle in the UI)."""
    _require_admin_in_multi_user(user)
    cfg = load_config()
    for p in cfg.providers:
        if p.id == provider_id:
            return SecretReveal(value=p.api_key or None, configured=bool(p.api_key))
    raise HTTPException(404, f"Provider {provider_id} not found")


@router.get("/tavily/key", response_model=SecretReveal)
def get_tavily_key(user: CurrentUser) -> SecretReveal:
    """Return the full Tavily API key."""
    _require_admin_in_multi_user(user)
    cfg = load_config()
    return SecretReveal(value=cfg.tavily_api_key or None, configured=bool(cfg.tavily_api_key))


@router.get("/mineru/key", response_model=SecretReveal)
def get_mineru_key(user: CurrentUser) -> SecretReveal:
    """Return the full Mineru API key."""
    _require_admin_in_multi_user(user)
    cfg = load_config()
    return SecretReveal(value=cfg.mineru_api_key or None, configured=bool(cfg.mineru_api_key))


@router.get("/smtp/key", response_model=SecretReveal)
def get_smtp_key(user: CurrentUser) -> SecretReveal:
    """Return the full SMTP password."""
    _require_admin_in_multi_user(user)
    cfg = load_config()
    return SecretReveal(value=cfg.smtp_password or None, configured=bool(cfg.smtp_password))


# ---------- SMTP test ----------

@router.post("/smtp/test", response_model=SmtpTestResult)
def test_smtp(payload: SmtpTestRequest, user: CurrentUser) -> SmtpTestResult:
    """Send a test email using the currently-configured SMTP settings.

    This lets the user verify their SMTP config (host/port/user/password/from)
    without waiting for a real risk event to trigger a notification.

    Implementation notes
    --------------------
    * Uses an explicit ``ssl.create_default_context()`` with TLS 1.2+ —
      Resend / Gmail / Outlook 365 all reject handshakes below TLS 1.2,
      which manifests as ``SMTPServerDisconnected: Connection unexpectedly
      closed`` when relying on ``smtplib``'s default context on some
      systems (notably macOS with older Python builds).
    * Each stage (connect / auth / send) is wrapped in its own try/except so
      the user sees *which* step failed instead of a generic error.
    * Resend-specific hint: the From address must use a verified domain —
      the default ``notify@lifetree.local`` is always rejected.
    """
    _require_admin_in_multi_user(user)

    import smtplib
    import ssl
    from email.mime.text import MIMEText
    from email.utils import formataddr

    from app.llm.registry import get_smtp_config

    cfg = load_config()
    smtp = get_smtp_config()
    host = smtp["host"]
    if not host:
        return SmtpTestResult(ok=False, error="SMTP host is not configured")

    port = smtp["port"] or 587
    smtp_user = smtp["user"]
    smtp_password = smtp["password"]
    from_addr = smtp["from"] or "notify@lifetree.local"
    sender_name = smtp.get("sender_name", "LifeTree") or "LifeTree"
    use_tls = smtp["use_tls"] if smtp["use_tls"] is not None else True
    use_ssl = smtp["use_ssl"] if smtp["use_ssl"] is not None else False

    # Build a strict TLS context — required by Resend / Gmail / O365.
    # ``create_default_context`` enables cert verification + hostname check
    # by default; we additionally pin the minimum version to TLS 1.2 so
    # legacy servers can't downgrade the handshake.
    tls_ctx = ssl.create_default_context()
    tls_ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    # Resend-specific hint: From address must be from a verified domain.
    # ``onboarding@resend.dev`` is the only allowed test address for
    # unverified accounts. We surface this proactively because Resend
    # closes the connection on bad senders rather than returning a 550.
    is_resend = "resend" in host.lower()
    from_domain = from_addr.rsplit("@", 1)[-1].lower() if "@" in from_addr else ""
    resend_from_hint = ""
    if is_resend and from_domain in {"lifetree.local", "localhost", ""}:
        resend_from_hint = (
            " — Resend 要求 From 地址来自已验证的域名；"
            "请在 SMTP 配置中将 from_addr 改为 onboarding@resend.dev "
            "（测试用）或你已验证的域名邮箱（如 noreply@yourdomain.com）。"
        )

    body = (
        "This is a test email from LifeTree.\n\n"
        "If you received this message, your SMTP configuration is working correctly.\n\n"
        f"Server: {host}:{port}\n"
        f"From: {from_addr}\n"
        f"TLS: {'on' if use_tls else 'off'}\n"
        f"SSL: {'on' if use_ssl else 'off'}"
    )
    # Build an HTML test email using the shared template so admins see the
    # same look-and-feel as real notifications.
    from app.services.email_template import build_html_message, render_email_html

    test_body_html = f"""
<h1>SMTP 配置测试 · SMTP Test</h1>
<p>这是一封来自 LifeTree 的测试邮件。如果你收到了这封邮件，说明你的 SMTP 配置正确无误。</p>
<p>This is a test email from LifeTree. If you received this message, your SMTP configuration is working correctly.</p>
<div class="alert">测试邮件 · Test email</div>
<p style="font-family:monospace; font-size:12px; background:#f3f4f6; padding:12px; border-radius:6px;">
Server: {host}:{port}<br />
From: {from_addr}<br />
TLS: {'on' if use_tls else 'off'}<br />
SSL: {'on' if use_ssl else 'off'}
</p>"""
    html = render_email_html(
        title="LifeTree SMTP Test",
        preheader="LifeTree SMTP configuration test",
        body_html=test_body_html,
    )
    msg = build_html_message(
        to_addr=payload.to_addr,
        subject="[LifeTree] SMTP Test",
        html_body=html,
        plain_text_fallback=body,
    )
    msg["From"] = formataddr((sender_name, from_addr))
    msg["To"] = payload.to_addr

    def _port_mismatch_hint(stage: str, exc: Exception) -> str:
        """Best-effort hint for ``Connection unexpectedly closed``."""
        s = str(exc).lower()
        if "connection unexpectedly closed" not in s:
            return ""
        hint = ""
        if use_ssl and port in (587, 25, 2587):
            hint = (
                " — 提示：SSL 通常使用端口 465，而非 587/25/2587。"
                "请尝试切换为 TLS(STARTTLS) 或将端口改为 465。"
            )
        elif not use_ssl and port == 465:
            hint = (
                " — 提示：端口 465 通常需要 SSL，而非 STARTTLS。"
                "请尝试启用 SSL 并关闭 TLS。"
            )
        elif not use_tls and not use_ssl:
            hint = " — 提示：大多数 SMTP 服务器需要加密。请尝试启用 TLS 或 SSL。"
        elif is_resend and stage == "connect":
            hint = (
                " — 提示：Resend 在 TLS 握手失败时会直接关闭连接。"
                "请确认端口与 SSL/TLS 选项匹配（465+SSL 或 587+TLS），"
                "并确保本机 Python/OpenSSL 支持 TLS 1.2+。"
            )
        return hint

    # ---------- Connect ----------
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=30, context=tls_ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
    except smtplib.SMTPServerDisconnected as exc:
        return SmtpTestResult(
            ok=False,
            error=f"[connect] {exc}{_port_mismatch_hint('connect', exc)}{resend_from_hint}",
        )
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        return SmtpTestResult(ok=False, error=f"[connect] {exc}{resend_from_hint}")

    # ---------- EHLO / STARTTLS / LOGIN / SEND ----------
    try:
        server.ehlo()
        if not use_ssl and use_tls:
            server.starttls(context=tls_ctx)
            server.ehlo()
        if smtp_user:
            try:
                server.login(smtp_user, smtp_password)
            except smtplib.SMTPAuthenticationError as exc:
                return SmtpTestResult(
                    ok=False,
                    error=(
                        f"[auth] {exc}"
                        + (
                            " — 提示：Resend 的密码字段填 API key（re_ 开头），用户名填 'resend'。"
                            if is_resend
                            else ""
                        )
                    ),
                )
        try:
            server.sendmail(from_addr, [payload.to_addr], msg.as_string())
        except smtplib.SMTPRecipientsRefused as exc:
            return SmtpTestResult(
                ok=False,
                error=(
                    f"[send] 收件人被拒绝: {exc}"
                    + (
                        " — 提示：Resend 测试收件人也必须在已验证域名下，或使用 onboarding@resend.dev。"
                        if is_resend
                        else ""
                    )
                ),
            )
        except smtplib.SMTPSenderRefused as exc:
            return SmtpTestResult(
                ok=False,
                error=(
                    f"[send] 发件人被拒绝: {exc}"
                    + (
                        " — 提示：Resend 要求 From 地址来自已验证域名；"
                        "onboarding@resend.dev 可用于未验证账户的测试。"
                        if is_resend
                        else ""
                    )
                ),
            )
    except smtplib.SMTPServerDisconnected as exc:
        return SmtpTestResult(
            ok=False,
            error=f"[send] {exc}{_port_mismatch_hint('send', exc)}{resend_from_hint}",
        )
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        return SmtpTestResult(ok=False, error=f"[send] {exc}{resend_from_hint}")
    finally:
        try:
            server.quit()
        except Exception:
            pass

    return SmtpTestResult(ok=True)


# ---------- OAuth providers (admin-only) ----------
#
# Multi-user mode: admins configure generic OAuth2 providers (GitHub, Google,
# GitLab, …) so users can sign in without a password. All endpoints here
# require the ``admin`` role via the ``AdminUser`` dependency.

class OAuthProviderCreate(BaseModel):
    """Payload for POST /settings/oauth — add a new OAuth provider."""

    name: str = Field(..., min_length=1, max_length=128)
    client_id: str = Field("", description="OAuth client_id. Empty string = set later.")
    client_secret: str = Field("", description="OAuth client_secret. Empty string = set later.")
    authorize_url: str = Field("", description="Authorization endpoint URL.")
    token_url: str = Field("", description="Token exchange endpoint URL.")
    userinfo_url: str = Field("", description="User info endpoint URL.")
    scopes: list[str] = Field(default_factory=list, description="OAuth scopes to request.")
    redirect_uri: str = Field("", description="Callback URL configured at the provider.")
    enabled: bool = True
    avatar_url: str = Field("", description="Provider icon — data URL or external URL.")


class OAuthProviderUpdate(BaseModel):
    """Payload for PATCH /settings/oauth/{id}. All fields optional."""

    name: str | None = None
    client_id: str | None = Field(None, description="Empty string clears; null unchanged.")
    client_secret: str | None = Field(
        None, description="Empty string clears; null unchanged."
    )
    authorize_url: str | None = None
    token_url: str | None = None
    userinfo_url: str | None = None
    scopes: list[str] | None = None
    redirect_uri: str | None = None
    enabled: bool | None = None
    avatar_url: str | None = Field(
        None, description="Empty string clears; null unchanged. Data URL or external URL."
    )


class EmailVerificationUpdate(BaseModel):
    """Payload for PUT /settings/email-verification."""

    enabled: bool


class DisableRegistrationUpdate(BaseModel):
    """Payload for PUT /settings/disable-registration."""

    enabled: bool


class ServiceAddressUpdate(BaseModel):
    """Payload for PUT /settings/service-address."""

    address: str = Field("", description="Public URL of this LifeTree instance, e.g. https://lifetree.example.com")


@router.get("/oauth", response_model=list[OAuthProviderView])
def list_oauth_providers(admin: AdminUser) -> list[OAuthProviderView]:
    """List all configured OAuth providers (masked — no client_secret)."""
    return [_oauth_provider_to_view_public(p) for p in get_oauth_providers()]


@router.post("/oauth", response_model=OAuthProviderView, status_code=201)
def create_oauth_provider(
    admin: AdminUser, payload: OAuthProviderCreate
) -> OAuthProviderView:
    """Add a new OAuth provider."""
    p = add_oauth_provider(
        name=payload.name,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        authorize_url=payload.authorize_url,
        token_url=payload.token_url,
        userinfo_url=payload.userinfo_url,
        scopes=payload.scopes,
        redirect_uri=payload.redirect_uri,
        enabled=payload.enabled,
        avatar_url=payload.avatar_url,
    )
    return _oauth_provider_to_view_public(p)


@router.patch("/oauth/{provider_id}", response_model=OAuthProviderView)
def patch_oauth_provider(
    admin: AdminUser, provider_id: str, payload: OAuthProviderUpdate
) -> OAuthProviderView:
    """Update an OAuth provider. Returns 404 if not found."""
    p = update_oauth_provider(
        provider_id,
        name=payload.name,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        authorize_url=payload.authorize_url,
        token_url=payload.token_url,
        userinfo_url=payload.userinfo_url,
        scopes=payload.scopes,
        redirect_uri=payload.redirect_uri,
        enabled=payload.enabled,
        avatar_url=payload.avatar_url,
    )
    if p is None:
        raise HTTPException(404, f"OAuth provider {provider_id} not found")
    return _oauth_provider_to_view_public(p)


def _oauth_provider_to_view_public(p) -> OAuthProviderView:
    """Build a masked OAuthProviderView from an OAuthProvider model."""
    return OAuthProviderView(
        id=p.id,
        name=p.name,
        client_id=p.client_id,
        client_id_configured=bool(p.client_id),
        client_secret_configured=bool(p.client_secret),
        authorize_url=p.authorize_url,
        token_url=p.token_url,
        userinfo_url=p.userinfo_url,
        scopes=list(p.scopes),
        redirect_uri=p.redirect_uri,
        enabled=p.enabled,
        avatar_url=p.avatar_url,
        created_at=p.created_at,
    )


@router.delete("/oauth/{provider_id}")
def remove_oauth_provider(admin: AdminUser, provider_id: str) -> dict:
    """Delete an OAuth provider. Returns 404 if not found."""
    if not delete_oauth_provider(provider_id):
        raise HTTPException(404, f"OAuth provider {provider_id} not found")
    return {"ok": True}


@router.get("/oauth/{provider_id}/secret", response_model=SecretReveal)
def get_oauth_provider_secret(admin: AdminUser, provider_id: str) -> SecretReveal:
    """Return the full client_secret for an OAuth provider (eye-toggle in UI)."""
    p = get_oauth_provider_by_id(provider_id)
    if p is None:
        raise HTTPException(404, f"OAuth provider {provider_id} not found")
    return SecretReveal(value=p.client_secret or None, configured=bool(p.client_secret))


# ---------- Email verification toggle (admin-only) ----------

@router.get("/email-verification", response_model=EmailVerificationUpdate)
def get_email_verification_setting(admin: AdminUser) -> EmailVerificationUpdate:
    """Return whether email verification is required for registration."""
    return EmailVerificationUpdate(enabled=get_email_verification_enabled())


@router.put("/email-verification", response_model=EmailVerificationUpdate)
def put_email_verification_setting(
    admin: AdminUser, payload: EmailVerificationUpdate
) -> EmailVerificationUpdate:
    """Enable or disable email verification for registration."""
    set_email_verification_enabled(payload.enabled)
    return EmailVerificationUpdate(enabled=payload.enabled)


# ---------- Disable registration toggle (admin-only) ----------

@router.get("/disable-registration", response_model=DisableRegistrationUpdate)
def get_disable_registration_setting(admin: AdminUser) -> DisableRegistrationUpdate:
    """Return whether new-user registration is disabled."""
    return DisableRegistrationUpdate(enabled=get_disable_registration())


@router.put("/disable-registration", response_model=DisableRegistrationUpdate)
def put_disable_registration_setting(
    admin: AdminUser, payload: DisableRegistrationUpdate
) -> DisableRegistrationUpdate:
    """Disable or re-enable new-user registration."""
    set_disable_registration(payload.enabled)
    return DisableRegistrationUpdate(enabled=payload.enabled)


# ---------- Service address (admin-only) ----------

@router.get("/service-address", response_model=ServiceAddressUpdate)
def get_service_address_setting(admin: AdminUser) -> ServiceAddressUpdate:
    """Return the configured public service address."""
    return ServiceAddressUpdate(address=get_service_address())


@router.put("/service-address", response_model=ServiceAddressUpdate)
def put_service_address_setting(
    admin: AdminUser, payload: ServiceAddressUpdate
) -> ServiceAddressUpdate:
    """Set the public service address used in emails and notifications."""
    set_service_address(payload.address)
    return ServiceAddressUpdate(address=payload.address)


# ---------- Smoke tests ----------

@router.post("/test/{role}", response_model=TestResult)
async def test_role(role: Role, user: CurrentUser) -> TestResult:
    """Smoke-test the model configured for ``role``.

    Protected: the probe calls the upstream provider with the stored API
    key, which would leak connectivity / quota status to non-admins in
    multi-user mode.
    """
    _require_admin_in_multi_user(user)

    # For chat / vision / embedding we call ``models.list`` on the OpenAI-compat
    # endpoint. For rerank we issue a 1-document rerank call.
    resolved = resolve_role(role)
    if resolved is None:
        return TestResult(ok=False, role=role, error=f"No model configured for role '{role}'")

    if role == "rerank":
        return await _test_rerank(resolved)

    return await _test_openai_compat(resolved, role)


async def _test_openai_compat(resolved, role: Role) -> TestResult:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=resolved.provider.api_key or "missing",
            base_url=resolved.provider.base_url or None,
        )
        models = client.models.list()
        return TestResult(
            ok=True,
            role=role,
            model=resolved.model.name,
            provider=resolved.provider.name,
            available_count=len(models.data),
        )
    except Exception as exc:  # noqa: BLE001
        return TestResult(
            ok=False,
            role=role,
            model=resolved.model.name,
            provider=resolved.provider.name,
            error=str(exc),
        )


async def _test_rerank(resolved) -> TestResult:
    try:
        from app.llm.rerank import rerank, RerankError

        # Tiny rerank probe — 2 short docs.
        results = rerank(
            "hello world",
            ["hello", "world"],
            top_n=2,
        )
        return TestResult(
            ok=True,
            role="rerank",
            model=resolved.model.name,
            provider=resolved.provider.name,
            available_count=len(results),
        )
    except RerankError as exc:
        return TestResult(
            ok=False,
            role="rerank",
            model=resolved.model.name,
            provider=resolved.provider.name,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return TestResult(
            ok=False,
            role="rerank",
            model=resolved.model.name,
            provider=resolved.provider.name,
            error=str(exc),
        )


# ---------- Legacy compat ----------
#
# The old single-LLM ``POST /settings`` accepted flat fields like
# ``llm_base_url`` / ``llm_api_key``. We keep a thin handler that maps the
# old payload onto the new provider/model API so older frontends don't break.
# New clients should use the structured endpoints above.

class LegacyLLMSettingsUpdate(BaseModel):
    llm_provider: Protocol | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_embedding_model: str | None = None
    tavily_api_key: str | None = None


@router.post("", response_model=LLMConfigView, include_in_schema=False)
async def legacy_update_settings(payload: LegacyLLMSettingsUpdate) -> LLMConfigView:
    """Legacy flat-payload handler. Rewrites to the new schema in place."""
    cfg = load_config()

    # Find or create a single "legacy" provider.
    provider = next((p for p in cfg.providers if p.id == "legacy"), None)
    if payload.llm_base_url is not None or payload.llm_api_key is not None:
        if provider is None:
            provider = add_provider(
                cfg,
                name="默认供应商",
                protocol=payload.llm_provider or "openai_compatible",
                base_url=payload.llm_base_url,
                api_key=payload.llm_api_key or "",
            )
            provider.id = "legacy"
        else:
            update_provider(
                cfg,
                "legacy",
                protocol=payload.llm_provider,
                base_url=payload.llm_base_url,
                api_key=payload.llm_api_key,
            )

    if payload.llm_model is not None and provider is not None:
        m = next(
            (x for x in cfg.models if x.provider_id == provider.id and "chat" in x.capabilities),
            None,
        )
        if m is None:
            m = add_model(
                cfg,
                provider_id=provider.id,
                name=payload.llm_model,
                display_name=payload.llm_model,
                capabilities=["chat"],
            )
        else:
            update_model(cfg, m.id, name=payload.llm_model, display_name=payload.llm_model)
        set_role_assignment(cfg, "chat", m.id)

    if payload.llm_embedding_model is not None and provider is not None:
        m = next(
            (x for x in cfg.models if x.provider_id == provider.id and "embedding" in x.capabilities),
            None,
        )
        if m is None:
            m = add_model(
                cfg,
                provider_id=provider.id,
                name=payload.llm_embedding_model,
                display_name=payload.llm_embedding_model,
                capabilities=["embedding"],
            )
        else:
            update_model(cfg, m.id, name=payload.llm_embedding_model, display_name=payload.llm_embedding_model)
        set_role_assignment(cfg, "embedding", m.id)

    if payload.tavily_api_key is not None:
        set_tavily_key(cfg, payload.tavily_api_key)

    save_config(cfg)
    return to_view(cfg)
