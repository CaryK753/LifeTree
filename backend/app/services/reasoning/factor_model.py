"""Shared aggregation semantics for structured scenario forecasts."""

from __future__ import annotations

import math
from collections.abc import Sequence

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
    *,
    axis: int | None = None,
) -> np.ndarray | float:
    """Combine hazards while tempering the false independence assumption."""
    clipped = np.clip(survivals, 1e-3, 1.0)
    count = clipped.shape[axis] if axis is not None else clipped.size
    exponent = 1.0 / math.sqrt(max(1, count))
    product = np.prod(clipped, axis=axis)
    result = np.power(product, exponent)
    return float(result) if axis is None else result


def aggregate_success(
    requirement_probs: np.ndarray,
    requirement_weights: Sequence[float],
    risk_survivals: np.ndarray,
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
        correlated_risk_survival(risk_survivals, axis=axis)
        if risk_survivals.size
        else 1.0
    )
    return np.clip(np.asarray(readiness) * np.asarray(survival), 0.01, 0.99)
