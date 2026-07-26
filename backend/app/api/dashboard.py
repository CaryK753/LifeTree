"""Dashboard summary endpoint for the goal compass view.

Per project plan §5: the 目标罗盘仪表盘 shows, on a single timeline view,
the key milestones, progress, risk heatmap and recent event flow for a goal.

This endpoint composes those pieces from:
- the Goal itself (title / scenario / target_date / status)
- the latest computed Scenario's cached success_probability (p10/p50/p90)
- the latest RiskAssessment's overall_risk + factor_scores (risk propagation)
- recent events, risk factor heatmap, credibility distribution
- consecutive planning days (distinct days with any user-initiated activity:
  scenario runs, ingestions, notifications — a "low-anxiety" positive-progress
  signal per §6 产品盲点).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.event import Event, InformationSource
from app.models.goal import Goal, Pathway, RiskFactor
from app.models.notification import NotificationLog, RiskAssessment
from app.models.scenario import Scenario, ScenarioRun, ScenarioStatus
from app.schemas.api import (
    CredibilityDistribution,
    DashboardSummary,
    EventRead,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/{goal_id}", response_model=DashboardSummary)
def get_dashboard(goal_id: str, db: Session = Depends(get_db)) -> DashboardSummary:
    """Compose the goal compass dashboard payload."""
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")

    # ---- Goal fields (so the compass card can render without a second fetch) ----
    goal_title = goal.title
    goal_scenario = goal.scenario
    goal_target_date = (
        goal.target_date.isoformat() if goal.target_date is not None else None
    )
    goal_status = goal.status

    # ---- Success probability: prefer the latest computed active scenario ----
    # The reasoning engine caches p10/p50/p90/bayesian_point onto the Scenario
    # row when ScenarioService.run_reasoning fires. We fall back to the latest
    # RiskAssessment (from risk propagation) for overall_risk / factor_scores.
    latest_scenario = db.scalar(
        select(Scenario)
        .where(Scenario.goal_id == goal_id)
        .order_by(Scenario.computed_at.desc().nullslast(), Scenario.created_at.desc())
    )
    scenario_prob: dict = {}
    if latest_scenario is not None and latest_scenario.success_probability:
        scenario_prob = dict(latest_scenario.success_probability)
        if latest_scenario.risk_score is not None:
            scenario_prob.setdefault("overall_risk", latest_scenario.risk_score)
        if latest_scenario.computed_at is not None:
            scenario_prob.setdefault(
                "computed_at", latest_scenario.computed_at.isoformat()
            )
        if latest_scenario.key_risk_factors:
            scenario_prob.setdefault(
                "key_risk_factors", list(latest_scenario.key_risk_factors)
            )

    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.goal_id == goal_id)
        .order_by(RiskAssessment.computed_at.desc())
    )
    if assessment is not None:
        # Risk propagation contributes overall_risk + factor_scores; scenario
        # numbers (p10/p50/p90) take precedence when both exist.
        scenario_prob.setdefault("overall_risk", assessment.overall_risk)
        scenario_prob.setdefault("factor_scores", assessment.factor_scores or [])
        scenario_prob.setdefault(
            "computed_at",
            assessment.computed_at.isoformat() if assessment.computed_at else None,
        )

    # ---- Drill-down: latest ScenarioRun.result gives the full reasoning output ----
    # Per project plan §5 透明化 + 收敛建议: expose optimal_action_sequence,
    # factor_contributions, explanation, survival_curve so the UI can render
    # the "无悔行动" card and a factor-breakdown drill-down alongside the
    # headline probability numbers.
    regret_free_actions: list[dict] = []
    factor_contributions: list[dict] = []
    reasoning_explanation: str | None = None
    median_time_months: float | None = None
    survival_curve: list[dict] = []
    key_risk_times: list[dict] = []
    reasoning_run_id: str | None = None
    reasoning_iterations: int | None = None

    if latest_scenario is not None:
        latest_run = db.scalar(
            select(ScenarioRun)
            .where(ScenarioRun.scenario_id == latest_scenario.id)
            .order_by(ScenarioRun.started_at.desc().nullslast(), ScenarioRun.created_at.desc())
        )
        if latest_run is not None and latest_run.result:
            r = latest_run.result or {}
            regret_free_actions = list(r.get("optimal_action_sequence") or [])
            factor_contributions = list(r.get("factor_contributions") or [])
            reasoning_explanation = r.get("explanation")
            median_time_months = r.get("median_time_months")
            survival_curve = list(r.get("survival_curve") or [])
            key_risk_times = list(r.get("key_risk_times") or [])
            reasoning_run_id = latest_run.id
            reasoning_iterations = r.get("iterations")

    success_probability = scenario_prob

    # ---- Pathways + milestones ----
    pathways = list(db.scalars(
        select(Pathway).where(Pathway.goal_id == goal_id)
    ))
    milestones: list[dict] = []
    for p in pathways:
        for ms in (p.milestones or [])[:5]:
            ms_dict = dict(ms) if isinstance(ms, dict) else {"label": str(ms)}
            ms_dict.setdefault("pathway", p.name)
            milestones.append(ms_dict)

    # Also fold in scenario-cached milestones (reasoning engine output).
    if latest_scenario is not None and latest_scenario.milestones:
        for ms in latest_scenario.milestones[:10]:
            ms_dict = dict(ms) if isinstance(ms, dict) else {"label": str(ms)}
            ms_dict.setdefault("source", "scenario")
            milestones.append(ms_dict)

    # ---- Recent events ----
    recent_events = list(db.scalars(
        select(Event).order_by(Event.created_at.desc()).limit(10)
    ))

    # ---- Risk heatmap (grouped by type + level) ----
    rfs = list(db.scalars(select(RiskFactor)))
    heatmap: dict[tuple[str, str], int] = {}
    for rf in rfs:
        heatmap[(rf.type, rf.level)] = heatmap.get((rf.type, rf.level), 0) + 1
    risk_heatmap = [
        {"type": t, "level": l, "count": c}
        for (t, l), c in sorted(heatmap.items())
    ]

    # ---- Active scenarios count ----
    active_count = int(
        db.scalar(
            select(Scenario)
            .where(
                Scenario.goal_id == goal_id,
                Scenario.status == ScenarioStatus.ACTIVE.value,
            )
        ) is not None
    )

    # ---- Credibility distribution ----
    from sqlalchemy import func

    rows = db.execute(
        select(InformationSource.credibility, func.count())
        .group_by(InformationSource.credibility)
    ).all()
    counts = {row[0]: row[1] for row in rows}
    total = sum(counts.values())
    private_count = db.scalar(
        select(func.count())
        .select_from(InformationSource)
        .where(InformationSource.kind == "user_upload")
    ) or 0

    credibility = CredibilityDistribution(
        high=counts.get("high", 0),
        medium=counts.get("medium", 0),
        low=counts.get("low", 0),
        pending=counts.get("pending", 0),
        user_marked_reliable=counts.get("user_marked_reliable", 0),
        user_marked_questionable=counts.get("user_marked_questionable", 0),
        total=total,
        private_share=(private_count / total) if total else 0.0,
    )

    # ---- Consecutive planning days ----
    # Count trailing days (ending today, in user's local timezone-ish UTC) on
    # which the user had ANY activity: scenario runs, notifications, or events
    # they ingested. This is the "连续规划天数" positive-progress signal.
    consecutive_planning_days = _compute_consecutive_planning_days(db, goal_id)

    return DashboardSummary(
        goal_id=goal_id,
        goal_title=goal_title,
        goal_scenario=goal_scenario,
        goal_target_date=goal_target_date,
        goal_status=goal_status,
        success_probability=success_probability,
        milestones=milestones,
        recent_events=[EventRead.model_validate(e) for e in recent_events],
        risk_heatmap=risk_heatmap,
        credibility=credibility,
        active_scenarios=active_count,
        consecutive_planning_days=consecutive_planning_days,
        regret_free_actions=regret_free_actions,
        factor_contributions=factor_contributions,
        reasoning_explanation=reasoning_explanation,
        median_time_months=median_time_months,
        survival_curve=survival_curve,
        key_risk_times=key_risk_times,
        reasoning_run_id=reasoning_run_id,
        reasoning_iterations=reasoning_iterations,
    )


def _compute_consecutive_planning_days(db: Session, goal_id: str) -> int:
    """Count the trailing streak of UTC days with any user activity.

    Activity sources (union by day):
    - ScenarioRun rows for scenarios under this goal
    - NotificationLog rows for the default user
    - Event rows (any user event counts as engagement)

    We look back up to 365 days; if today has no activity yet, the streak
    still counts starting from yesterday so users aren't penalized for the
    current day not having fired a cron yet.
    """
    from app.core.tenant import get_default_user

    try:
        user = get_default_user(db)
        user_id = user.id
    except Exception:  # noqa: BLE001
        return 0

    # Gather all relevant timestamps' UTC dates.
    horizon = datetime.now(timezone.utc) - timedelta(days=365)

    # Scenario runs under this goal (via join to scenarios).
    run_dates = {
        d.date()
        for (d,) in db.execute(
            select(ScenarioRun.started_at)
            .join(Scenario, Scenario.id == ScenarioRun.scenario_id)
            .where(Scenario.goal_id == goal_id, ScenarioRun.started_at >= horizon)
        ).all()
        if d is not None
    }

    # Notifications for this user.
    notif_dates = {
        d.date()
        for (d,) in db.execute(
            select(NotificationLog.created_at)
            .where(
                NotificationLog.user_id == user_id,
                NotificationLog.created_at >= horizon,
            )
        ).all()
        if d is not None
    }

    # Events the user ingested (any event counts as engagement).
    event_dates = {
        d.date()
        for (d,) in db.execute(
            select(Event.created_at).where(Event.created_at >= horizon)
        ).all()
        if d is not None
    }

    active_days = run_dates | notif_dates | event_dates
    if not active_days:
        return 0

    today = datetime.now(timezone.utc).date()
    # If today has no activity yet, start the streak from yesterday so a user
    # who planned yesterday still sees their streak intact this morning.
    cursor = today if today in active_days else today - timedelta(days=1)
    streak = 0
    while cursor in active_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
