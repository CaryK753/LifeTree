"""ModelParamStore — typed, scoped accessor for the ``model_params`` table.

Per project plan §11.2 缺口 G: reasoning-engine constants are no longer
hardcoded. This store resolves a parameter key with the scope cascade:

    (goal_type, region) → (goal_type, __global__) → (__global__, __global__)

and coerces the stored text value to the requested Python type. A
module-level cache fronts the DB so hot-path calls (e.g. inside Monte
Carlo iterations) don't pay a round-trip per parameter.

The cache is invalidated whenever ``set_param`` / ``bulk_set`` /
``calibrate`` mutates a row, and on a 60s TTL as a safety net for
multi-process admin edits. Callers that need a fresh snapshot (e.g. the
reasoning engine at the start of a run) should call ``invalidate()``.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.model_params import ModelParam

log = get_logger(__name__)

_GLOBAL = "__global__"
_CACHE_TTL_SECONDS = 60.0


class ModelParamStore:
    """Scoped, typed, cached reader/writer for ``model_params`` rows."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._cache: dict[tuple[str, str, str], tuple[Any, float]] = {}

    # ---------------- Public reads ----------------

    def get_float(
        self,
        key: str,
        *,
        default: float,
        goal_type: str = _GLOBAL,
        region: str = _GLOBAL,
    ) -> float:
        return float(self._get(key, default, goal_type, region, "float"))

    def get_int(
        self,
        key: str,
        *,
        default: int,
        goal_type: str = _GLOBAL,
        region: str = _GLOBAL,
    ) -> int:
        return int(self._get(key, default, goal_type, region, "int"))

    def get_bool(
        self,
        key: str,
        *,
        default: bool,
        goal_type: str = _GLOBAL,
        region: str = _GLOBAL,
    ) -> bool:
        return bool(self._get(key, default, goal_type, region, "bool"))

    def get_json(
        self,
        key: str,
        *,
        default: Any,
        goal_type: str = _GLOBAL,
        region: str = _GLOBAL,
    ) -> Any:
        return self._get(key, default, goal_type, region, "json")

    def is_calibrated(
        self, *, goal_type: str = _GLOBAL, region: str = _GLOBAL
    ) -> bool:
        """True if any parameter in the given scope is marked calibrated.

        The frontend uses this to render the '未校准' / '已校准' badge on
        prediction results.
        """
        row = self._fetch_scope_meta(goal_type, region)
        return bool(row and row.get("calibrated") == "true")

    def calibration_sample_size(
        self, *, goal_type: str = _GLOBAL, region: str = _GLOBAL
    ) -> int:
        row = self._fetch_scope_meta(goal_type, region)
        return int(row.get("calibration_sample_size", 0)) if row else 0

    # ---------------- Public writes ----------------

    def set_param(
        self,
        key: str,
        value: Any,
        *,
        value_type: str = "float",
        goal_type: str = _GLOBAL,
        region: str = _GLOBAL,
        notes: str | None = None,
    ) -> ModelParam:
        """Upsert a single parameter row and invalidate the cache."""
        serialized = self._serialize(value, value_type)
        row = self._db.scalar(
            select(ModelParam).where(
                ModelParam.goal_type == goal_type,
                ModelParam.region == region,
                ModelParam.key == key,
            )
        )
        if row is None:
            row = ModelParam(
                goal_type=goal_type,
                region=region,
                key=key,
                value=serialized,
                value_type=value_type,
                notes=notes,
            )
            self._db.add(row)
        else:
            row.value = serialized
            row.value_type = value_type
            if notes is not None:
                row.notes = notes
        self._db.commit()
        self._db.refresh(row)
        self.invalidate()
        log.info(
            "model_param.set",
            key=key,
            goal_type=goal_type,
            region=region,
            value=serialized,
        )
        return row

    def mark_calibrated(
        self,
        *,
        goal_type: str = _GLOBAL,
        region: str = _GLOBAL,
        sample_size: int,
    ) -> int:
        """Flip ``calibrated`` to true for all rows in a scope after a
        calibration run. Returns the number of rows updated.
        """
        rows = list(
            self._db.scalars(
                select(ModelParam).where(
                    ModelParam.goal_type == goal_type,
                    ModelParam.region == region,
                )
            )
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        for r in rows:
            r.calibrated = "true"
            r.calibration_sample_size = sample_size
            r.last_calibrated_at = now_iso
        self._db.commit()
        self.invalidate()
        log.info(
            "model_param.calibrated",
            goal_type=goal_type,
            region=region,
            sample_size=sample_size,
            rows=len(rows),
        )
        return len(rows)

    def invalidate(self) -> None:
        self._cache.clear()

    # ---------------- Internal ----------------

    def _get(
        self,
        key: str,
        default: Any,
        goal_type: str,
        region: str,
        expected_type: str,
    ) -> Any:
        cache_key = (goal_type, region, key)
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and (now - cached[1]) < _CACHE_TTL_SECONDS:
            return cached[0]

        value = self._resolve_scoped(key, goal_type, region, expected_type)
        if value is None:
            value = default
        self._cache[cache_key] = (value, now)
        return value

    def _resolve_scoped(
        self,
        key: str,
        goal_type: str,
        region: str,
        expected_type: str,
    ) -> Any | None:
        """Try (gt, r) → (gt, __global__) → (__global__, __global__)."""
        for gt, r in [
            (goal_type, region),
            (goal_type, _GLOBAL),
            (_GLOBAL, _GLOBAL),
        ]:
            row = self._db.scalar(
                select(ModelParam).where(
                    ModelParam.goal_type == gt,
                    ModelParam.region == r,
                    ModelParam.key == key,
                )
            )
            if row is not None:
                return self._coerce(row.value, row.value_type, expected_type)
        return None

    def _fetch_scope_meta(
        self, goal_type: str, region: str
    ) -> dict[str, Any] | None:
        """Return the first row's calibration metadata for the scope."""
        for gt, r in [
            (goal_type, region),
            (goal_type, _GLOBAL),
            (_GLOBAL, _GLOBAL),
        ]:
            row = self._db.scalar(
                select(ModelParam).where(
                    ModelParam.goal_type == gt,
                    ModelParam.region == r,
                ).limit(1)
            )
            if row is not None:
                return {
                    "calibrated": row.calibrated,
                    "calibration_sample_size": row.calibration_sample_size,
                }
        return None

    @staticmethod
    def _serialize(value: Any, value_type: str) -> str:
        if value_type == "json":
            return json.dumps(value)
        if value_type == "bool":
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _coerce(stored: str, stored_type: str, expected_type: str) -> Any:
        if expected_type == "float":
            return float(stored)
        if expected_type == "int":
            return int(float(stored))
        if expected_type == "bool":
            return stored.lower() == "true"
        if expected_type == "json":
            return json.loads(stored) if stored else {}
        return stored


# ---------------- Module-level helpers for hot paths ----------------

# Reasoning-engine code that doesn't own a DB session (e.g. the pure
# aggregation functions in factor_model.py) reads defaults from a
# snapshot dict. The engine facade builds this snapshot once per run via
# ``build_param_snapshot`` and passes it down. This keeps the inner
# functions pure while still sourcing values from the DB.

_DEFAULT_SNAPSHOT: dict[str, Any] = {
    "requirement_base_prob.met": 0.92,
    "requirement_base_prob.partial": 0.60,
    "requirement_base_prob.missing": 0.40,
    "requirement_base_prob.unknown": 0.50,
    "requirement_weight_blend": 0.2,
    "risk_level_p.low": 0.08,
    "risk_level_p.medium": 0.20,
    "risk_level_p.high": 0.40,
    "risk_level_blend": 0.5,
    "correlation_alpha": 0.3,
    "survival_horizon_months": 36,
    "survival_shape_offset": 1.0,
    "survival_scale_offset": 0.5,
    "calibration_probability_bias": 0.0,
}


def build_param_snapshot(
    db: Session,
    *,
    goal_type: str = _GLOBAL,
    region: str = _GLOBAL,
) -> dict[str, Any]:
    """Build a flat dict snapshot of all params for a given scope.

    The reasoning engine calls this once at the start of a run and
    passes the snapshot to the pure aggregation functions. Falls back to
    ``_DEFAULT_SNAPSHOT`` for any missing key, so behavior is always
    defined even on a fresh DB.
    """
    snapshot = dict(_DEFAULT_SNAPSHOT)
    store = ModelParamStore(db)
    for key in _DEFAULT_SNAPSHOT:
        default = _DEFAULT_SNAPSHOT[key]
        if isinstance(default, float):
            snapshot[key] = store.get_float(key, default=default, goal_type=goal_type, region=region)
        elif isinstance(default, int):
            snapshot[key] = store.get_int(key, default=default, goal_type=goal_type, region=region)
        elif isinstance(default, bool):
            snapshot[key] = store.get_bool(key, default=default, goal_type=goal_type, region=region)
    meta = store._fetch_scope_meta(goal_type, region) or {}
    snapshot["__calibrated__"] = meta.get("calibrated") == "true"
    snapshot["__calibration_sample_size__"] = int(meta.get("calibration_sample_size", 0))
    return snapshot
