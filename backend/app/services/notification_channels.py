"""Optional SMS and Web Push gateways with explicit availability status."""

from __future__ import annotations

import json
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.notification import WebPushSubscription
from app.models.user import UserProfile


class NotificationChannelService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def status(self, user_id: str | None = None) -> dict:
        sms_ready = all([
            self.settings.sms_provider == "twilio",
            self.settings.twilio_account_sid,
            self.settings.twilio_auth_token.get_secret_value(),
            self.settings.twilio_from_number,
        ])
        push_credentials = bool(
            self.settings.vapid_private_key.get_secret_value()
            and self.settings.vapid_public_key
        )
        subscriptions = 0
        if user_id:
            subscriptions = len(list(self.db.scalars(select(WebPushSubscription.id).where(
                WebPushSubscription.user_id == user_id,
                WebPushSubscription.enabled.is_(True),
            ))))
        return {
            "in_app": {"available": True, "transport": "database+sse"},
            "sms": {
                "available": sms_ready,
                "provider": self.settings.sms_provider,
                "reason": None if sms_ready else "provider_credentials_missing",
            },
            "web_push": {
                "available": push_credentials and subscriptions > 0,
                "credentials_configured": push_credentials,
                "subscriptions": subscriptions,
                "public_key": self.settings.vapid_public_key or None,
            },
        }

    def send_sms(self, user: UserProfile, title: str, body: str) -> None:
        state = self.status(user.id)["sms"]
        phone = (user.demographics or {}).get("phone")
        if not state["available"]:
            raise RuntimeError("sms_provider_not_configured")
        if not phone:
            raise RuntimeError("user_phone_not_configured")
        sid = self.settings.twilio_account_sid
        url = f"https://api.twilio.com/2010-04-01/Accounts/{quote(sid)}/Messages.json"
        response = httpx.post(
            url,
            auth=(sid, self.settings.twilio_auth_token.get_secret_value()),
            data={
                "From": self.settings.twilio_from_number,
                "To": phone,
                "Body": f"{title}\n{body}",
            },
            timeout=20,
        )
        response.raise_for_status()

    def send_web_push(self, user: UserProfile, title: str, body: str) -> int:
        try:
            from pywebpush import webpush
        except ImportError as exc:
            raise RuntimeError("pywebpush_not_installed") from exc
        if not self.status(user.id)["web_push"]["credentials_configured"]:
            raise RuntimeError("vapid_not_configured")
        subscriptions = list(self.db.scalars(select(WebPushSubscription).where(
            WebPushSubscription.user_id == user.id,
            WebPushSubscription.enabled.is_(True),
        )))
        if not subscriptions:
            raise RuntimeError("web_push_subscription_missing")
        sent = 0
        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=json.dumps({"title": title, "body": body}, ensure_ascii=False),
                    vapid_private_key=self.settings.vapid_private_key.get_secret_value(),
                    vapid_claims={"sub": self.settings.vapid_contact},
                )
                sent += 1
            except Exception:  # noqa: BLE001
                subscription.enabled = False
                self.db.add(subscription)
        self.db.flush()
        if sent == 0:
            raise RuntimeError("web_push_delivery_failed")
        return sent
