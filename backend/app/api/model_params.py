"""Admin-only endpoints for model params + prediction-outcome calibration.

Exposes the ``model_params`` table for admin tuning (§11.2 缺口 G) and a
calibration view backed by ``PredictionOutcomeService.compute_brier_score``.

All endpoints require the ``admin`` role (resolved via ``AdminUser`` —
returns 403 for non-admins, mirroring ``app.api.admin``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import AdminUser
from app.db.postgres import get_db
from app.models.intelligence import CalibrationReport
from app.models.model_params import ModelParam, PredictionOutcome
from app.services.calibration_monitor import CalibrationMonitor, calibration_report_dict
from app.services.prediction_outcomes import PredictionOutcomeService

log = get_logger(__name__)

router = APIRouter(prefix="/model-params", tags=["model-params"])


# ---------- Schemas ----------


class ModelParamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    goal_type: str
    region: str
    key: str
    value: str
    value_type: str
    calibrated: str
    calibration_sample_size: int
    last_calibrated_at: str | None = None
    notes: str | None = None


class ModelParamUpdate(BaseModel):
    """Admin can update a single param's stored value (+ optional notes)."""

    value: str = Field(..., description="Serialized value (text).")
    value_type: str | None = Field(None, description='"float" | "int" | "bool" | "json"')
    notes: str | None = None


class PredictionOutcomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    goal_id: str
    scenario_id: str | None = None
    run_id: str | None = None
    goal_type: str
    region: str
    predicted_p50: float | None = None
    predicted_p10: float | None = None
    predicted_p90: float | None = None
    predicted_at: str | None = None
    model_version: str | None = None
    factor_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    actual_outcome: str
    actual_date: Any | None = None
    actual_binary: int
    notes: str | None = None


class ScopeCalibration(BaseModel):
    goal_type: str
    region: str
    sample_size: int
    brier_score: float
    mean_predicted: float
    mean_actual: float
    reliability_curve: list[dict[str, Any]] = Field(default_factory=list)


class CalibrationResponse(BaseModel):
    brier_score: float
    sample_size: int
    per_scope: list[ScopeCalibration]


# ---------- Endpoints ----------


@router.get("", response_model=list[ModelParamRead])
def list_model_params(
    admin: AdminUser,
    db: Session = Depends(get_db),
    goal_type: str | None = Query(None, description="Filter by goal_type tag."),
    region: str | None = Query(None, description="Filter by region."),
) -> list[ModelParam]:
    """List all model params (admin only), optionally filtered by scope."""
    stmt = select(ModelParam).order_by(
        ModelParam.goal_type.asc(),
        ModelParam.region.asc(),
        ModelParam.key.asc(),
    )
    if goal_type is not None:
        stmt = stmt.where(ModelParam.goal_type == goal_type)
    if region is not None:
        stmt = stmt.where(ModelParam.region == region)
    return list(db.scalars(stmt))


@router.get("/calibration", response_model=CalibrationResponse)
def get_calibration(
    admin: AdminUser,
    db: Session = Depends(get_db),
) -> CalibrationResponse:
    """Aggregate Brier calibration across every (goal_type, region) scope.

    The top-level ``brier_score`` / ``sample_size`` cover all outcomes;
    ``per_scope`` breaks the same stats down for each scope that has at
    least one outcome row.
    """
    svc = PredictionOutcomeService(db)
    overall = svc.compute_brier_score()

    # Distinct (goal_type, region) pairs that have any outcome row.
    pairs = list(
        db.execute(
            select(PredictionOutcome.goal_type, PredictionOutcome.region)
            .distinct()
            .order_by(PredictionOutcome.goal_type.asc(), PredictionOutcome.region.asc())
        ).all()
    )

    per_scope: list[ScopeCalibration] = []
    for gt, reg in pairs:
        stats = svc.compute_brier_score(goal_type=gt, region=reg)
        per_scope.append(
            ScopeCalibration(
                goal_type=gt,
                region=reg,
                sample_size=stats["sample_size"],
                brier_score=stats["brier_score"],
                mean_predicted=stats["mean_predicted"],
                mean_actual=stats["mean_actual"],
                reliability_curve=stats["reliability_curve"],
            )
        )

    return CalibrationResponse(
        brier_score=overall["brier_score"],
        sample_size=overall["sample_size"],
        per_scope=per_scope,
    )


@router.get("/outcomes", response_model=list[PredictionOutcomeRead])
def list_outcomes(
    admin: AdminUser,
    db: Session = Depends(get_db),
    goal_type: str | None = Query(None, description="Filter by goal_type tag."),
    region: str | None = Query(None, description="Filter by region."),
    limit: int = Query(100, ge=1, le=1000),
) -> list[PredictionOutcome]:
    """List prediction outcomes (admin only), filterable by scope."""
    return PredictionOutcomeService(db).list_outcomes(
        goal_type=goal_type, region=region, limit=limit
    )


@router.get("/calibration/reports")
def list_calibration_reports(
    admin: AdminUser,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(CalibrationReport).order_by(CalibrationReport.window_end.desc()).limit(limit)
        )
    )
    return [calibration_report_dict(row) for row in rows]


@router.post("/calibration/run")
def run_calibration(admin: AdminUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    reports = CalibrationMonitor(db).run_all_scopes()
    return {
        "reports": [calibration_report_dict(row) for row in reports],
        "count": len(reports),
    }


@router.patch("/{param_id}", response_model=ModelParamRead)
def update_model_param(
    param_id: str,
    payload: ModelParamUpdate,
    admin: AdminUser,
    db: Session = Depends(get_db),
) -> ModelParam:
    """Update a single param's stored value (admin only)."""
    param = db.get(ModelParam, param_id)
    if param is None:
        raise HTTPException(404, "Model param not found")

    param.value = payload.value
    if payload.value_type is not None:
        if payload.value_type not in ("float", "int", "bool", "json"):
            raise HTTPException(400, "value_type must be one of float|int|bool|json")
        param.value_type = payload.value_type
    if payload.notes is not None:
        param.notes = payload.notes

    db.commit()
    db.refresh(param)
    log.info(
        "model_param.updated",
        id=param_id,
        key=param.key,
        admin=admin.id,
    )
    return param


__all__ = ["router"]
