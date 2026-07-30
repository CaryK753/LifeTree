"""Recurring action materialization, reminders, metrics, and ICS export."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.action import Action
from app.models.user import UserProfile
from app.services.notification import NotificationService

ACTIVE_STATUSES = ("pending", "in_progress", "deferred")


class ActionScheduler:
    def __init__(self, db: Session) -> None:
        self.db = db

    def materialize_for_user(self, user_id: str, horizon_days: int = 35) -> int:
        user = self.db.get(UserProfile, user_id)
        today = self._local_today(user)
        horizon = today + timedelta(days=horizon_days)
        templates = list(self.db.scalars(select(Action).where(
            Action.user_id == user_id,
            Action.deleted_at.is_(None),
            Action.recurrence.in_(["daily", "weekly", "monthly"]),
            Action.recurrence_parent_id.is_(None),
            Action.due_at.isnot(None),
        )))
        created = 0
        for template in templates:
            due = self._next_date(template.due_at, template.recurrence)
            while due <= horizon:
                if due >= today:
                    created += int(self._create_occurrence(template, due))
                due = self._next_date(due, template.recurrence)
        self.db.commit()
        return created

    def send_due_reminders(self, user_id: str | None = None) -> int:
        stmt = (
            select(Action)
            .where(
                Action.deleted_at.is_(None),
                Action.status.in_(ACTIVE_STATUSES),
                Action.due_at.isnot(None),
                Action.reminder_sent_at.is_(None),
            )
            .order_by(Action.user_id, Action.due_at)
        )
        if user_id:
            stmt = stmt.where(Action.user_id == user_id)
        sent = 0
        for action in self.db.scalars(stmt):
            user = self.db.get(UserProfile, action.user_id)
            if user is None or action.due_at > self._local_today(user):
                continue
            record = NotificationService(self.db).notify(
                user,
                title="行动任务到期提醒",
                body=f"「{action.title}」计划于 {action.due_at.isoformat()} 完成。",
                severity="warning" if action.due_at < self._local_today(user) else "info",
                risk_factor_id=f"action_due:{action.id}:{action.due_at.isoformat()}",
                impact_summary={"action_id": action.id, "goal_id": action.goal_id},
            )
            if record is not None and record.status != "failed":
                action.reminder_sent_at = datetime.now(UTC)
                self.db.add(action)
                sent += 1
        self.db.commit()
        return sent

    def refresh_completion_metrics(self, user_id: str) -> dict[str, float | int]:
        total = int(self.db.scalar(select(func.count(Action.id)).where(
            Action.user_id == user_id, Action.deleted_at.is_(None)
        )) or 0)
        completed = int(self.db.scalar(select(func.count(Action.id)).where(
            Action.user_id == user_id,
            Action.deleted_at.is_(None),
            Action.status == "completed",
        )) or 0)
        metrics = {
            "total": total,
            "completed": completed,
            "completion_rate": round(completed / total, 4) if total else 0.0,
        }
        user = self.db.get(UserProfile, user_id)
        if user is not None:
            progress = dict(user.progress or {})
            progress["action_metrics"] = metrics
            user.progress = progress
            self.db.add(user)
            self.db.commit()
        return metrics

    def export_ics(self, user_id: str) -> str:
        actions = list(self.db.scalars(
            select(Action).where(
                Action.user_id == user_id,
                Action.deleted_at.is_(None),
                Action.due_at.isnot(None),
            ).order_by(Action.due_at, Action.created_at)
        ))
        lines = [
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LifeTree//Action Calendar//CN",
            "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        ]
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        for action in actions:
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{action.id}@lifetree.local",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{action.due_at.strftime('%Y%m%d')}",
                f"SUMMARY:{self._ics_escape(action.title)}",
                f"DESCRIPTION:{self._ics_escape(action.description or '')}",
                f"STATUS:{'COMPLETED' if action.status == 'completed' else 'NEEDS-ACTION'}",
                "END:VEVENT",
            ])
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"

    def _create_occurrence(self, template: Action, due: date) -> bool:
        key = f"{template.id}:{due.isoformat()}"
        if self.db.scalar(select(Action.id).where(Action.occurrence_key == key)):
            return False
        meta = dict(template.meta or {})
        meta["recurrence_template_id"] = template.id
        self.db.add(Action(
            user_id=template.user_id,
            goal_id=template.goal_id,
            scenario_id=template.scenario_id,
            pathway_id=template.pathway_id,
            requirement_id=template.requirement_id,
            risk_factor_id=template.risk_factor_id,
            title=template.title,
            description=template.description,
            stage=template.stage,
            due_at=due,
            recurrence="",
            recurrence_parent_id=template.id,
            occurrence_key=key,
            cost=template.cost,
            expected_prob_lift=template.expected_prob_lift,
            source=template.source,
            source_run_id=template.source_run_id,
            meta=meta,
        ))
        self.db.flush()
        return True

    @staticmethod
    def _next_date(current: date, recurrence: str) -> date:
        if recurrence == "daily":
            return current + timedelta(days=1)
        if recurrence == "weekly":
            return current + timedelta(days=7)
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        return date(year, month, min(current.day, calendar.monthrange(year, month)[1]))

    @staticmethod
    def _local_today(user: UserProfile | None) -> date:
        name = ((user.demographics or {}).get("timezone") if user else None) or "Asia/Shanghai"
        try:
            return datetime.now(ZoneInfo(name)).date()
        except (KeyError, ValueError, TypeError):
            return datetime.now(ZoneInfo("Asia/Shanghai")).date()

    @staticmethod
    def _ics_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
