"""LLM client construction — role-driven, multi-provider.

We expose two flavours:
  * Raw OpenAI clients (sync + async) for chat / vision / embeddings.
  * Instructor-wrapped clients for Pydantic-validated structured output.

Each call resolves the model+provider configured for a *role* (chat / vision /
embedding) from ``app.llm.registry``. If no model is configured for the role,
``LLMNotConfiguredError`` is raised.

For backward compatibility, ``get_sync_openai_client`` / ``get_async_openai_client``
remain — they resolve the ``chat`` role. Existing callers don't need to change
unless they want to opt into the role-based API.
"""

from __future__ import annotations

import instructor
from openai import AsyncOpenAI, OpenAI

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.llm.registry import ResolvedModel, Role, resolve_role

log = get_logger(__name__)


def _resolve_or_raise(role: Role) -> ResolvedModel:
    resolved = resolve_role(role)
    if resolved is None:
        raise LLMNotConfiguredError(
            f"No model configured for role '{role}'. "
            "Add a provider + model in Settings and assign it to this role.",
            details={"role": role},
        )
    return resolved


def _build_sync_openai(resolved: ResolvedModel) -> OpenAI:
    """Build a sync OpenAI client for the given resolved provider+model."""
    return OpenAI(
        api_key=resolved.provider.api_key or "missing",
        base_url=resolved.provider.base_url or None,
    )


def _build_async_openai(resolved: ResolvedModel) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=resolved.provider.api_key or "missing",
        base_url=resolved.provider.base_url or None,
    )


# ---------- Role-driven factories ----------
#
# We intentionally do NOT lru_cache these. The registry file can change at any
# time (the user updates settings via the UI), and a cached client would keep
# the old API key / base_url. Callers should construct a client per request
# (cheap — it's just an httpx wrapper) or accept that a settings update will
# require a process restart for long-lived workers.
#
# For request-scoped code (advisor graph, structuring), construct once per
# request and reuse within that request.


def get_chat_model() -> ResolvedModel:
    """Return the resolved model+provider for the ``chat`` role."""
    return _resolve_or_raise("chat")


def get_vision_model() -> ResolvedModel:
    return _resolve_or_raise("vision")


def get_embedding_model() -> ResolvedModel:
    return _resolve_or_raise("embedding")


def get_chat_sync_client() -> tuple[OpenAI, str]:
    """Return ``(client, model_name)`` for the configured chat model."""
    resolved = get_chat_model()
    return _build_sync_openai(resolved), resolved.model.name


def get_chat_async_client() -> tuple[AsyncOpenAI, str]:
    resolved = get_chat_model()
    return _build_async_openai(resolved), resolved.model.name


def get_embedding_sync_client() -> tuple[OpenAI, str]:
    resolved = get_embedding_model()
    return _build_sync_openai(resolved), resolved.model.name


def get_instructor_sync() -> instructor.Instructor:
    """Instructor-wrapped sync client for structured output (chat role)."""
    resolved = get_chat_model()
    client = _build_sync_openai(resolved)
    return instructor.from_openai(client)


def get_instructor_async() -> instructor.AsyncInstructor:
    """Instructor-wrapped async client for structured output (chat role)."""
    resolved = get_chat_model()
    client = _build_async_openai(resolved)
    return instructor.from_openai(client)


# ---------- Backward-compat shims ----------
#
# Old callers (and the existing settings API smoke test) used these. They now
# resolve the ``chat`` role and return a plain ``OpenAI`` client (no model
# name). Prefer the role-driven factories above for new code.


def get_sync_openai_client() -> OpenAI:
    client, _ = get_chat_sync_client()
    return client


def get_async_openai_client() -> AsyncOpenAI:
    client, _ = get_chat_async_client()
    return client


def close_llm_clients() -> None:
    """No-op — clients are not cached anymore.

    Kept so old shutdown hooks don't break.
    """
    return None


__all__ = [
    "close_llm_clients",
    "get_async_openai_client",
    "get_chat_async_client",
    "get_chat_model",
    "get_chat_sync_client",
    "get_embedding_model",
    "get_embedding_sync_client",
    "get_instructor_async",
    "get_instructor_sync",
    "get_sync_openai_client",
    "get_vision_model",
]
