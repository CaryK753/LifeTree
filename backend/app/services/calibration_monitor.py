"""Periodic calibration reporting, fitting gates, and drift alerts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.intelligence import CalibrationReport
from app.models.model_params import PredictionOutcome
from app.models.user import UserProfile
from app.services.model_params import ModelParamStore
from app.services.notification import NotificationService
from app.services.prediction_outcomes import PredictionOutcomeService

MIN_CALIBRATION_SAMPLES = 50
DRIFT_THRESHOLD = 0.05
WINDOW_DAYS = 90


class CalibrationMonitor:
    """Create versioned reports and fit only after the sample gate is met."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def run_all_scopes(self, *, notify_admins: bool = True) -> list[CalibrationReport]:
        scopes = list(self.db.execute(
            select(PredictionOutcome.goal_type, PredictionOutcome.region).distinct()
        ).all())
        reports = [self.run_scope(goal_type, region) for goal_type, region in scopes]
        if notify_admins:
            for report in reports:
                if report.drift_detected:
                    self._notify_admins(report)
        return reports

    def run_scope(self, goal_type: str, region: str) -> CalibrationReport:
        today = datetime.now(UTC).date()
        existing = self.db.scalar(select(CalibrationReport).where(
            CalibrationReport.goal_type == goal_type,
            CalibrationReport.region == region,
            CalibrationReport.window_end == today,
        ))
        if existing is not None:
            return existing

        stats = PredictionOutcomeService(self.db).compute_brier_score(goal_type, region)
        previous = self.db.scalar(
            select(CalibrationReport)
            .where(
                CalibrationReport.goal_type == goal_type,
                CalibrationReport.region == region,
            )
            .order_by(CalibrationReport.window_end.desc())
            .limit(1)
        )
        previous_brier = previous.brier_score if previous else None
        drift = abs(stats["brier_score"] - previous_brier) if previous_brier is not None else 0.0
        calibrated = stats["sample_size"] >= MIN_CALIBRATION_SAMPLES

        report = CalibrationReport(
            goal_type=goal_type,
            region=region,
            window_start=today - timedelta(days=WINDOW_DAYS),
            window_end=today,
            sample_size=stats["sample_size"],
            brier_score=stats["brier_score"],
            previous_brier_score=previous_brier,
            drift_score=round(drift, 6),
            drift_detected=drift >= DRIFT_THRESHOLD,
            calibrated=calibrated,
            reliability_curve=stats["reliability_curve"],
            meta={"minimum_samples": MIN_CALIBRATION_SAMPLES},
        )
        self.db.add(report)
        self.db.flush()
        if calibrated:
            self._fit_probability_bias(goal_type, region, stats)
        self.db.commit()
        self.db.refresh(report)
        return report

    def _fit_probability_bias(
        self, goal_type: str, region: str, stats: dict[str, Any]
    ) -> None:
        # Bounded intercept correction. It is deliberately simple and
        # auditable; richer fitting belongs behind held-out validation.
        bias = max(-0.25, min(0.25, stats["mean_actual"] - stats["mean_predicted"]))
        store = ModelParamStore(self.db)
        store.set_param(
            "calibration_probability_bias",
            bias,
            goal_type=goal_type,
            region=region,
            notes="Fitted from terminal outcomes; bounded to +/-0.25.",
        )
        store.mark_calibrated(
            goal_type=goal_type,
            region=region,
            sample_size=stats["sample_size"],
        )

    def _notify_admins(self, report: CalibrationReport) -> None:
        admins = list(self.db.scalars(select(UserProfile).where(UserProfile.role == "admin")))
        service = NotificationService(self.db)
        for admin in admins:
            service.notify(
                admin,
                title="模型校准漂移告警",
                body=(
                    f"{report.goal_type}/{report.region} 的 Brier Score 变化 "
                    f"{report.drift_score:.3f}，请检查样本和参数。"
                ),
                severity="warning",
                risk_factor_id=f"calibration:{report.goal_type}:{report.region}:{report.window_end}",
                impact_summary={"calibration_report_id": report.id},
            )


def calibration_report_dict(report: CalibrationReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "goal_type": report.goal_type,
        "region": report.region,
        "window_start": report.window_start.isoformat(),
        "window_end": report.window_end.isoformat(),
        "sample_size": report.sample_size,
        "brier_score": report.brier_score,
        "previous_brier_score": report.previous_brier_score,
        "drift_score": report.drift_score,
        "drift_detected": report.drift_detected,
        "calibrated": report.calibrated,
        "reliability_curve": report.reliability_curve,
    }
