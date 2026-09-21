"""Application settings, read from the environment (and a repo-root .env)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../backend/app/core/config.py -> core, app, backend, repo root
BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Spotify
    spotify_client_id: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:5173/auth/spotify/callback"

    # WHOOP. Not PKCE: WHOOP requires a client secret.
    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "http://127.0.0.1:5173/auth/whoop/callback"

    # Secrets
    encryption_key: str = ""
    session_secret: str = ""

    # Storage
    database_url: str = "sqlite:///data/chime.db"

    # Access
    allowed_spotify_user_ids: str = ""
    frontend_origin: str = "http://127.0.0.1:5173"

    # Cookies
    session_cookie_name: str = "chime_session"
    oauth_cookie_name: str = "chime_oauth"
    session_ttl_seconds: int = 60 * 60 * 24 * 30
    oauth_ttl_seconds: int = 600
    cookie_secure: bool = False

    # Outbound HTTP
    http_timeout_seconds: float = 10.0
    http_max_retries: int = 3

    # Library sync
    liked_page_limit: int = 50
    artist_fetch_concurrency: int = 2

    # Spotify's rate limit is a rolling window per app, so a burst of artist fetches is
    # what trips it. Spacing calls ~6/s walks a 1,000 artist library in under 3 minutes
    # without bursting.
    spotify_min_request_interval_ms: int = 160

    # A 429 asking us to wait longer than this is a penalty, not a hiccup: stop the run
    # and resume later rather than holding a request open.
    rate_limit_sleep_ceiling_seconds: float = 10.0

    # Wall-clock budget for the artist phase. Whatever is tagged by then is kept, and
    # the remaining artists are picked up on the next sync.
    artist_phase_budget_seconds: float = 300.0

    # WHOOP allows 100 requests/min and 10,000/day. A day's refresh is a handful of
    # calls, so this is politeness rather than a real constraint.
    whoop_min_request_interval_ms: int = 250

    # How stale cached WHOOP data may be before a read refreshes it (SPEC section 6).
    # Recovery lands once a day and strain creeps up hourly, so minutes are plenty.
    body_state_ttl_seconds: int = 600

    # How far back a refresh looks. Two days covers "yesterday's cycle is still open
    # because I have not woken up yet" without pulling history we do not use.
    whoop_lookback_hours: int = 48

    log_level: str = "INFO"

    @property
    def allowed_spotify_user_id_list(self) -> list[str]:
        return [part.strip() for part in self.allowed_spotify_user_ids.split(",") if part.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """Resolve relative sqlite paths against the repo root so the db file is stable.

        Keeps DATABASE_URL readable (``sqlite:///data/chime.db``) while the dev server
        runs from ``backend/``. Any other driver URL is passed through untouched.
        """
        url = self.database_url
        prefix = "sqlite:///"
        if url.startswith(prefix) and not url.startswith(prefix + "/"):
            target = url[len(prefix) :]
            if target and target != ":memory:" and not Path(target).is_absolute():
                return prefix + (PROJECT_ROOT / target).as_posix()
        return url

    @property
    def sqlite_path(self) -> Path | None:
        url = self.sqlalchemy_url
        prefix = "sqlite:///"
        if url.startswith(prefix):
            target = url[len(prefix) :]
            if target and target != ":memory:":
                return Path(target)
        return None


settings = Settings()
