"""Rerank clients for second-stage retrieval.

Supports Alibaba Cloud Bailian (DashScope) rerank models:

  - **qwen3-rerank** uses *flat* request params (``model``, ``query``,
    ``documents``, ``top_n``, ``instruct`` at top level).
  - **gte-rerank-v2** and **qwen3-vl-rerank** use *nested* params
    (``{model, input:{query, documents}, parameters:{top_n, return_documents}}``).

Endpoint routing depends on BOTH the model AND the host derived from the
provider ``base_url``:

  - **MaaS API host** (``*.maas.aliyuncs.com``, with workspace ID):
      - qwen3-rerank → ``/compatible-api/v1/reranks`` (compatible, flat params)
      - gte-rerank-v2 / qwen3-vl-rerank → ``/api/v1/services/rerank/text-rerank/text-rerank`` (native, nested params)
  - **DashScope host** (``dashscope.aliyuncs.com``, no workspace ID):
      - All models → ``/api/v1/services/rerank/text-rerank/text-rerank`` (native endpoint).
        The native endpoint accepts flat params for qwen3-rerank and nested
        params for the others, so the payload format is still chosen per model.

The DashScope host does NOT expose ``/compatible-api/v1/reranks`` — that path
only exists on the MaaS API host. Routing qwen3-rerank through the native
endpoint on the DashScope host is the documented fallback (see the official
DashScope SDK examples, which call qwen3-rerank via the native URL with flat
params).

Both endpoints share the response shape::

    {"output": {"results": [{"index": int, "relevance_score": float, "document"?: {"text": str}}]},
     "usage": {"total_tokens": int}, "request_id": str}

Other protocols (Cohere, Jina, Voyage) can be added later by extending the
``rerank`` function with a ``protocol`` branch.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.llm.registry import ResolvedModel, resolve_role

log = get_logger(__name__)


# Bailian rerank endpoints. Two routes exist — see module docstring.
BAILIAN_COMPATIBLE_RERANK_PATH = "/compatible-api/v1/reranks"
BAILIAN_NATIVE_RERANK_PATH = "/api/v1/services/rerank/text-rerank/text-rerank"
BAILIAN_DEFAULT_HOST = "https://dashscope.aliyuncs.com"

# Hosts that expose the OpenAI-compatible rerank endpoint
# (``/compatible-api/v1/reranks``). The DashScope host
# (``dashscope.aliyuncs.com``) does NOT — it only exposes the native endpoint,
# so qwen3-rerank must be routed through the native path there.
_MAAS_API_HOST_SUFFIX = ".maas.aliyuncs.com"

# Models that use the OpenAI-compatible flat-param endpoint.
# Everything else (gte-rerank-v2, qwen3-vl-rerank, future native models)
# uses the nested native endpoint.
_COMPATIBLE_MODELS = frozenset({"qwen3-rerank"})

# Default instruct for qwen3-rerank — per the doc, this guides the model toward
# QA-style retrieval ranking. The user can override via metadata on the model
# row if needed (future enhancement).
_DEFAULT_INSTRUCT = "Given a web search query, retrieve relevant passages that answer the query."


class RerankError(RuntimeError):
    """Raised when a rerank provider returns an error."""


def rerank(
    query: str,
    documents: list[str],
    *,
    top_n: int | None = None,
    return_documents: bool = False,
) -> list[dict[str, Any]]:
    """Rerank ``documents`` against ``query`` using the configured rerank model.

    Returns a list of ``{"index": int, "relevance_score": float, ...}`` dicts,
    sorted descending by score. The ``index`` field refers to the position in
    the original ``documents`` list.

    Raises ``RerankError`` if no rerank model is configured or the provider
    returns an error.
    """
    resolved = resolve_role("rerank")
    if resolved is None:
        raise RerankError("No rerank model configured. Add one in Settings.")

    protocol = resolved.provider.protocol
    if protocol == "bailian":
        return _rerank_bailian(resolved, query, documents, top_n, return_documents)
    # Future: cohere / jina / voyage
    raise RerankError(
        f"Rerank is not supported for provider protocol '{protocol}'. "
        "Use a Bailian (DashScope) provider."
    )


# ---------- Bailian (DashScope) ----------


def _is_compatible_model(model_name: str) -> bool:
    """Return True if the model uses the OpenAI-compatible flat-param endpoint."""
    name = (model_name or "").strip().lower()
    return name in _COMPATIBLE_MODELS


def _resolve_bailian_url(base_url: str | None, model_name: str) -> str:
    """Resolve the correct Bailian rerank URL for this model.

    The user may have configured the provider ``base_url`` as either:
      - the host root (e.g. ``https://dashscope.aliyuncs.com``)
      - the OpenAI-compatible base (ending ``/compatible-mode/v1`` or ``/v1``)
      - the MaaS API base (``https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-api/v1``)
      - the full native rerank URL (legacy)
      - empty / None → use the default host

    We normalize to the host root, then append the correct path based on
    model AND host:

      - MaaS API host (``*.maas.aliyuncs.com``) + qwen3-rerank → compatible endpoint
      - DashScope host (``dashscope.aliyuncs.com``) + ANY model → native endpoint
        (the DashScope host does not expose ``/compatible-api/v1/reranks``)
      - Unknown host → native endpoint (safer default)
    """
    host = BAILIAN_DEFAULT_HOST
    if base_url:
        # Strip known path suffixes to get back to the host root.
        b = base_url.rstrip("/")
        for suffix in (
            BAILIAN_NATIVE_RERANK_PATH,
            BAILIAN_COMPATIBLE_RERANK_PATH,
            "/compatible-mode/v1",
            "/compatible-api/v1",
            "/api/v1",
            "/v1",
        ):
            if b.endswith(suffix):
                b = b[: -len(suffix)]
                break
        host = b or BAILIAN_DEFAULT_HOST

    # Use the OpenAI-compatible endpoint ONLY on the MaaS API host. The
    # DashScope host (and any unknown host) does not expose that path —
    # we route qwen3-rerank through the native endpoint there, which the
    # official docs confirm accepts flat params for qwen3-rerank.
    is_maas_api_host = _MAAS_API_HOST_SUFFIX in host
    if is_maas_api_host and _is_compatible_model(model_name):
        return f"{host}{BAILIAN_COMPATIBLE_RERANK_PATH}"
    return f"{host}{BAILIAN_NATIVE_RERANK_PATH}"


def _rerank_bailian(
    resolved: ResolvedModel,
    query: str,
    documents: list[str],
    top_n: int | None,
    return_documents: bool,
) -> list[dict[str, Any]]:
    """Call the Bailian rerank API, routing to the correct endpoint by model."""
    if not resolved.provider.api_key:
        raise RerankError("Bailian provider has no API key configured.")

    model_name = resolved.model.name
    url = _resolve_bailian_url(resolved.provider.base_url, model_name)

    if _is_compatible_model(model_name):
        payload = _build_compatible_payload(
            model_name, query, documents, top_n, return_documents
        )
    else:
        payload = _build_native_payload(
            model_name, query, documents, top_n, return_documents
        )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved.provider.api_key}",
    }

    log.info(
        "rerank.bailian_request",
        model=model_name,
        endpoint="compatible" if _is_compatible_model(model_name) else "native",
        documents=len(documents),
        top_n=top_n,
    )

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500] if exc.response is not None else ""
        log.error(
            "rerank.bailian_http_error",
            status=exc.response.status_code,
            body=body,
            model=model_name,
        )
        raise RerankError(
            f"Bailian rerank HTTP {exc.response.status_code}: {body}"
        ) from exc
    except httpx.RequestError as exc:
        raise RerankError(f"Bailian rerank request failed: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise RerankError(f"Bailian rerank returned non-JSON: {exc}") from exc

    # Error responses use {"code": "...", "message": "...", "request_id": "..."}
    if "code" in data and data["code"]:
        raise RerankError(
            f"Bailian rerank error {data.get('code')}: {data.get('message')} "
            f"(request_id={data.get('request_id')})"
        )

    if "output" not in data or "results" not in data.get("output", {}):
        req_id = data.get("request_id")
        raise RerankError(
            f"Bailian rerank unexpected response (request_id={req_id}): {str(data)[:300]}"
        )

    results = data["output"]["results"]
    out: list[dict[str, Any]] = []
    for r in results:
        out.append(
            {
                "index": r.get("index"),
                "relevance_score": r.get("relevance_score"),
                **(
                    {"document": r["document"]}
                    if return_documents and "document" in r
                    else {}
                ),
            }
        )
    out.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
    return out


def _build_compatible_payload(
    model_name: str,
    query: str,
    documents: list[str],
    top_n: int | None,
    return_documents: bool,
) -> dict[str, Any]:
    """Build the flat-param payload for qwen3-rerank (compatible endpoint).

    Per the doc: ``model``, ``query``, ``documents``, ``top_n``, ``instruct``
    all live at the top level (no ``input`` / ``parameters`` nesting).
    ``return_documents`` is not part of this endpoint — the compatible API
    always returns scores only; callers wanting document text should
    reconstruct from the original list using ``index``.
    """
    payload: dict[str, Any] = {
        "model": model_name,
        "query": query,
        "documents": documents,
        "instruct": _DEFAULT_INSTRUCT,
    }
    if top_n is not None:
        payload["top_n"] = top_n
    return payload


def _build_native_payload(
    model_name: str,
    query: str,
    documents: list[str],
    top_n: int | None,
    return_documents: bool,
) -> dict[str, Any]:
    """Build the nested-param payload for gte-rerank-v2 / qwen3-vl-rerank.

    Per the doc: ``{model, input:{query, documents}, parameters:{top_n, return_documents}}``.
    For qwen3-vl-rerank the query/documents can be multimodal objects, but for
    plain text we keep the string form which both endpoints accept.
    """
    parameters: dict[str, Any] = {"return_documents": return_documents}
    if top_n is not None:
        parameters["top_n"] = top_n
    # qwen3-vl-rerank also supports ``instruct`` inside parameters; gte-rerank-v2 does not.
    if model_name.lower().startswith("qwen3-vl-rerank"):
        parameters["instruct"] = _DEFAULT_INSTRUCT
    return {
        "model": model_name,
        "input": {"query": query, "documents": documents},
        "parameters": parameters,
    }


__all__ = ["RerankError", "rerank"]
