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
- [x] Live round trip against a real WHOOP app. WHOOP's dashboard *does* accept `http://127.0.0.1:5173/auth/whoop/callback` even though its helper text says https only, so no tunnel or local TLS is needed. First connect pulled 3 cycles + 1 workout, offset `+05:30` stored.
- [ ] Verify cycle freshness during the day and report what actually updates — the measurement is written (`scripts/whoop_freshness.py`): leave it running on an ordinary day and it prints only the fields that moved, with the time, then a count per field. First live reading 2026-10-07 15:11 local: cycle open, recovery 82, sleep 71, strain 4.8. Needs a full day of readings to answer, so still open.
Demo: Home shows today's recovery, sleep and strain from WHOOP.

## Phase 3: Tagging and ranking (deterministic)
- [x] Spike: Last.fm / MusicBrainz coverage on the real library, report findings — MusicBrainz chosen (open, no key, tags inline on search hits, so one request per track). 83% of tracks tagged, 15% not in MusicBrainz at all. Last.fm not needed. **Spotify now sends no artist `genres` at all** (0 of 808 artists), so this is the only tag source, not an optional extra — SPEC section 5 updated.
- [x] tag_map.yaml + TagSource interface + energy/affinity computation — 158 entries, 21 aliases, 230 ignored tags (nationality, role, decade, format: skipped rather than counted as misses, which took mean confidence from 0.27 to 0.47)
- [x] Profile rules (SPEC section 3) with unit tests, including intent match | shift
- [x] Ranking with score breakdown; a dev-only page showing a ranked list for a chosen mood/type — `GET /api/dev/rank` and `/dev/rank`, behind `ENABLE_DEV_API`
Demo: pick "wind down + wired", see a sensible ranked list with reasons.
Whole library now tagged: 1,188 tracks, 989 with real tags (83%), 199 unknown (17% — 146 MusicBrainz has never heard of, 53 whose tags the map does not know). Mean confidence 0.46, mean energy 3.45.
Rank weighting (`RANK_WEIGHTS`, pairs of two) plus reading unknown tags through to the genre inside them took **mean confidence 0.44 -> 0.78, median 0.48 -> 0.87**, and rescued 32 tracks from unknown. `scripts/retag.py` applies map changes from `raw_tags` with no network.
Open: **the energy spread is too narrow to fill the curves** — 992 of 1,042 tracks sit between 2.5 and 4.5, only 9 below and 13 above. Measured, not guessed: the cause is *not* the averaging. Scoring the top tag alone and ignoring the other seven leaves the standard deviation at 0.41 and moves nothing out of the middle bands. So it is the energy this map assigns to whichever genres dominate the library, and the fix is editing `data/tag_map.yaml` against `data/tag_influence.txt` (86 entries in use, top of that file decides most of the library). That is a judgement call about this library, so it needs its owner's eyes, not mine — and rule 7 keeps those names out of my context anyway.
Open: 163 tag names in `data/unmatched_tags.txt` still have no entry, now that inheritance has absorbed the easy ones.

Deferred by decision (2026-09-22), to revisit once the loop runs and the narrow spread can be judged by ear rather than in a histogram:
- A hand-written seed list keyed by energy band, injected only where the library cannot reach the curve (not on a fixed ratio). This is Phase 8's Discovery with a static file instead of a live LLM call.
- `energy_override` UI ("Feels calmer" / "Feels more intense") so a handful of hand-marked tracks can give wind-down real material without leaving the library.

## Phase 4: Chime in / Chime out
- [x] Create playlist, add items, find device, start playback
- [x] Session persistence, mood in/out, summary
- [x] Remove or keep playlist on Chime out
- [x] Session screen, mini player, Chime out sheet
- [x] Intent: press and hold the orb to shift (DESIGN "Press and hold to shift"), IntentSegment in the sheet, `intent` on the session
Demo: full loop on a real device, plus a held orb producing a visibly different mix from the same mood.

