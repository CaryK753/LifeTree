"""Celery tasks for calibration and action automation."""

from __future__ import annotations

from sqlalchemy import select

from app.db.postgres import get_session
from app.models.goal import Goal, Pathway
from app.models.scenario import Scenario
from app.models.user import UserProfile
from app.services.action_scheduler import ActionScheduler
from app.services.calibration_monitor import CalibrationMonitor
from app.services.evolution import EvolutionService
from app.services.evolution_feedback import EvolutionFeedbackService
from app.services.risk_discovery import RiskDiscoveryService
from app.services.risk_proposals import RiskProposalService
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.intelligence_tasks.calibrate_model_params")
def calibrate_model_params() -> dict:
    db = get_session()
    try:
        reports = CalibrationMonitor(db).run_all_scopes()
        return {
            "status": "ok",
            "reports": len(reports),
            "calibrated": sum(int(report.calibrated) for report in reports),
            "drifted": sum(int(report.drift_detected) for report in reports),
        }
    finally:
        db.close()


@celery_app.task(name="app.workers.intelligence_tasks.materialize_recurring_actions")
def materialize_recurring_actions() -> dict:
    db = get_session()
    try:
        user_ids = list(db.scalars(select(UserProfile.id).where(UserProfile.is_enabled.is_(True))))
        service = ActionScheduler(db)
        created = sum(service.materialize_for_user(user_id) for user_id in user_ids)
        return {"status": "ok", "users": len(user_ids), "created": created}
    finally:
        db.close()


@celery_app.task(name="app.workers.intelligence_tasks.send_action_reminders")
def send_action_reminders() -> dict:
    db = get_session()
    try:
        sent = ActionScheduler(db).send_due_reminders()
        return {"status": "ok", "sent": sent}
    finally:
        db.close()


@celery_app.task(name="app.workers.intelligence_tasks.discover_emerging_risks")
def discover_emerging_risks() -> dict:
    import asyncio

    db = get_session()
    try:
        user_ids = list(db.scalars(select(UserProfile.id).where(UserProfile.is_enabled.is_(True))))
        proposed = 0
        for user_id in user_ids:
            candidates = asyncio.run(
                RiskDiscoveryService(db).discover_emerging_risks(user_id)
            )
            proposed += len(RiskProposalService(db, user_id).persist(candidates))
        return {"status": "ok", "users": len(user_ids), "proposals": proposed}
    finally:
        db.close()


@celery_app.task(name="app.workers.intelligence_tasks.evolve_all_active_scenarios")
def evolve_all_active_scenarios() -> dict:
    db = get_session()
    try:
        scenarios = list(db.scalars(
            select(Scenario).where(Scenario.status.in_(["active", "draft"]))
        ))
        completed = 0
        failed = 0
        for scenario in scenarios:
            goal = db.get(Goal, scenario.goal_id)
            if goal is None:
                continue
            user = type("WorkerUser", (), {"id": goal.user_id, "role": "user"})()
            try:
                # v0.4.0：通过 scenario 解析关联 Pathway，再调用 evolve(pathway)
                from app.services.scenario_pathway import resolve_scenario_pathway

                pathway = None
                if scenario.pathway_id:
                    pathway = db.get(Pathway, scenario.pathway_id)
                if pathway is None:
                    pathway = resolve_scenario_pathway(db, scenario)
                if pathway is None:
                    failed += 1
                    continue
                EvolutionService(db).evolve(pathway, user)
                completed += 1
            except Exception:  # noqa: BLE001
                failed += 1
        return {"status": "ok", "completed": completed, "failed": failed}
    finally:
        db.close()


@celery_app.task(name="app.workers.intelligence_tasks.compare_evolution_milestones")
def compare_evolution_milestones() -> dict:
    db = get_session()
    try:
        return {"status": "ok", **EvolutionFeedbackService(db).compare_due()}
    finally:
        db.close()
