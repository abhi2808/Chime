# Chime

One tap ("Chime in") reads WHOOP body data plus a mood check-in, builds a temporary Spotify
playlist, and plays it. "Chime out" ends the session and removes the playlist unless you keep
it. History records how each session started, what played, and how it ended.

Personal, open-source, portfolio project. Not a public product. Product behavior lives in
[docs/SPEC.md](docs/SPEC.md), UI direction in [docs/DESIGN.md](docs/DESIGN.md), and the phase
checklist in [docs/PLAN.md](docs/PLAN.md).

**What exists today (Phases 1–7):** Spotify login and liked-songs sync, WHOOP body data,
deterministic tagging from MusicBrainz and ranking, Chime in / Chime out with a real
playlist on a real device, History, the live loop (skip capture, adaptation, WHOOP refresh),
and Docker images with a deployment guide in [docs/DEPLOY.md](docs/DEPLOY.md). Phase 8
(discovery, a fuller Insights tab, other providers) is optional and not started.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node 20+
- A Spotify account with Premium (playback in later phases needs it)

## 1. Create the Spotify app

1. Go to https://developer.spotify.com/dashboard and create an app.
2. Add this redirect URI **exactly**:

   ```
   http://127.0.0.1:5173/auth/spotify/callback
   ```

   Spotify rejects `localhost`, so the literal `127.0.0.1` matters. The URI points at the Vite
   dev server, which proxies `/auth` to the backend, so the whole OAuth round trip stays on one
   origin and the session cookie survives it.
3. Under APIs, tick **Web API** (and Web Playback SDK if you plan to follow later phases).
4. Copy the **Client ID**. Chime uses Authorization Code with PKCE, so there is **no client
   secret** to copy.
5. The app starts in Development Mode: up to 5 users, each added by hand under
   Settings → User Management.

## 2. Configure

```bash
cp .env.example .env
```

Fill in:

- `SPOTIFY_CLIENT_ID` — from the dashboard.
- `ENCRYPTION_KEY` — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `SESSION_SECRET` — `python -c "import secrets; print(secrets.token_urlsafe(48))"`

The defaults for `SPOTIFY_REDIRECT_URI`, `DATABASE_URL`, `FRONTEND_ORIGIN` and
`ALLOWED_SPOTIFY_USER_IDS` are fine for local use. Leaving `ALLOWED_SPOTIFY_USER_IDS` empty
means the first account to log in becomes the owner and every other account is refused.

## 3. Install and migrate

```bash
cd backend && uv sync && uv run alembic upgrade head
cd ../frontend && npm install
```

The database file lands at `data/chime.db` (gitignored) no matter which folder you run from.

## 4. Run

Two terminals:

```bash
cd backend && uv run fastapi dev app/main.py --port 8000
cd frontend && npm run dev
```

Open **http://127.0.0.1:5173** — not `localhost`, or the login cookie will not come back with
the OAuth redirect.

## 5. Sign in

Press "Continue with Spotify", approve the scopes, and you land on Home. The liked-songs sync
starts automatically after the first login; the Library card shows songs going in and then
artists being fetched. Re-running a sync stops at the first liked song it already knows about;
"Sync again" walks the whole library.

## Checks

```bash
cd backend && uv run pytest
cd frontend && npm run typecheck && npm run lint
```

Tests use `respx`, so nothing touches the network.

## Layout

```
backend/   FastAPI app (api, services, models, integrations/{spotify,whoop,musicbrainz}),
           Alembic migrations, maintenance scripts, tests
frontend/  Vite + React + TypeScript + Tailwind, mobile-first
data/      tag_map.yaml (committed) and the SQLite database file (gitignored)
deploy/    Caddyfile for the web container
docs/      SPEC, DESIGN (+ design/ mockups), PLAN, DEPLOY
prompts/   The phase prompts used to build each phase
```

## Docker

```bash
HTTP_PORT=5173 docker compose up -d --build   # then open http://127.0.0.1:5173
```

Production on EC2 with HTTPS, the allowlist and backups: [docs/DEPLOY.md](docs/DEPLOY.md).

## Notes

- Secrets live only in `.env`. OAuth tokens are encrypted at rest with Fernet, and tokens are
  never logged.
- Two Spotify fields this project deliberately works around: `GET /me` no longer returns
  `product`, so Premium cannot be detected up front, and Spotify now sends no artist
  `genres` at all, so every tag comes from MusicBrainz (SPEC section 5).
- Spotify content (track, artist, album or playlist names, ids, genres, your library) never
  goes into an LLM prompt, per Spotify's Developer Terms.