Order of operations in `chime_in` is deliberate and tested: rank locally, write the session row, then create the playlist, then play.
Changed (2026-09-22), on request: **a Spotify that will not press play no longer fails the session.** Chime cannot check for Premium or for an open Spotify app in advance, so both used to surface as a dead end that deleted the playlist it had just made. Now the session stays `created`, keeps its playlist, and the answer carries `needs_manual_start`, a reason, and `playlist_url`. Chime in tries to open that playlist in a new tab (a popup blocker may refuse it, which is why the link is always on screen too), `POST /api/sessions/{id}/start` retries once Spotify is open, and the next `/active` poll that sees our own playlist playing promotes the session to `active`. What still fails a Chime in is a refusal that leaves nothing usable — a playlist we could not fill, or an expired login — and those still take the playlist back out of the library.
Decided (2026-09-22): mood is optional in the sheet. The sheet still opens, Start works with nothing selected, and tapping the chosen chip again clears it. Without a mood the engine runs on body data and the time of day; `intent: shift` becomes a no-op (`profile_rules.build_profile` needs a mood to have something to move away from), so the sheet says so under the segment instead of letting it look like it worked.
Deviation from DESIGN: intent `shift` rewrites the energy curve (`SHIFT_CURVES[mood]`) and leaves the session type alone, so there is no "hue of where the session is heading" to recolour the orb and the Start pill with — hue follows the session type and the copy carries the shift. Doing it DESIGN's way would mean reimplementing `resolve_type()` in the frontend.
Deferred: the track row overflow menu ("Feels calmer" / "Feels more intense" are the deferred `energy_override`; "Remove from this session" has no endpoint), so a row carries only "open in Spotify". Played/skipped counts stay null until the Phase 6 poller measures them, and the summary omits them rather than showing zero.

