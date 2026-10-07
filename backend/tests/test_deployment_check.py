"""APP_ENV=production refuses an install that is not locked down."""

from __future__ import annotations

import pytest

from app import main
from app.core.config import Settings


def _locked_down(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "allowed_spotify_user_ids": "owner123",
        "encryption_key": "k",
        "session_secret": "s",
        "cookie_secure": True,
        "frontend_origin": "https://chime.example.com",
        "spotify_redirect_uri": "https://chime.example.com/auth/spotify/callback",
        "whoop_redirect_uri": "https://chime.example.com/auth/whoop/callback",
        "enable_dev_api": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_locked_down_configuration_has_no_problems() -> None:
    assert _locked_down().production_problems() == []


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"allowed_spotify_user_ids": ""}, "ALLOWED_SPOTIFY_USER_IDS"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"spotify_redirect_uri": "http://127.0.0.1:5173/auth/spotify/callback"}, "SPOTIFY_REDIRECT_URI"),
        ({"frontend_origin": "http://chime.example.com"}, "FRONTEND_ORIGIN"),
        ({"encryption_key": ""}, "ENCRYPTION_KEY"),
        ({"enable_dev_api": True}, "ENABLE_DEV_API"),
    ],
)
def test_each_gap_is_named(override: dict, fragment: str) -> None:
    problems = _locked_down(**override).production_problems()
    assert len(problems) == 1
    assert fragment in problems[0]


def test_production_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", _locked_down(allowed_spotify_user_ids=""))
    with pytest.raises(main.UnsafeConfiguration, match="ALLOWED_SPOTIFY_USER_IDS"):
        main.check_deployment()


def test_development_only_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", _locked_down(app_env="development", cookie_secure=False))
    main.check_deployment()  # does not raise
