"""Survival analysis: P(success by time t).

Per project plan §4.6: estimates the cumulative probability of achieving
the goal by each time t up to (and beyond) the target_date.

Per §11.2 缺口 G: Weibull shape/scale offsets and horizon are sourced
from a ``params`` snapshot (keys ``survival_shape_offset``,
``survival_scale_offset``, ``survival_horizon_months``) so they can be
tuned per goal_type/region and calibrated from real outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from app.models.goal import Goal


@dataclass(slots=True)
class SurvivalResult:
    curve: list[dict[str, float]]
    p_by_target_date: float
    median_time_months: int | None


class SurvivalEstimator:
    """Kaplan-Meier-flavoured estimator with a Weibull base hazard."""

    def estimate(
        self,
        goal: Goal,
        p_success: float,
        *,
        horizon_months: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> SurvivalResult:
        p = params or {}
        if horizon_months is None:
            horizon_months = int(p.get("survival_horizon_months", 36))
        shape_offset = float(p.get("survival_shape_offset", 1.0))
        scale_offset = float(p.get("survival_scale_offset", 0.5))

        # Weibull shape: ambitious goals (low p_success) → concave (slow start),
        # easy goals (high p_success) → convex (fast start).
        shape = shape_offset + (1.0 - p_success)
        scale = max(1.0, horizon_months * (1.0 - p_success + scale_offset))

        months = np.arange(0, horizon_months + 1)
        # Cumulative hazard H(t) = (t/scale)^shape
        H = (months / scale) ** shape
        # S(t) = exp(-H(t)); F(t) = 1 - S(t)
        cum_prob = 1.0 - np.exp(-H)
        # Scale so that final cum_prob reflects p_success
        if cum_prob[-1] > 0:
            cum_prob = cum_prob * (p_success / cum_prob[-1])
        cum_prob = np.clip(cum_prob, 0.0, p_success)

        curve = [
            {"t": self._month_to_date(goal, int(m)), "p": float(p_)}
            for m, p_ in zip(months, cum_prob)
        ]

        p_target = 0.0
        if goal.target_date:
            target_month_idx = self._months_until(goal.target_date)
            if 0 <= target_month_idx < len(cum_prob):
                p_target = float(cum_prob[target_month_idx])

        median_idx = int(np.searchsorted(cum_prob, 0.5))
        median_months: int | None = (
            int(months[median_idx]) if median_idx < len(months) else None
        )

        return SurvivalResult(
            curve=curve,
            p_by_target_date=p_target,
            median_time_months=median_months,
        )

    # ---------------- Helpers ----------------

    @staticmethod
    def _months_until(target: date, *, from_: date | None = None) -> int:
        base = from_ or date.today()
        return max(
            0,
            (target.year - base.year) * 12 + (target.month - base.month),
        )

    @staticmethod
    def _month_to_date(goal: Goal, month_offset: int) -> str:
        base = goal.created_at.date() if goal.created_at else date.today()
        # Naive month arithmetic
        year = base.year + (base.month - 1 + month_offset) // 12
        month = (base.month - 1 + month_offset) % 12 + 1
        return f"{year:04d}-{month:02d}"