## Phase 5: History
- [x] List with grouping, filters, week summary
- [x] Detail page (before/after, why, songs, timeline)
- [x] Bring it back as a playlist
- [x] Delete a record (DESIGN asks for it; not in SPEC's API surface)
Demo: a week of sessions grouped by day, filter to Focus, open one, bring its playlist back, delete a record.

Prompt: `prompts/05-history.md`. Everything History reads is already stored by Phase 4, so this phase adds no columns: the new endpoints are `GET /api/sessions`, `GET /api/sessions/week`, `POST /api/sessions/{id}/restore`, `DELETE /api/sessions/{id}`, plus the `session_events` timeline on the existing detail response. Restore writes the new playlist URI to a `session_event` rather than over `sessions.playlist_uri`, which still points at the playlist that was removed.

Built as specified, with these decisions worth knowing:
- **All four live in `app/api/routes/sessions.py`.** `/week` and `/{session_id}` are the same shape to a router, and only declaration order tells them apart; a separate History router would have risked `week` being parsed as an id depending on mount order.
- **Minutes come off `sessions.summary`** for anything finished, and off the clock only for a live session. Recomputing per row would be a query each for a page of twenty, and a finished session's minutes were settled the day it ended.
- **A failed session is out of the list and the week by default** (`include_failed=true` brings it back). It played nothing.
- **Grouping by day happens in the browser**, because the day a person lived through is their local one; the backend filters by UTC days, which is right for a query. `from`/`to` are inclusive of `to`.
- **A removed playlist is no longer offered as a link** anywhere — `playlist_url` is null once `playlist_removed_at` is set, since it would open a Spotify page saying the playlist does not exist.
- **Filters live in the URL** (`/history?type=focus&mood=flat&kept=1`), so a filtered list survives a reload and the back button, and each combination caches separately.
- Deferred, deliberately: the mood-shift figure in the week card only counts sessions that recorded *both* ends, and says so rather than implying nothing moved. A date-range picker is not built — the API takes `from`/`to` and nothing on screen sets them yet.

## Phase 6: Live loop
- [x] Playback polling, skip capture, behavior boost
- [x] Adaptation triggers, append/trim upcoming tracks
- [ ] Test whether editing a playing playlist interrupts playback; choose approach — the measurement is written (`scripts/probe_playlist_edit.py`) but needs a live session on a real device to run, so the choice is still provisional. Adaptation edits the playlist today.
- [x] A WHOOP poller. APScheduler is in the stack but nothing is scheduled yet: body state is read on demand and cached for `BODY_STATE_TTL_SECONDS`, so a session only ever sees the body data it started with. Mid-session readiness and day_part changes are adaptation triggers, and they need something refreshing WHOOP in the background (SPEC section 6). One function a poller or a webhook can both call.
Demo: chime in, let it play, skip a couple of songs on purpose, and watch the queue grow an "added later" song; chime out and the summary reports plays and skips instead of omitting them.

Prompt: none — there is no `prompts/06-*.md`, so this phase was built from `docs/PLAN.md` and SPEC section 6 directly. Three new services (`playback`, `behavior`, `adaptation`), one scheduler, one migration (`0006_session_track_finished_at`), and no new endpoints: everything here happens on a timer and surfaces through the responses Phases 4 and 5 already return.

Built as specified, with these decisions worth knowing:
- **Plays are sampled, not logged.** Spotify only answers "what is playing now", so `played_ms` is the *highest* `progress_ms` ever seen for a row and a song shorter than one poll interval can be missed entirely. This is the single most important caveat about every number Phase 6 produces, and it is printed with the evaluation output rather than buried here.
- **A song is judged only once playback has left it**, which is why `session_tracks` needed `finished_at`: it separates "not played" from "played, verdict in". A session ended part way through a song leaves that song unjudged on purpose — stopping Chime is not rejecting a song.
- **Silence never counts.** A pause, an unreadable playback read, an expired grant or playback on someone else's playlist all leave every row exactly as it was. The alternative — treating a failed read as a skip — would have poisoned the behaviour boost with the app's own outages.
- **The behaviour boost was inert until now.** SPEC section 5 step 5 is 15% of the ranking score and nothing had ever written `user_tracks.completes` / `fast_skips`; `services/behavior.py` fills them, so the ranking only starts learning from this phase on.
- **Adaptation adds before it removes.** A failed append leaves the playlist exactly as it was; a failed removal leaves a longer playlist whose old songs still play. The other order can leave someone listening to a playlist that runs out, and there is a test pinning the request order.
- **Each trigger fires once per run of events, not once per tick.** The last `adapt` event is the watermark for all four triggers, so the same three skips or the same mood check cannot re-trigger every five minutes for the rest of the session. Without this the mix churns.
- **An adaptation continues the curve rather than restarting it**, sampling `profile.curve()` from where the session has got to. Restarting would drop a workout back to its opening energy half an hour in.
- **Trimmed songs are deleted, not flagged.** Nobody heard them, and keeping them would put songs into History's record of what was listened to. Positions are not renumbered; the gaps cost nothing because `position` is only ever used for ordering.
- **`sessions.target_profile` is never rewritten.** It is the brief the session began with, which is a fact about how it started and stays true; each adaptation records its own numbers on its own `adapt` event.
- **WHOOP is polled only for users with a live session.** Everything else reads body state on demand, so polling an idle user spends WHOOP's budget (100/min, 10,000/day) on an answer nobody asked for. A refresh that changed nothing is not recorded, or every timeline fills with "WHOOP data refreshed" four times an hour.
- **The loop is one switch.** `ENABLE_SCHEDULER=false` turns all three jobs off, which is how the tests run and how a second process stays quiet; the ticks are plain async functions so they can be called directly. Every job is isolated per session: one expired grant must not stop the loop before it reaches the next session, because APScheduler only logs the exception and the whole tick is lost.
- **`scripts/evaluate.py` answers "was the mix any good?"** by cutting skip rate nine ways — including energy fit and tag confidence, the two that say whether `WEIGHT_ENERGY` and the tagging are earning their weight. It prints its own caveats and hides thin buckets, because a number that looks precise and is not is worse than no number.
- Deferred: webhooks (they need public HTTPS, so polling stays the v1 answer; `whoop_sync.refresh_body_data` is already the one function either path calls). Nothing on screen triggers an adaptation by hand. The playlist-edit probe above.

## Phase 7: Docker and deployment
- [x] Dockerfiles, docker-compose (SQLite volume, optional Postgres profile)
- [x] EC2 notes, HTTPS, redirect URIs, allowlist enforced — `docs/DEPLOY.md`
- [x] GitHub Actions: lint, test, build — `.github/workflows/ci.yml`
Demo (local): `HTTP_PORT=5173 docker compose up -d --build`, open http://127.0.0.1:5173, log in, chime in.

Prompt: none, built from this checklist. Not deployed, by request: everything stops short of an instance.

Built as specified, with these decisions worth knowing:
- **Two containers, one origin.** `backend` (uvicorn) and `web` (Caddy serving the built SPA and proxying `/api` and `/auth`). The OAuth cookies need one origin, which the Vite proxy gave us in development; Caddy gives the same in production, and fetches and renews its own Let's Encrypt certificate when `SITE_ADDRESS` is a domain. No nginx, no certbot cron.
- **One uvicorn worker, always.** The live loop runs in-process, so a second worker is a second poller on the same session. The Dockerfile pins it and DEPLOY.md says why.
- **Migrations run on every start** (`alembic upgrade head` before uvicorn), so an update is `git pull && docker compose up -d --build`.
- **`APP_ENV=production` refuses to start** unless the allowlist is set, the secrets are set, cookies are secure, `FRONTEND_ORIGIN` and both redirect URIs are https, and the dev API is off. It names every gap at once. This is what "allowlist enforced" means here: the first-login-owns-it rule stays for local use, but cannot reach the internet.
- **Postgres is a profile, and needed one new dependency:** `psycopg[binary]` as an optional extra (`postgres`). Without a driver the profile could not work. The image always installs it, so switching needs no rebuild. CI runs every migration up and down against Postgres 17 on each push, which is what keeps "Postgres-compatible" true rather than hoped for.
- **The tag map is baked into the image** at `/app/config/tag_map.yaml`, because `data/` is a volume and would hide it. Editing the map means a rebuild, then `scripts.retag --write`.
- **CI builds the images but never pushes them.** Deploying stays a manual step.
- Verified locally on 2026-10-07: both images build, migrations up/down/up on Postgres 17, `/api/health` and the SPA fallback through Caddy, `/api/me` 401 without a cookie, `/auth/spotify/login` redirects to Spotify, security headers present, and production refusal with an open allowlist.

## UI redesign (2026-10-07)
Home and Session rebuilt from the Claude Design mockups in `docs/design/` (prompt: `prompts/02-ui-redesign.md`, written before Phase 4, so its "mock data" and "placeholder" steps were applied to the real screens instead). A lit sphere orb with corona and pulse rings; a petal-ring navigation around it from 880 px; a settings gear; a tab bar of Home, History, Insights and Library below 880 px; and a slim top bar on other screens from 880 px. Library and WHOOP cards left Home for a new Library screen and Settings. Insights is a real screen with the week summary, which says plainly what is not built yet. DESIGN.md follows, including the exceptions: uppercase petal labels (from the mockup, against principle 4), and mood stays optional (against the mockup's disabled Start).

## Phase 8: Optional
- [ ] Discovery (LLM proposes songs from non-Spotify inputs only; resolve via search)
- [ ] Insights tab (day-level outcomes: skip rate by mix type, next-morning recovery after wind-down)
- [ ] YouTube provider behind MusicProvider
