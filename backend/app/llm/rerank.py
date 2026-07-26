"""Rerank clients for second-stage retrieval.

Supports Alibaba Cloud Bailian (DashScope) rerank models:

  - **qwen3-rerank** uses *flat* request params (``model``, ``query``,
    ``documents``, ``top_n``, ``instruct`` at top level) and the
    OpenAI-compatible endpoint ``/compatible-api/v1/reranks``.
  - **gte-rerank-v2** and **qwen3-vl-rerank** use *nested* params
    (``{model, input:{query, documents}, parameters:{top_n, return_documents}}``)
    and the native endpoint ``/api/v1/services/rerank/text-rerank/text-rerank``.

Endpoint routing depends on the MODEL ONLY (per the official Bailian rerank
doc). Both the DashScope host (``dashscope.aliyuncs.com``) and the MaaS API
host (``*.maas.aliyuncs.com``) expose both endpoints; the choice is determined
by which model is being called, NOT by which host was configured.

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
    if protocol in ("bailian", "bailian_rerank"):
        return _rerank_bailian(resolved, query, documents, top_n, return_documents)
    # Future: cohere / jina / voyage
    raise RerankError(
        f"Rerank is not supported for provider protocol '{protocol}'. "
        "Use a Bailian (DashScope) provider or the dedicated Bailian Rerank provider."
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
    MODEL ONLY (per the official Alibaba Cloud Bailian rerank doc):

      - qwen3-rerank → ``/compatible-api/v1/reranks`` (flat params: model, query,
        documents, top_n, instruct at top level). Both DashScope host and
        MaaS API host expose this endpoint.
      - gte-rerank-v2 / qwen3-vl-rerank → ``/api/v1/services/rerank/text-rerank/text-rerank``
        (nested params: input.{query,documents} + parameters.{top_n, return_documents}).

    The previous host-based routing was wrong: it sent qwen3-rerank to the
    native endpoint on the DashScope host, but that endpoint does NOT accept
    the flat params qwen3-rerank uses — causing connection failures.
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

    # Route by MODEL, not by host. Both DashScope and MaaS API hosts expose
    # both endpoints; the choice depends only on which model is being called.
    if _is_compatible_model(model_name):
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

    # Two response shapes exist depending on which endpoint was called:
    #
    # 1. Native endpoint (/api/v1/services/rerank/text-rerank/text-rerank):
    #    {"output": {"results": [...]}, "usage": {...}, "request_id": "..."}
    #
    # 2. Compatible endpoint (/compatible-api/v1/reranks, used by qwen3-rerank):
    #    {"object": "list", "results": [...], "model": "...", "id": "...", "usage": {...}}
    #    NOTE: no ``output`` wrapper, no ``request_id``. The results array is
    #    at the top level. This is the OpenAI-style rerank response shape.
    if "output" in data and "results" in data.get("output", {}):
        results = data["output"]["results"]
    elif "results" in data and isinstance(data["results"], list):
        results = data["results"]
    else:
        req_id = data.get("request_id")
        raise RerankError(
            f"Bailian rerank unexpected response (request_id={req_id}): {str(data)[:300]}"
        )

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
