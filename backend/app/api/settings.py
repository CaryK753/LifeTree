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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.llm.registry import (
    ALL_ROLES,
    LLMConfigView,
    Protocol,
    Role,
    add_model,
    add_provider,
    delete_model,
    delete_provider,
    load_config,
    resolve_role,
    save_config,
    set_mineru_key,
    set_role_assignment,
    set_smtp_config,
    set_tavily_key,
    to_view,
    update_model,
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
async def get_settings() -> LLMConfigView:
    """Return the full LLM configuration with masked secrets."""
    return to_view(load_config())


# ---------- Providers ----------

@router.post("/providers", response_model=LLMConfigView)
async def create_provider(payload: ProviderCreate) -> LLMConfigView:
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
async def patch_provider(provider_id: str, payload: ProviderUpdate) -> LLMConfigView:
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
async def remove_provider(provider_id: str) -> LLMConfigView:
    def _mut(cfg):
        n = delete_provider(cfg, provider_id)
        if n == 0 and not any(p.id == provider_id for p in cfg.providers):
            raise HTTPException(404, f"Provider {provider_id} not found")

    return _load_and_save(_mut)


# ---------- Models ----------

@router.post("/models", response_model=LLMConfigView)
async def create_model(payload: ModelCreate) -> LLMConfigView:
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
async def patch_model(model_id: str, payload: ModelUpdate) -> LLMConfigView:
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
async def remove_model(model_id: str) -> LLMConfigView:
    def _mut(cfg):
        if not delete_model(cfg, model_id):
            raise HTTPException(404, f"Model {model_id} not found")

    return _load_and_save(_mut)


# ---------- Role assignments ----------

@router.put("/roles", response_model=LLMConfigView)
async def put_roles(payload: RoleAssignments) -> LLMConfigView:
    """Set which model serves each role. Only the supplied roles are touched."""
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
async def put_tavily(payload: TavilyUpdate) -> LLMConfigView:
    return _load_and_save(lambda cfg: set_tavily_key(cfg, payload.api_key))


@router.put("/mineru", response_model=LLMConfigView)
async def put_mineru(payload: MineruUpdate) -> LLMConfigView:
    return _load_and_save(
        lambda cfg: set_mineru_key(cfg, payload.api_key, payload.base_url)
    )


@router.put("/smtp", response_model=LLMConfigView)
async def put_smtp(payload: SmtpUpdate) -> LLMConfigView:
    """Update SMTP settings for risk-warning email notifications (§4.5).

    All fields are optional — pass null to leave a field unchanged, empty
    string to clear it (for password/host/user/from_addr).
    """
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

@router.get("/providers/{provider_id}/key", response_model=SecretReveal)
def get_provider_key(provider_id: str) -> SecretReveal:
    """Return the full API key for a provider (for the eye-toggle in the UI)."""
    cfg = load_config()
    for p in cfg.providers:
        if p.id == provider_id:
            return SecretReveal(value=p.api_key or None, configured=bool(p.api_key))
    raise HTTPException(404, f"Provider {provider_id} not found")


@router.get("/tavily/key", response_model=SecretReveal)
def get_tavily_key() -> SecretReveal:
    """Return the full Tavily API key."""
    cfg = load_config()
    return SecretReveal(value=cfg.tavily_api_key or None, configured=bool(cfg.tavily_api_key))


@router.get("/mineru/key", response_model=SecretReveal)
def get_mineru_key() -> SecretReveal:
    """Return the full Mineru API key."""
    cfg = load_config()
    return SecretReveal(value=cfg.mineru_api_key or None, configured=bool(cfg.mineru_api_key))


@router.get("/smtp/key", response_model=SecretReveal)
def get_smtp_key() -> SecretReveal:
    """Return the full SMTP password."""
    cfg = load_config()
    return SecretReveal(value=cfg.smtp_password or None, configured=bool(cfg.smtp_password))


# ---------- SMTP test ----------

@router.post("/smtp/test", response_model=SmtpTestResult)
def test_smtp(payload: SmtpTestRequest) -> SmtpTestResult:
    """Send a test email using the currently-configured SMTP settings.

    This lets the user verify their SMTP config (host/port/user/password/from)
    without waiting for a real risk event to trigger a notification.
    """
    import smtplib
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

    body = (
        "This is a test email from LifeTree.\n\n"
        "If you received this message, your SMTP configuration is working correctly.\n\n"
        f"Server: {host}:{port}\n"
        f"From: {from_addr}\n"
        f"TLS: {'on' if use_tls else 'off'}\n"
        f"SSL: {'on' if use_ssl else 'off'}"
    )
    msg = MIMEText(body)
    msg["Subject"] = "[LifeTree] SMTP Test"
    msg["From"] = formataddr((sender_name, from_addr))
    msg["To"] = payload.to_addr

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, [payload.to_addr], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, [payload.to_addr], msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        return SmtpTestResult(ok=False, error=str(exc))
    return SmtpTestResult(ok=True)


# ---------- Smoke tests ----------

@router.post("/test/{role}", response_model=TestResult)
async def test_role(role: Role) -> TestResult:
    """Smoke-test the model configured for ``role``.

    For chat / vision / embedding we call ``models.list`` on the OpenAI-compat
    endpoint. For rerank we issue a 1-document rerank call.
    """
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
