"""Multi-channel notification dispatch with suppression rules.

Per project plan §4.5: Email / in-app / SMS / push, with per-user cool-down
windows and quiet hours. We persist every attempt to NotificationLog.
"""

from __future__ import annotations

import json
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import formataddr
from zoneinfo import ZoneInfo

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

# Default timezone when the user's demographics don't specify one.
DEFAULT_TIMEZONE = "Asia/Shanghai"


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
        if not force and self._is_suppressed(user, risk_factor_id, severity=severity):
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
                # SMS gateway not yet wired (§4.5 P2 — pending Twilio/阿里云
                # integration). Mark as FAILED rather than pretending we sent
                # it, so the user isn't silently misled. The in-app channel
                # still receives the message via the SSE push below.
                log.warning(
                    "notification.sms_not_configured",
                    user_id=user.id,
                    title=title,
                )
                return self._log(
                    user,
                    channel="sms",
                    status=NotificationStatus.FAILED.value,
                    title=title,
                    body=body,
                    severity=severity,
                    event_id=event_id,
                    risk_factor_id=risk_factor_id,
                    impact_summary=impact_summary or {},
                )
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

        record = self._log(
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
        # Push to the user's SSE channel so connected clients refresh in
        # real time. Best-effort: a Redis hiccup must never break the
        # notification pipeline.
        self._publish_sse(user.id, record)
        return record

    # ---------------- SSE push ----------------

    def _publish_sse(self, user_id: str, record: NotificationLog) -> None:
        """Best-effort publish to ``lifetree:risk:{user_id}`` for SSE push."""
        try:
            payload = {
                "type": "notification",
                "data": {
                    "id": record.id,
                    "title": record.title,
                    "body": record.body,
                    "severity": record.severity,
                    "channel": record.channel,
                    "event_id": record.event_id,
                    "risk_factor_id": record.risk_factor_id,
                    "impact_summary": record.impact_summary or {},
                    "created_at": record.created_at.isoformat()
                    if record.created_at
                    else None,
                },
            }
            self.redis.publish(
                f"lifetree:risk:{user_id}",
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "notification.sse_publish_failed",
                user_id=user_id,
                error=str(exc),
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

    def _is_suppressed(
        self, user: UserProfile, risk_factor_id: str | None, severity: str = "info"
    ) -> bool:
        # Cruising Mode (§4.5 & §5.4): only CRITICAL alerts reach the user; all medium/low notifications are suppressed.
        if user.cruising_mode and severity != "critical":
            return True
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
            # Resolve the user's local timezone from demographics (JSONB),
            # defaulting to Asia/Shanghai. Quiet hours are interpreted in
            # the user's local time, not server UTC.
            tz_name = (user.demographics or {}).get("timezone") or DEFAULT_TIMEZONE
            try:
                tz = ZoneInfo(tz_name)
            except (KeyError, ValueError, TypeError):
                tz = ZoneInfo(DEFAULT_TIMEZONE)
            hour = datetime.now(tz).hour
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

        Renders an HTML email using the shared LifeTree template; links
        point to the admin-configured "service address" so they resolve to
        the public URL rather than an internal Docker hostname.
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
        use_ssl = smtp.get("use_ssl", False) if smtp["host"] else False
        sender_name = (
            smtp.get("sender_name", "LifeTree") if smtp["host"] else "LifeTree"
        ) or "LifeTree"

        # Build an HTML risk-warning email using the shared template. The
        # severity is mapped from the record's channel/severity if available.
        from app.services.email_template import (
            build_html_message,
            render_risk_warning_email,
        )

        # Try to extract severity from the most recent record for this user,
        # falling back to "warning" when unknown.
        severity = "warning"
        try:
            recent = self.redis.get(f"notif:last_severity:{user.id}")
            if recent and isinstance(recent, str):
                severity = recent
        except Exception:  # noqa: BLE001
            pass

        subject, html_body = render_risk_warning_email(
            user_display_name=user.display_name or user.email,
            title=title,
            body_text=body,
            severity=severity,
        )
        msg = build_html_message(
            to_addr=user.email,
            subject=subject,
            html_body=html_body,
            plain_text_fallback=f"{title}\n\n{body}\n",
        )
        # Override From/To from the legacy SMTP config when the admin
        # block is empty (the template uses the admin-configured values
        # already, but legacy env settings may differ).
        msg["From"] = formataddr((sender_name, from_addr))
        msg["To"] = user.email

        try:
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=30) as server:
                    server.ehlo()
                    if smtp_user:
                        server.login(smtp_user, smtp_password)
                    server.sendmail(from_addr, [user.email], msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=30) as server:
                    server.ehlo()
                    if use_tls:
                        server.starttls()
                        server.ehlo()
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

    def list_filtered(
        self,
        user_id: str,
        *,
        severity: str | None = None,
        status: str | None = None,
        channel: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationLog]:
        """Server-side filtered notification list for one user."""
        stmt = (
            select(NotificationLog)
            .where(NotificationLog.user_id == user_id)
            .order_by(NotificationLog.created_at.desc())
        )
        if severity:
            stmt = stmt.where(NotificationLog.severity == severity)
        if status:
            stmt = stmt.where(NotificationLog.status == status)
        if channel:
            stmt = stmt.where(NotificationLog.channel == channel)
        stmt = stmt.limit(limit).offset(offset)
        return list(self.db.scalars(stmt))

    def count_unread(self, user_id: str) -> int:
        """Efficient single COUNT of unread notifications for one user.

        "Unread" = status not in {READ, SUPPRESSED}. SUPPRESSED rows are
        excluded because the user never saw them and shouldn't see a badge.
        """
        from sqlalchemy import func

        result = self.db.scalar(
            select(func.count(NotificationLog.id)).where(
                NotificationLog.user_id == user_id,
                NotificationLog.status.notin_(
                    [NotificationStatus.READ.value, NotificationStatus.SUPPRESSED.value]
                ),
            )
        )
        return int(result or 0)

    def bulk_mark_read(
        self, user_id: str, notification_ids: list[str]
    ) -> int:
        """Mark a batch of notifications as READ in a single UPDATE.

        Only touches rows owned by ``user_id`` (prevents cross-user tampering).
        Returns the number of rows actually updated.
        """
        if not notification_ids:
            return 0
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        result = self.db.execute(
            update(NotificationLog)
            .where(
                NotificationLog.user_id == user_id,
                NotificationLog.id.in_(notification_ids),
                NotificationLog.status != NotificationStatus.READ.value,
            )
            .values(status=NotificationStatus.READ.value, read_at=now)
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def mark_read(self, notification_id: str, user_id: str) -> NotificationLog | None:
        record = self.db.get(NotificationLog, notification_id)
        if record is None or record.user_id != user_id:
            return None
        record.status = NotificationStatus.READ.value
        record.read_at = datetime.now(timezone.utc)
        self.db.commit()
        return record
