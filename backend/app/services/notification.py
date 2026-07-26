"""Multi-channel notification dispatch with suppression rules.

Per project plan §4.5: Email / in-app / SMS / push, with per-user cool-down
windows and quiet hours. We persist every attempt to NotificationLog.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.redis import get_redis
from app.models.notification import NotificationLog, NotificationStatus
from app.models.user import UserProfile

log = get_logger(__name__)

# Default cool-down: same user + same risk_factor_id → no more than 1 push / 6h
COOLDOWN_SECONDS = 6 * 3600


class NotificationService:
    """Decide channel + suppress + dispatch + log."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.redis = get_redis()

    # ---------------- Public API ----------------

    def notify(
        self,
        user: UserProfile,
        *,
        title: str,
        body: str,
        severity: str = "info",
        event_id: str | None = None,
        risk_factor_id: str | None = None,
        impact_summary: dict | None = None,
        force: bool = False,
    ) -> NotificationLog | None:
        """Send a notification to the user, honoring cool-down & quiet hours."""
        if not force and self._is_suppressed(user, risk_factor_id):
            log.info("notification.suppressed", user_id=user.id, title=title)
            return self._log(
                user,
                channel="in_app",
                status=NotificationStatus.SUPPRESSED.value,
                title=title,
                body=body,
                severity=severity,
                event_id=event_id,
                risk_factor_id=risk_factor_id,
                impact_summary=impact_summary or {},
            )

        channel = self._pick_channel(user, severity)
        try:
            if channel == "email":
                self._send_email(user, title, body)
            elif channel == "sms":
                # MVP: stub SMS gateway
                log.info("notification.sms_stub", user_id=user.id)
            # in_app / push: stored, frontend polls
        except Exception as exc:  # noqa: BLE001
            log.error("notification.dispatch_failed", error=str(exc), channel=channel)
            return self._log(
                user,
                channel=channel,
                status=NotificationStatus.FAILED.value,
                title=title,
                body=body,
                severity=severity,
                event_id=event_id,
                risk_factor_id=risk_factor_id,
                impact_summary=impact_summary or {},
            )

        return self._log(
            user,
            channel=channel,
            status=NotificationStatus.SENT.value,
            title=title,
            body=body,
            severity=severity,
            event_id=event_id,
            risk_factor_id=risk_factor_id,
            impact_summary=impact_summary or {},
            sent_at=datetime.now(timezone.utc),
        )

    # ---------------- Channel selection ----------------

    def _pick_channel(self, user: UserProfile, severity: str) -> str:
        prefs = user.notify_channels or {"in_app": True}
        if severity == "critical" and prefs.get("sms"):
            return "sms"
        if prefs.get("email"):
            return "email"
        return "in_app"

    # ---------------- Suppression ----------------

    def _is_suppressed(self, user: UserProfile, risk_factor_id: str | None) -> bool:
        if risk_factor_id is None:
            return False
        if self._in_quiet_hours(user):
            return True
        key = f"notif:cooldown:{user.id}:{risk_factor_id}"
        # setnx returns 1 if the key was newly set
        acquired = self.redis.set(key, "1", ex=COOLDOWN_SECONDS, nx=True)
        return not bool(acquired)

    def _in_quiet_hours(self, user: UserProfile) -> bool:
        qh = user.quiet_hours or {}
        if not qh:
            return False
        try:
            start = int(qh.get("start", "22"))
            end = int(qh.get("end", "07"))
            hour = datetime.now(timezone.utc).hour
            if start <= end:
                return start <= hour < end
            return hour >= start or hour < end
        except (TypeError, ValueError):
            return False

    # ---------------- Email ----------------

    def _send_email(self, user: UserProfile, title: str, body: str) -> None:
        """Send a risk-warning email via the SMTP server configured in LLMConfig.

        SMTP settings live in ``.llm_config.json`` (hot-reloadable via
        ``PUT /settings/smtp``) so users can update them without a process
        restart. We read the live config on every send rather than caching.
        Falls back to legacy env-var settings (``Settings.smtp_*``) only if
        the LLMConfig SMTP block is empty — this preserves backward
        compatibility for deployments that already configured SMTP via .env.
        """
        if not user.email:
            raise RuntimeError("user has no email address")

        # Live-read from LLMConfig (hot-reloadable).
        from app.llm.registry import get_smtp_config

        smtp = get_smtp_config()
        host = smtp["host"] or self.settings.smtp_host
        if not host:
            log.info("notification.email_skipped_no_smtp", user_id=user.id)
            return

        port = smtp["port"] if smtp["host"] else self.settings.smtp_port
        smtp_user = smtp["user"] if smtp["host"] else self.settings.smtp_user
        # LLMConfig stores plaintext; legacy Settings stores SecretStr.
        if smtp["host"]:
            smtp_password = smtp["password"]
        else:
            smtp_password = self.settings.smtp_password.get_secret_value()
        from_addr = smtp["from"] if smtp["host"] else self.settings.smtp_from
        use_tls = smtp["use_tls"] if smtp["host"] else True

        msg = MIMEText(body)
        msg["Subject"] = f"[LifeTree] {title}"
        msg["From"] = from_addr
        msg["To"] = user.email

        try:
            with smtplib.SMTP(host, port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, [user.email], msg.as_string())
        except (smtplib.SMTPException, OSError) as exc:
            log.error(
                "notification.email_send_failed",
                user_id=user.id,
                host=host,
                port=port,
                error=str(exc),
            )
            raise

    # ---------------- Log persistence ----------------

    def _log(
        self,
        user: UserProfile,
        *,
        channel: str,
        status: str,
        title: str,
        body: str,
        severity: str,
        event_id: str | None,
        risk_factor_id: str | None,
        impact_summary: dict,
        sent_at: datetime | None = None,
    ) -> NotificationLog:
        record = NotificationLog(
            user_id=user.id,
            channel=channel,
            status=status,
            severity=severity,
            title=title,
            body=body,
            event_id=event_id,
            risk_factor_id=risk_factor_id,
            impact_summary=impact_summary,
            sent_at=sent_at,
        )
        self.db.add(record)
        self.db.commit()
        return record

    # ---------------- Reader ----------------

    def list_recent(self, user_id: str, limit: int = 50) -> list[NotificationLog]:
        return list(
            self.db.scalars(
                select(NotificationLog)
                .where(NotificationLog.user_id == user_id)
                .order_by(NotificationLog.created_at.desc())
                .limit(limit)
            )
        )

    def mark_read(self, notification_id: str, user_id: str) -> NotificationLog | None:
        record = self.db.get(NotificationLog, notification_id)
        if record is None or record.user_id != user_id:
            return None
        record.status = NotificationStatus.READ.value
        record.read_at = datetime.now(timezone.utc)
        self.db.commit()
        return record
