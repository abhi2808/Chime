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

    # Tagging. Relative paths resolve against the repo root, like the sqlite file.
    tag_map_path: str = "data/tag_map.yaml"

    # MusicBrainz asks for one request per second and for an application name, version
    # and contact in the User-Agent. Set MUSICBRAINZ_USER_AGENT to something contactable
    # (a repo URL or an email) before tagging a whole library.
    musicbrainz_min_request_interval_ms: int = 1100
    musicbrainz_user_agent: str = ""
    #: Lucene score a recording hit must reach before we believe it is the same song.
    musicbrainz_min_score: int = 90

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

    # The live loop (SPEC section 6). Both jobs run per *active session*, so on a personal
    # app these are a handful of requests a minute at most.
    #
    # 20 s is a compromise a snapshot poller cannot get away from: it is the resolution at
    # which "they skipped it" and "they listened to it" are told apart. Finer would measure
    # better and cost more requests; the session screen's own polling of /api/sessions/active
    # records too, so a screen that is open gets better resolution for free.
    playback_poll_seconds: int = 20
    session_poll_seconds: int = 300
    # WHOOP scores a day, not a moment, so this only has to be often enough that a recovery
    # or day_part change becomes an adaptation trigger within a session.
    whoop_poll_seconds: int = 900

    # The scheduler behind all three. Off in tests, and worth turning off in a second
    # process so two of them are not polling the same session.
    enable_scheduler: bool = True

    log_level: str = "INFO"

    # "production" turns the warnings below into a refusal to start: a Chime on the public
    # internet with an open allowlist would hand the install to whoever logs in first.
    app_env: str = "development"

    # Mounts /api/dev/*: read-only views into the engine, used to check the ranking before
    # there is a session or playback to see it through. Still behind the login.
    enable_dev_api: bool = True

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
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    def production_problems(self) -> list[str]:
        """Everything that makes this configuration unsafe to expose, in plain words.

        Checked at startup. In development it is logged; with ``APP_ENV=production`` any
        entry stops the process before it serves a request.
        """
        problems: list[str] = []
        if not self.allowed_spotify_user_id_list:
            problems.append(
                "ALLOWED_SPOTIFY_USER_IDS is empty, so the first account to log in owns this install"
            )
        if not self.encryption_key:
            problems.append("ENCRYPTION_KEY is not set")
        if not self.session_secret:
            problems.append("SESSION_SECRET is not set")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE is false, so the session cookie would travel over http")
        for name, url in (
            ("FRONTEND_ORIGIN", self.frontend_origin),
            ("SPOTIFY_REDIRECT_URI", self.spotify_redirect_uri),
            ("WHOOP_REDIRECT_URI", self.whoop_redirect_uri),
        ):
            if not url.startswith("https://"):
                problems.append(f"{name} is not https ({url})")
        if self.enable_dev_api:
            problems.append("ENABLE_DEV_API is on; /api/dev/* should not be public")
        return problems

    @property
    def musicbrainz_agent(self) -> str:
        """User-Agent for MusicBrainz, which blocks anonymous-looking clients."""
        return self.musicbrainz_user_agent.strip() or (
            "Chime/0.1 ( personal non-commercial use; set MUSICBRAINZ_USER_AGENT )"
        )

    @property
    def tag_map_file(self) -> Path:
        """Absolute path to the tag map, resolved like ``sqlalchemy_url`` does."""
        path = Path(self.tag_map_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

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
