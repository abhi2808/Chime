# Chime

Personal, open-source app. One tap ("Chime in") reads WHOOP body data plus a mood check-in, builds a temporary Spotify playlist, and plays it. "Chime out" ends the session and removes the playlist unless the user keeps it. History records how each session started, what played, and how it ended.

Portfolio and personal-use project. Not a public product.

Details live in docs/ and are read on demand (open them with your file tools when a task needs them; they are deliberately not imported at launch):
- `docs/SPEC.md`: product behavior, data model, ranking, session engine, API surface
- `docs/DESIGN.md`: UI direction, tokens, screens (reference image: `docs/reference/inspiration.png`)
- `docs/PLAN.md`: phase checklist. Tick items as you finish them.
- `docs/design/`: the approved Claude Design mockups for Home and Session; they win over DESIGN.md where they differ
- `docs/DEPLOY.md`: Docker, EC2, HTTPS, production settings, backups

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x + Alembic, httpx (async), APScheduler. Managed with uv.
- DB: SQLite file at data/chime.db by default. Keep it Postgres-compatible: all access through SQLAlchemy, URL from DATABASE_URL, no SQLite-only features.
- Frontend: React + Vite + TypeScript + Tailwind, TanStack Query, React Router. Mobile-first.
- Docker: `compose.yaml` runs the backend (one uvicorn worker, migrations on start) and Caddy (`deploy/Caddyfile`) serving the built frontend and proxying /api and /auth, so the app stays one origin. Keep all config in env vars. Deployment notes: `docs/DEPLOY.md`.

## Commands
Keep this section current as scripts are added.
- Backend dev: `cd backend && uv run fastapi dev app/main.py --port 8000`
- Frontend dev: `cd frontend && npm run dev` (serves http://127.0.0.1:5173, proxies /api and /auth to :8000)
- Tests: `cd backend && uv run pytest`; `cd frontend && npm run typecheck && npm run lint`
- Migrations: `cd backend && uv run alembic upgrade head` (new revision: `uv run alembic revision --autogenerate -m "..."`)
- First-time install: `cd backend && uv sync`; `cd frontend && npm install`
- Frontend production build: `cd frontend && npm run build` (runs `tsc --noEmit` first)
- Tag the library from MusicBrainz: `cd backend && uv run python -m scripts.tag_spike --limit 5000` (add `--dry-run` to measure without writing). Prints numbers only; unmapped tag names go to `data/unmatched_tags.txt`. One request per track at ~1.7 s, so a 1,200-track library takes about 35 minutes. It prints progress every 20 tracks with an ETA, reads only untagged tracks and commits each one, so Ctrl+C is safe and re-running carries on from where it stopped. A track MusicBrainz has no answer for gets a `source = unknown` row so it is not re-queried every run; `--retry-unknown` is how you re-check those later.
- Re-apply the tag map to the whole library with no network: `cd backend && uv run python -m scripts.retag` (add `--write` to keep it). Reads `track_tags.raw_tags`, so tuning `data/tag_map.yaml` costs seconds. Writes `data/tag_influence.txt` (map entries by how many tracks they tag, with the energy each assigns) and refreshes `data/unmatched_tags.txt`.
- Look at the ranking without playing anything: http://127.0.0.1:5173/dev/rank (needs `ENABLE_DEV_API`, default on)
- The live session screen: http://127.0.0.1:5173/session (not in the nav; reached from the orb or the mini player)
- Was the mix any good? `cd backend && uv run python -m scripts.evaluate` (`--days 90`, `--min 10`). Skip rate cut nine ways, including energy fit and tag confidence — the two cuts that say whether `WEIGHT_ENERGY` and the tagging are earning their weight. Numbers only, reads nothing but what the poller measured, prints its own caveats. Needs sessions that actually played with the backend running.
- Does editing a playing playlist interrupt playback? `cd backend && uv run python -m scripts.probe_playlist_edit` (`--session <id>`, defaults to the newest live one). Run it **during a live session on a real device**: it removes the last item, re-adds it, and prints a verdict. The one Phase 6 question documentation cannot answer.
- Run the whole stack in Docker: `HTTP_PORT=5173 docker compose up -d --build` (then http://127.0.0.1:5173; stop `npm run dev` first). `--profile postgres` adds Postgres. `APP_ENV=production` refuses to start unless the allowlist is set, cookies are secure, URLs are https and the dev API is off.
- Is WHOOP data fresh through the day? `cd backend && uv run python -m scripts.whoop_freshness` (`--every 30 --hours 12`). Leave it running on a normal day; it refreshes from WHOOP on an interval and prints only what changed, so the Phase 2 freshness question gets a measured answer.
- The live loop (playback poll, adaptation, WHOOP refresh) starts with the app and is switched off with `ENABLE_SCHEDULER=false`. It does nothing at all when no session is live, so an idle Chime makes no outbound requests. Run a second backend process with it off, or two pollers will fight over the same sessions.

## Hard rules: Spotify (read before writing any Spotify code)
1. Removed or blocked for our app, never call them: audio-features, audio-analysis, recommendations, related-artists, artist top-tracks, browse/featured-playlists, browse/categories, new-releases, "Get Several X" endpoints (tracks, artists, albums). Do not add fallbacks to them.
2. Playlists: create with `POST /me/playlists`; items live at `/playlists/{id}/items` (NOT `/tracks`); there is no true delete. Remove a playlist from the user's library with `DELETE /playlists/{id}/followers`. Save/check library: `PUT /me/library`, `GET /me/library/contains`. **Amended 2026-09-22, measured on a real account:** this rule used to say `DELETE /me/library`, which does accept `spotify:playlist:` URIs but whose official schema asks for `user-library-modify` **and** `user-follow-modify` **and** `playlist-modify-public` together — live it answers `403 Insufficient client scope` on our grant, and two real sessions recorded a removal that never happened. The unfollow route needs only `playlist-modify-public`/`-private`, which we already hold, and `GET /me/library/contains` confirmed it went from `[true]` to `[false]`. Chime out verifies every removal against `contains` rather than trusting the 200.
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
