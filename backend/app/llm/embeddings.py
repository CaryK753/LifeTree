"""Text embedding helpers using the OpenAI-compatible embeddings endpoint.

Resolves the model configured for the ``embedding`` role from
``app.llm.registry``. Falls back to empty vectors if the role is unset or
the endpoint fails — callers should handle ``[]`` embeddings downstream.
"""

from __future__ import annotations

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.llm.client import get_embedding_sync_client

log = get_logger(__name__)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
)
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts; returns one vector per input.

    Uses the model configured for the ``embedding`` role. Returns
    empty-list placeholders if the role is unset or the endpoint fails so
    callers can still proceed.
    """
    if not texts:
        return []

    try:
        client, model_name = get_embedding_sync_client()
    except LLMNotConfiguredError:
        log.warning("llm.embed_role_not_configured")
        return [[] for _ in texts]

    # Trim very long inputs to keep token cost predictable
    trimmed = [t[:8000] for t in texts]

    try:
        # Default to 1024 dimensions — supported by both OpenAI
        # text-embedding-3-* and Alibaba Cloud text-embedding-v3, which are
        # the models currently configured for this role. Can be overridden
        # via model metadata in the future if a different dim is needed.
        resp = client.embeddings.create(
            model=model_name, input=trimmed, dimensions=1024
        )
        return [d.embedding for d in resp.data]
    except Exception as exc:  # noqa: BLE001
        log.warning("llm.embed_failed", error=str(exc), n=len(trimmed))
        # Return zero-length placeholders so callers can still proceed
        return [[] for _ in trimmed]
