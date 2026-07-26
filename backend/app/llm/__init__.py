"""LLM client wrappers (role-driven, multi-provider)."""

from app.llm.client import (
    get_async_openai_client,
    get_chat_async_client,
    get_chat_model,
    get_chat_sync_client,
    get_embedding_model,
    get_embedding_sync_client,
    get_instructor_async,
    get_instructor_sync,
    get_sync_openai_client,
    get_vision_model,
)
from app.llm.embeddings import embed_texts
from app.llm.rerank import RerankError, rerank
from app.llm.registry import (
    ALL_ROLES,
    LLMConfig,
    LLMConfigView,
    Model,
    Provider,
    Role,
    load_config,
    resolve_role,
    save_config,
)

__all__ = [
    "ALL_ROLES",
    "LLMConfig",
    "LLMConfigView",
    "Model",
    "Provider",
    "RerankError",
    "Role",
    "embed_texts",
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
    "load_config",
    "rerank",
    "resolve_role",
    "save_config",
]
