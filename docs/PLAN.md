# Plan

Tick items as they are finished. Each phase has a matching prompt in `prompts/` (only phase 1 is written; the rest get written after the previous phase is verified).

## Phase 1: Foundation, Spotify login, library sync, Home shell
- [x] Repo scaffold (backend uv project, frontend Vite app, .env.example, .gitignore, README)
- [x] Config + Fernet token encryption + Alembic initial migration
- [x] Spotify client with refresh + backoff
- [x] Spotify login (PKCE, state), allowlist, session cookie, logout
- [x] Library sync (liked songs + unique artists' genres), resumable, status endpoint
- [x] Frontend shell: tokens, Figtree, tab bar / rail, login screen
- [x] Home screen with orb (Chime in sheet is UI only, fake data)
- [x] Tests, typecheck, lint green
Demo: log in with Spotify, watch sync progress, see Home at 390 px and desktop width.

## Phase 2: WHOOP connection and body state
- [x] WHOOP OAuth (offline scope), encrypted tokens, refresh
- [x] Pull cycle, recovery, sleep, workouts into whoop_daily / whoop_workouts
- [x] `GET /api/body-state`, Home figures use real data
- [ ] Live round trip against a real WHOOP app (blocked: WHOOP documents https and custom-scheme redirect URIs only, so `http://127.0.0.1:5173/...` may be refused; needs credentials in .env)
- [ ] Verify cycle freshness during the day and report what actually updates
Demo: Home shows today's recovery, sleep and strain from WHOOP.

## Phase 3: Tagging and ranking (deterministic)
- [ ] Spike: Last.fm / MusicBrainz coverage on the real library, report findings
- [ ] tag_map.yaml + TagSource interface + energy/affinity computation
- [ ] Profile rules (SPEC section 3) with unit tests, including intent match | shift
- [ ] Ranking with score breakdown; a dev-only page showing a ranked list for a chosen mood/type
Demo: pick "wind down + wired", see a sensible ranked list with reasons.

## Phase 4: Chime in / Chime out
- [ ] Create playlist, add items, find device, start playback
- [ ] Session persistence, mood in/out, summary
- [ ] Remove or keep playlist on Chime out
- [ ] Session screen, mini player, Chime out sheet
- [ ] Intent: press and hold the orb to shift (DESIGN "Press and hold to shift"), IntentSegment in the sheet, `intent` on the session
Demo: full loop on a real device, plus a held orb producing a visibly different mix from the same mood.

## Phase 5: History
- [ ] List with grouping, filters, week summary
- [ ] Detail page (before/after, why, songs, timeline)
- [ ] Bring it back as a playlist

## Phase 6: Live loop
- [ ] Playback polling, skip capture, behavior boost
- [ ] Adaptation triggers, append/trim upcoming tracks
- [ ] Test whether editing a playing playlist interrupts playback; choose approach

## Phase 7: Docker and deployment
- [ ] Dockerfiles, docker-compose (SQLite volume, optional Postgres profile)
- [ ] EC2 notes, HTTPS, redirect URIs, allowlist enforced
- [ ] GitHub Actions: lint, test, build

## Phase 8: Optional
- [ ] Discovery (LLM proposes songs from non-Spotify inputs only; resolve via search)
- [ ] Insights tab (day-level outcomes: skip rate by mix type, next-morning recovery after wind-down)
- [ ] YouTube provider behind MusicProvider
