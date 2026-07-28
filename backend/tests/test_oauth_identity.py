from types import SimpleNamespace

from app.services import oauth_identity


def provider(name: str = "GitHub") -> SimpleNamespace:
    return SimpleNamespace(
        id="o_123",
        name=name,
        client_id="client",
        client_secret="secret",
        token_url="https://example.test/token",
        userinfo_url="https://api.github.com/user",
        redirect_uri="http://localhost/auth/callback/github",
    )


def test_normalize_common_and_nested_profile_fields() -> None:
    identity = oauth_identity.normalize_oauth_userinfo(
        provider("Facebook"),
        {
            "id": "42",
            "mail": "USER@example.com",
            "display_name": "Example User",
            "picture": {"data": {"url": "https://img.test/avatar.png"}},
        },
    )

    assert identity.external_sub == "42"
    assert identity.email == "user@example.com"
    assert identity.display_name == "Example User"
    assert identity.avatar_url == "https://img.test/avatar.png"


def test_normalize_discord_avatar_hash() -> None:
    identity = oauth_identity.normalize_oauth_userinfo(
        provider("Discord"),
        {"id": "7", "username": "cary", "avatar": "hash"},
    )

    assert identity.avatar_url == "https://cdn.discordapp.com/avatars/7/hash.png"


def test_github_private_email_is_fetched(monkeypatch) -> None:
    requested_urls: list[str] = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self.payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **_kwargs):
            return Response({"access_token": "provider-token"})

        def get(self, url, **_kwargs):
            requested_urls.append(url)
            if url.endswith("/emails"):
                return Response(
                    [{"email": "private@example.com", "primary": True, "verified": True}]
                )
            return Response({"id": 99, "login": "private-user", "avatar_url": "avatar"})

    monkeypatch.setattr(oauth_identity.httpx, "Client", Client)

    identity = oauth_identity.exchange_oauth_identity(provider(), "code")

    assert requested_urls == ["https://api.github.com/user", "https://api.github.com/user/emails"]
    assert identity.email == "private@example.com"
    assert identity.avatar_url == "avatar"
