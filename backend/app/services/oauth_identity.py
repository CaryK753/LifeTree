"""OAuth token exchange and provider user-info normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class OAuthProviderLike(Protocol):
    id: str
    name: str
    client_id: str
    client_secret: str
    token_url: str
    userinfo_url: str
    redirect_uri: str


class OAuthIdentityError(Exception):
    """Raised when an OAuth provider exchange or user-info request fails."""


@dataclass(frozen=True)
class OAuthIdentity:
    external_sub: str
    email: str
    display_name: str
    avatar_url: str | None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_oauth_userinfo(
    provider: OAuthProviderLike,
    payload: dict[str, Any],
    *,
    fallback_email: str = "",
) -> OAuthIdentity:
    """Map common OAuth/OIDC response shapes to LifeTree's user fields."""
    nested = payload.get("data")
    if isinstance(nested, dict) and not any(k in payload for k in ("id", "sub", "email")):
        payload = nested

    external_sub = _text(payload.get("sub") or payload.get("id") or payload.get("user_id"))
    email = _text(
        payload.get("email")
        or payload.get("emailAddress")
        or payload.get("mail")
        or fallback_email
    )
    if not email:
        preferred_username = _text(payload.get("preferred_username"))
        if "@" in preferred_username:
            email = preferred_username

    display_name = _text(
        payload.get("name")
        or payload.get("display_name")
        or payload.get("login")
        or payload.get("username")
        or payload.get("nickname")
    )
    if not display_name:
        display_name = email.split("@", 1)[0] if email else "user"

    picture = payload.get("picture")
    if isinstance(picture, dict):
        picture_data = picture.get("data")
        picture = picture_data.get("url") if isinstance(picture_data, dict) else picture.get("url")
    avatar_url = _text(
        payload.get("avatar_url")
        or payload.get("avatarUrl")
        or payload.get("profile_image_url")
        or picture
    ) or None

    provider_key = f"{provider.id} {provider.name}".lower()
    if not avatar_url and "discord" in provider_key and external_sub and payload.get("avatar"):
        avatar_hash = _text(payload["avatar"])
        avatar_url = f"https://cdn.discordapp.com/avatars/{external_sub}/{avatar_hash}.png"

    return OAuthIdentity(
        external_sub=external_sub,
        email=email.lower(),
        display_name=display_name[:128],
        avatar_url=avatar_url,
    )


def exchange_oauth_identity(provider: OAuthProviderLike, code: str) -> OAuthIdentity:
    """Exchange an authorization code and return normalized identity data."""
    token_payload = {
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code": code,
        "redirect_uri": provider.redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        with httpx.Client(timeout=15) as client:
            token_response = client.post(
                provider.token_url,
                data=token_payload,
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise OAuthIdentityError("OAuth token endpoint returned no access_token")

            headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
            userinfo_response = client.get(provider.userinfo_url, headers=headers)
            userinfo_response.raise_for_status()
            userinfo = userinfo_response.json()
            if not isinstance(userinfo, dict):
                raise OAuthIdentityError("OAuth userinfo endpoint returned a non-object response")

            fallback_email = ""
            provider_key = f"{provider.id} {provider.name} {provider.userinfo_url}".lower()
            if not userinfo.get("email") and "github" in provider_key:
                emails_response = client.get(
                    f"{provider.userinfo_url.rstrip('/')}/emails",
                    headers=headers,
                )
                emails_response.raise_for_status()
                emails = emails_response.json()
                if isinstance(emails, list):
                    preferred = next(
                        (item for item in emails if item.get("primary") and item.get("verified")),
                        None,
                    ) or next((item for item in emails if item.get("verified")), None)
                    if preferred:
                        fallback_email = _text(preferred.get("email"))
    except OAuthIdentityError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise OAuthIdentityError(str(exc)) from exc

    return normalize_oauth_userinfo(provider, userinfo, fallback_email=fallback_email)


__all__ = [
    "OAuthIdentity",
    "OAuthIdentityError",
    "exchange_oauth_identity",
    "normalize_oauth_userinfo",
]
