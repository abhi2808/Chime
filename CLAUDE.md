# Chime

Personal, open-source app. One tap ("Chime in") reads WHOOP body data plus a mood check-in, builds a temporary Spotify playlist, and plays it. "Chime out" ends the session and removes the playlist unless the user keeps it. History records how each session started, what played, and how it ended.

Portfolio and personal-use project. Not a public product.

Details live in docs/ and are read on demand (open them with your file tools when a task needs them; they are deliberately not imported at launch):
- `docs/SPEC.md`: product behavior, data model, ranking, session engine, API surface
- `docs/DESIGN.md`: UI direction, tokens, screens (reference image: `docs/reference/inspiration.png`)
- `docs/PLAN.md`: phase checklist. Tick items as you finish them.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x + Alembic, httpx (async), APScheduler. Managed with uv.
- DB: SQLite file at data/chime.db by default. Keep it Postgres-compatible: all access through SQLAlchemy, URL from DATABASE_URL, no SQLite-only features.
- Frontend: React + Vite + TypeScript + Tailwind, TanStack Query, React Router. Mobile-first.
- Docker/compose come in Phase 7. Keep all config in env vars so containerizing is free.

## Commands
Keep this section current as scripts are added.
- Backend dev: `cd backend && uv run fastapi dev app/main.py --port 8000`
- Frontend dev: `cd frontend && npm run dev` (serves http://127.0.0.1:5173, proxies /api and /auth to :8000)
- Tests: `cd backend && uv run pytest`; `cd frontend && npm run typecheck && npm run lint`
- Migrations: `cd backend && uv run alembic upgrade head` (new revision: `uv run alembic revision --autogenerate -m "..."`)
- First-time install: `cd backend && uv sync`; `cd frontend && npm install`
- Frontend production build: `cd frontend && npm run build` (runs `tsc --noEmit` first)

## Hard rules: Spotify (read before writing any Spotify code)
1. Removed or blocked for our app, never call them: audio-features, audio-analysis, recommendations, related-artists, artist top-tracks, browse/featured-playlists, browse/categories, new-releases, "Get Several X" endpoints (tracks, artists, albums). Do not add fallbacks to them.
2. Playlists: create with `POST /me/playlists`; items live at `/playlists/{id}/items` (NOT `/tracks`); there is no true delete. Remove a playlist from the user's library with `DELETE /me/library`. Save/check library: `PUT /me/library`, `GET /me/library/contains`.
3. `GET /search` allows limit 1-10 (default 5). Use it to resolve a specific artist + title, not to browse.
4. Redirect URIs must be `http://127.0.0.1:<port>/...` or https. `localhost` is rejected. Always open the app at http://127.0.0.1:5173 (never localhost) or session cookies will not survive the OAuth redirect.
5. `GET /me` no longer returns `product`, `country`, `email`. We cannot detect Premium. Handle 403/PREMIUM_REQUIRED and NO_ACTIVE_DEVICE from player endpoints with clear user-facing errors.
6. Dev Mode: max 5 authorized users, one Client ID, Premium required for the app owner. Put user_id on every row, but do not build signup flows.
7. **No Spotify content in any AI/ML model.** Spotify's Developer Terms prohibit training on Spotify Content or otherwise ingesting it into an ML/AI model. So: never put track, artist, album or playlist names, IDs, genres, or the user's library into an LLM prompt, and never train or fine-tune anything on Spotify data. Track tagging is deterministic (SPEC section 5). LLM calls are allowed only on non-Spotify inputs (WHOOP-derived body state, mood, time of day), for example to write the "why this mix" sentence.
8. Verify, don't assume. Before using an endpoint, check https://developer.spotify.com/documentation/web-api and tolerate missing fields. If docs and live responses disagree with SPEC, stop and tell me.

## WHOOP facts
- API v2, base `https://api.prod.whoop.com/developer`. Scopes: `offline` (needed for refresh tokens), `read:profile`, `read:recovery`, `read:sleep`, `read:workout`, `read:cycles`, `read:body_measurement`.
- There is NO stress score and NO live heart-rate endpoint. Do not invent them. Available: cycle (day strain), recovery (score, HRV, resting HR, SpO2, skin temp), sleep, workouts (after they finish).
- Rate limit: 100 requests/min, 10,000/day. Cache and poll gently.
- Webhooks cover only recovery/sleep/workout updates and need public HTTPS. Polling is the v1 approach; write the refresh as one function a poller or a webhook can both call.

## Conventions
- Secrets only in env. OAuth tokens encrypted at rest (Fernet, key from ENCRYPTION_KEY). Never log tokens or raw WHOOP payloads. Commit `.env.example`, never `.env`.
- Backend layout: `app/{api,services,models,schemas,integrations/{spotify,whoop}}`. Routes stay thin; logic in services; integrations return typed pydantic models.
- Music source sits behind a `MusicProvider` interface (Spotify is the only implementation) so another provider could be added later.
- Every external call: timeout, retry with backoff on 429/5xx (honor Retry-After), typed errors.
- Tests: pytest + respx. No real network in tests. Every integration function gets a fixture-based test.
- Frontend: use design tokens from docs/DESIGN.md, no hardcoded colors. Respect prefers-reduced-motion. Visible keyboard focus. Sentence-case copy.
- Small commits, one task each, clear messages. Stay inside the current phase. Ask before adding a dependency that is not listed in the phase prompt.

## Working agreement
- At the start of a phase: read the prompt in prompts/, read the phase in docs/PLAN.md, propose a short plan, and wait for my OK on anything ambiguous.
- End each phase with: what changed, how to run it, what I should click to verify, and anything you were unsure about.
