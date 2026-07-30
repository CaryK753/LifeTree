"""Shared aggregation semantics for structured scenario forecasts.

Per project plan §11.2 缺口 G: aggregation constants are no longer
hardcoded. Pure functions below accept a ``params`` snapshot dict (built
once per run by ``ModelParamStore.build_param_snapshot``) so the same
code serves both heuristic defaults and data-calibrated values.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

MODEL_VERSION = "structured-scenario-v2"


def normalized_weights(weights: Sequence[float]) -> np.ndarray:
    values = np.asarray([max(0.05, min(2.0, float(w))) for w in weights])
    return values / values.sum()


def weighted_geometric_mean(
    probabilities: np.ndarray,
    weights: Sequence[float],
    *,
    axis: int | None = None,
) -> np.ndarray | float:
    """Aggregate jointly-needed requirements without rewarding duplicates."""
    clipped = np.clip(probabilities, 1e-3, 1 - 1e-3)
    norm = normalized_weights(weights)
    if axis is None:
        return float(np.exp(np.sum(norm * np.log(clipped))))
    return np.exp(np.sum(np.log(clipped) * norm, axis=axis))


def correlated_risk_survival(
    survivals: np.ndarray,
    params: dict[str, Any] | None = None,
    *,
    axis: int | None = None,
) -> np.ndarray | float:
    """Combine hazards while tempering the false independence assumption.

    Uses a copula-style blend: the joint survival is a weighted average of
    the product (full independence, pessimistic) and the geometric mean
    (perfect correlation, optimistic). The blend weight ``correlation_alpha``
    is sourced from ``params`` (key ``correlation_alpha``), defaulting to
    0.3 when unset — matching the pre-externalization heuristic.
    """
    p = params or {}
    alpha = float(p.get("correlation_alpha", 0.3))
    alpha = max(0.0, min(1.0, alpha))

    clipped = np.clip(survivals, 1e-3, 1.0)
    count = clipped.shape[axis] if axis is not None else clipped.size
    if count <= 1:
        result = np.prod(clipped, axis=axis)
        return float(result) if axis is None else result
    product = np.prod(clipped, axis=axis)
    gmean = np.power(product, 1.0 / count)
    result = alpha * product + (1.0 - alpha) * gmean
    return float(result) if axis is None else result


def aggregate_success(
    requirement_probs: np.ndarray,
    requirement_weights: Sequence[float],
    risk_survivals: np.ndarray,
    params: dict[str, Any] | None = None,
    *,
    axis: int | None = None,
) -> np.ndarray | float:
    if requirement_probs.size:
        readiness = weighted_geometric_mean(
            requirement_probs, requirement_weights, axis=axis
        )
    else:
        shape = risk_survivals.shape[0] if axis == 1 else None
        readiness = np.full(shape, 0.5) if shape is not None else 0.5
    survival = (
        correlated_risk_survival(risk_survivals, params, axis=axis)
        if risk_survivals.size
        else 1.0
    )
    return np.clip(np.asarray(readiness) * np.asarray(survival), 0.01, 0.99)


def aggregate_risk_exposure(
    risk_survivals: Sequence[float], params: dict[str, Any] | None = None
) -> float:
    """Return modeled risk exposure independently from requirement readiness."""
    values = np.asarray(risk_survivals, dtype=float)
    if not values.size:
        return 0.0
    survival = correlated_risk_survival(values, params)
    return float(np.clip(1.0 - survival, 0.0, 1.0))
