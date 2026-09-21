# Prompt 01: foundation, Spotify login, library sync, Home shell

## Before you paste this (human checklist)
1. Create a Spotify app at https://developer.spotify.com/dashboard (your account needs Premium).
2. Add this redirect URI exactly: `http://127.0.0.1:5173/auth/spotify/callback`
3. Copy the Client ID. This app uses PKCE, so no client secret is needed.
4. Run Claude Code from the project root (the folder containing CLAUDE.md), then paste everything below the line.

---

Read `CLAUDE.md` fully, then `docs/SPEC.md` (sections 1, 2, 4, 9, 10), `docs/DESIGN.md`, and Phase 1 of `docs/PLAN.md`. Look at `docs/reference/inspiration.png` for the visual direction.

**Do not write code yet.** First reply with:
1. A short plan (files/modules you will create, in order).
2. Any place where these docs look wrong or ambiguous against the live Spotify docs. Check the current docs for `GET /me/tracks`, `GET /artists/{id}`, the token endpoint for PKCE, and the redirect URI rules.
3. Questions, if any (max 3).

Wait for my OK. After my OK, build Phase 1 as follows.

## Goal
A running app where I can log in with Spotify, watch my liked songs sync into the database, and land on a Home screen that already looks like the design. Nothing else.

## Build

**Repo**
- `backend/` (uv project, Python 3.12), `frontend/` (Vite + React + TS + Tailwind), `data/` (gitignored, holds the SQLite file), plus `.gitignore`, `.env.example`, and a `README.md` with setup steps including the Spotify app creation above.
- `.env.example` keys: `SPOTIFY_CLIENT_ID`, `SPOTIFY_REDIRECT_URI` (default `http://127.0.0.1:5173/auth/spotify/callback`), `ENCRYPTION_KEY` (with a one-line command to generate a Fernet key), `SESSION_SECRET`, `DATABASE_URL` (default `sqlite:///data/chime.db`), `ALLOWED_SPOTIFY_USER_IDS` (empty = first login becomes owner), `FRONTEND_ORIGIN` (`http://127.0.0.1:5173`).

**Backend**
- FastAPI app with pydantic-settings config, structured logging that never prints tokens, and `GET /api/health`.
- SQLAlchemy 2.x models and one Alembic migration for: `users`, `oauth_tokens`, `artists`, `tracks`, `user_tracks` (as in SPEC section 4; other tables come in later phases). Fernet encryption helper for token columns.
- Spotify integration in `app/integrations/spotify/`: async httpx client, automatic access-token refresh, timeout, retry/backoff on 429/5xx honoring Retry-After, typed pydantic responses, typed errors.
- Auth routes: `GET /auth/spotify/login` (PKCE + random state; verifier and state in a short-lived signed httpOnly cookie), `GET /auth/spotify/callback` (validate state, exchange code, call `GET /me`, apply the allowlist / first-user-is-owner rule, upsert user, store encrypted tokens, set signed httpOnly SameSite=Lax session cookie, redirect to the frontend), `POST /auth/logout`, `GET /api/me`.
- Requested scopes: `user-library-read`, `user-library-modify`, `user-read-recently-played`, `user-top-read`, `playlist-read-private`, `playlist-modify-private`, `user-read-playback-state`, `user-modify-playback-state`, `user-read-currently-playing`. Check the docs for which endpoints need which scope and tell me if any are unnecessary.
- Library sync (background task): page through `GET /me/tracks` (limit 50), upsert `tracks` and `user_tracks(source='liked')`; then collect unique artist IDs and fetch each with `GET /artists/{id}` at low concurrency (4) with backoff, storing `genres` when present (the field may be missing; do not fail). Resumable if interrupted, incremental on re-sync (liked songs come newest first, so stop at the first already-known liked song), with a `full=true` option. Endpoints: `POST /api/library/sync`, `GET /api/library/status` (state, tracks synced, artists fetched / total).

**Frontend**
- Tokens from `docs/DESIGN.md` as CSS variables and Tailwind theme values. Figtree via `@fontsource-variable/figtree`.
- Vite dev server on `127.0.0.1:5173` proxying `/api` and `/auth` to `http://127.0.0.1:8000`.
- Routes: `/login`, `/` (Home), `/history` (placeholder with the empty state copy), `/settings` (placeholder). Auth guard using `GET /api/me`.
- Navigation: bottom tab bar on mobile, left rail at >= 1024 px.
- Login screen: product name, one line of copy, "Continue with Spotify".
- Home: greeting, the `Orb` component (idle glow, ember hue at reduced intensity), library sync card driven by `/api/library/status`, a "Connect WHOOP" placeholder card (no functionality yet), last-session card placeholder. Tapping the orb opens the Chime in sheet from DESIGN.md as **UI only**: mood chips, session type, Start closes the sheet. No backend calls.
- Build `Orb`, `Sheet`, `MoodChips`, `SessionTypeSegment`, `StatFigure`, `EmptyState` as reusable components.

**Tests**
- Backend (pytest + respx): encryption round trip; PKCE verifier/challenge; callback happy path plus bad-state and disallowed-user cases; token refresh; sync upsert and incremental stop logic using fixture responses. No real network.
- Frontend: `typecheck` and `lint` scripts pass.

## Allowed dependencies (ask before adding others)
Backend: fastapi, uvicorn/`fastapi[standard]`, sqlalchemy, alembic, httpx, pydantic-settings, cryptography, itsdangerous (or equivalent for signed cookies), pytest, pytest-asyncio, respx.
Frontend: react, react-router-dom, @tanstack/react-query, tailwindcss, @fontsource-variable/figtree, lucide-react, eslint, typescript.

## Out of scope
WHOOP, tagging/ranking, creating playlists, playback, session logic, Docker, deployment. Do not stub these beyond the placeholders listed.

## Definition of done
- I can run the two dev commands from `CLAUDE.md`, open `http://127.0.0.1:5173`, log in with Spotify, and see sync progress reach completion on my real library.
- Home matches the design at 390 px and at desktop width, keyboard focus is visible, reduced-motion is respected.
- `uv run pytest`, `npm run typecheck`, `npm run lint` all pass.
- `docs/PLAN.md` Phase 1 is ticked, `CLAUDE.md` Commands section is accurate, and your final message lists: what changed, how to run it, what I should click to verify, and anything you were unsure about (especially any live-API behavior that differed from the docs).
