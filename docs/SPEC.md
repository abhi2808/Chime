# Chime spec

## 1. Product in one paragraph
Open the app, tap **Chime in**, pick a mood (and optionally a session type). Chime reads your WHOOP daily state, ranks songs from your Spotify library for that moment, creates a private temporary playlist, and starts playback. While the session runs, it can gently adapt the queue. **Chime out** ends the session, asks how you feel now, and removes the playlist from your library unless you keep it. **History** remembers every session: how you entered, what played, how you left.

Non-goals: public launch, monetization, social features, training ML models, live heart-rate or stress features (WHOOP's API does not provide them).

## 2. Signals we actually have
| Signal | Source | Freshness |
|---|---|---|
| Recovery score, HRV, resting HR, SpO2, skin temp | WHOOP recovery | once per day (morning) |
| Sleep performance, duration | WHOOP sleep | once per day |
| Day strain | WHOOP cycle | updates through the day, coarse |
| Workouts (strain, avg/max HR, zones) | WHOOP workout | after workout ends |
| Mood | user check-in at Chime in / Chime out | live |
| Skips, completions, plays | Spotify playback + recently-played | live (~20 s polling) |
| Time of day, day of week | clock | live |

Consequence: WHOOP gives *context* (how ready is your body today), the user gives the *live mood*, and skips give *live feedback*. Never present WHOOP data as "live stress".

### Body state (input to the engine)
```json
{
  "recovery": 41, "hrv_ms": 38, "rhr": 61, "sleep_performance": 63,
  "day_strain": 9.4, "minutes_since_last_workout": 210,
  "readiness": "low",          // low <34, medium 34-66, high >66 (WHOOP's own bands)
  "day_part": "evening",       // early_morning | morning | afternoon | evening | late_night
  "mood": "wired"              // wired | drained | flat | steady | fired_up
}
```
Every figure is optional: WHOOP scores a day in stages and may not be connected at all. `GET /api/body-state` therefore always answers 200 and adds what a screen needs to explain a gap — `connected`, `has_data`, `calibrating`, `needs_reconnect`, `date`, `fetched_at`, and a `note` written to be shown verbatim ("WHOOP isn't connected, so this mix uses your mood and the time of day."). `mood` is not part of that response: it comes from the user at Chime in.

### Session types
`auto` (default), `workout`, `focus`, `wind_down`, `wake_up`. `auto` resolves a type from day_part, recent workout, and mood, and the resolved type is stored on the session.

### Intent
`match` (default) or `shift`. `match` meets the body where it is. `shift` deliberately moves it to the other pole: you are flat and want to be lifted out of it, or wired and want to be brought down. Intent is stored on the session and changes only the target profile, never the candidate pool.

## 3. Target profile (rules, kept as data)
The engine maps body state + type to a target profile: `energy` (1-5 curve over the session), and affinity weights for `calm`, `focus`, `workout`, `wind_down`, `wake_up`.

Starting rules (put in `backend/app/services/profile_rules.py` as plain data + unit tests, tune later):
- **workout**: energy ramps 3 -> 5, ease off in the last 10%. If mood is drained, cap at 4.
- **focus**: energy 2-3 flat; prefer focus-affine tracks.
- **wind_down**: energy 2 -> 1 descending.
- **wake_up**: energy ramps 2 -> 4; if readiness is low, cap at 3.
- Mood shift on top: wired -1, drained -1 (except workout), flat +1, fired_up +1, steady 0. Clamp to 1-5.
- Low readiness lowers the ceiling by 1 for non-workout sessions.

**Intent = shift** replaces the mood shift above with its opposite pole, and makes the curve a ramp *towards* that pole rather than a flat sit in it:
- wired -> descend to 1-2 (calm it down; same direction as match, steeper)
- drained -> ramp 2 -> 4 (this is the case match cannot express: match takes drained *down*)
- flat -> ramp 3 -> 5
- fired_up -> descend 4 -> 2
- steady -> no target to move to, so shift is a no-op; the UI still accepts it
- Readiness still caps the ceiling. A low-recovery body does not get dragged to 5 just because the mood says flat: cap at 4 for non-workout sessions, and say so in `why_text`.

Affinity weights are untouched by intent; only the energy curve moves.

## 4. Data model (SQLAlchemy; every user-owned row has user_id)
- `users`: id, spotify_user_id, display_name, created_at
- `oauth_tokens`: user_id, provider (spotify|whoop), access_token_enc, refresh_token_enc, expires_at, scopes
- `artists`: spotify_artist_id, name, genres (json, nullable), fetched_at
- `tracks` (shared cache): spotify_track_id, name, artist_ids (json), artist_names (json), album_name, image_url, duration_ms, explicit, cached_at
- `track_tags` (shared): track_id, energy (1-5 float), affinities (json), source (map|external|manual), confidence, updated_at
- `user_tracks`: user_id, track_id, source (liked|playlist|top|recent), liked_at, plays, completes, fast_skips, kept_count, energy_override (nullable), last_played_at
- `whoop_daily`: user_id, date, cycle_id, timezone_offset, recovery, hrv_ms, rhr, sleep_performance, day_strain, spo2, skin_temp_c, calibrating, cycle_open, fetched_at (raw payloads NOT stored). `date` is the **member's** local date for the cycle and `timezone_offset` is their UTC offset, because a WHOOP day starts when they wake and matches neither UTC midnight nor the server's clock. Every figure is nullable: WHOOP fills a day in over time, and a re-read that arrives `PENDING_SCORE` must never overwrite a scored value.
- `whoop_workouts`: user_id, whoop_id (UUID in API v2), start, end, strain, avg_hr, max_hr, sport, fetched_at
- `sessions`: id, user_id, type, intent (match|shift), mood_in, mood_out, started_at, ended_at, body_in (json), body_out (json), playlist_uri, playlist_name, kept, playlist_removed_at, target_profile (json), why_text, summary (json: played, skipped, skip_rate, minutes)
- `session_tracks`: id, session_id, position, track_id, source (library|adapt), started_at, played_ms, skipped, score_breakdown (json)
- `session_events`: id, session_id, ts, type (mood_check|whoop_refresh|adapt|error), payload (json)
- `settings`: user_id, values (json): sources, explicit_ok, poll_seconds, default_keep

Retention note: `tracks` and `artists` cache Spotify metadata. Keep it minimal and refreshable, and re-read Spotify's Developer Policy on caching and retention before publishing the repo.

## 5. Song tagging and ranking (deterministic, no AI on Spotify content)
Spotify no longer exposes energy/tempo/valence, and Spotify content may not be fed to AI/ML models. So track "energy" comes from a rule pipeline:

1. **Genres**: `GET /artists/{id}` gives artist genres (treat the field as optional; one call per unique artist, cached).
2. **Optional external tags** behind a `TagSource` interface. Phase 3 starts with a spike to check Last.fm (`track.getTopTags`, `artist.getTopTags`) and MusicBrainz for availability, terms and coverage. Sending titles to a non-AI tag service is fine; sending them to an LLM is not. If coverage is poor, genres alone are acceptable.
3. **Mapping table**: `data/tag_map.yaml` maps tag/genre -> `{energy, affinities}` (e.g. `ambient: {energy: 1, calm: .9, focus: .8}`; `hip hop: {energy: 4, workout: .7}`). A track's tags are the weighted average of its matches. Unknown = energy 3, low confidence.
4. **Manual override** (highest priority): user marks a track "calmer" or "more intense" from the UI -> `user_tracks.energy_override`.
5. **Behavior boost** (per user, plain arithmetic, no trained model): completions and keeps raise a bounded boost, fast skips (<10 s) lower it, decayed over time.

**Ranking**: `score = 0.50*energy_fit + 0.25*affinity(type) + 0.15*behavior_boost + 0.10*freshness`, where freshness penalizes tracks used in the last few sessions. Then shape the order to the energy curve, and avoid more than 2 tracks in a row from one artist. Store the per-component breakdown in `session_tracks.score_breakdown` so "Why this mix" and History can explain themselves.

**LLM use (allowed)**: given only non-Spotify inputs (body state, mood, type, day_part, and the *numeric* target profile), Claude can write the one-sentence "why this mix". Never include track or artist data in that prompt. Optional; template fallback when no API key.

**Discovery (Phase 8, optional)**: an LLM may propose artist + title pairs from its own knowledge given only mood/type/user-typed taste seeds (typed by the user, not pulled from Spotify), each resolved through `/search`. Off by default; a discovery slider caps the share.

## 6. Session engine
State machine: `created -> active -> ended(kept | removed)`, or `failed`.

**Chime in** (`POST /api/sessions {type, mood, intent}`):
1. Refresh WHOOP if daily data is older than 10 min (else use cache). If WHOOP is disconnected or fails, continue with mood + time only and say so.
2. Build body state, resolve `auto` type, compute target profile.
3. Rank candidates from allowed sources (settings), take about 25 tracks (~90 minutes max).
4. `POST /me/playlists` (private), name `Chime · <Type> · <time>`. Add items in chunks of 100 via `POST /playlists/{id}/items`.
5. Find a device (`GET /me/player/devices`). If none: return `NO_ACTIVE_DEVICE` with instructions. Otherwise transfer if needed and `PUT /me/player/play` with `context_uri`.
6. Persist session, session_tracks, session_events. Return session + tracks + why_text.

**While active** (APScheduler, per active session):
- every `PLAYBACK_POLL_SECONDS` (default 20): read playback state, record track transitions into session_tracks (started_at, played_ms, skipped = moved on before ~10 s or before 30% played).
- every `SESSION_POLL_SECONDS` (default 300): evaluate adaptation.
- Adapt only on a trigger: mood re-check, readiness/day_part bucket change, 3+ skips in the last 5, or fewer than 3 upcoming tracks. Adapting means appending new tracks and removing *upcoming unplayed* ones. Never replace the whole playlist while it is playing. Test early whether editing a playing playlist interrupts playback; if it does, use the queue endpoint instead.

**Chime out** (`POST /api/sessions/{id}/end {keep, name?, mood_out}`):
1. Pause playback (optional per request). Take a final WHOOP snapshot into `body_out` (daily-level; expect small deltas).
2. Compute summary: minutes, tracks played, skips, skip rate.
3. If `keep`: rename via `PUT /playlists/{id}`. Else `DELETE /me/library` for the playlist URI, set `playlist_removed_at`.
4. Session tracks stay in the DB either way. History can **bring it back** by recreating a playlist from `session_tracks`.

## 7. API surface (all under /api except auth)
`GET /auth/spotify/login`, `GET /auth/spotify/callback`, `GET /auth/whoop/login`, `GET /auth/whoop/callback`, `POST /auth/logout`
`GET /api/me`, `POST /api/library/sync`, `GET /api/library/status`, `GET /api/body-state`
`POST /api/sessions`, `GET /api/sessions/active`, `POST /api/sessions/{id}/mood`, `POST /api/sessions/{id}/end`, `GET /api/sessions` (filters: type, mood_in, kept, from, to), `GET /api/sessions/{id}`, `POST /api/sessions/{id}/restore`
`GET|PUT /api/settings`, `POST /api/tracks/{id}/override`

## 8. Settings
Sources: liked songs (default on), my playlists, top tracks. Explicit content allowed. Default keep-or-remove on Chime out. Poll intervals. Discovery slider (Phase 8, hidden until then).

## 9. Auth and security
- Spotify: Authorization Code with PKCE, random `state`, verifier + state in a short-lived signed httpOnly cookie. Redirect URI default `http://127.0.0.1:5173/auth/spotify/callback` (Vite proxies to the backend so cookies stay same-origin).
- Scopes (verify each in the docs, drop what is unused): `user-library-read`, `user-library-modify`, `user-read-recently-played`, `user-top-read`, `playlist-read-private`, `playlist-modify-private`, `user-read-playback-state`, `user-modify-playback-state`, `user-read-currently-playing`.
- App login = a signed httpOnly, SameSite=Lax session cookie issued after Spotify login. Allowlist via `ALLOWED_SPOTIFY_USER_IDS` (empty = the first user to log in becomes the owner and everyone else is refused). This matters the moment it is deployed anywhere public, because the app can control someone's playback and read their WHOOP data.
- Tokens encrypted at rest (Fernet). No raw WHOOP payloads stored by default. A "delete all my data" action wipes sessions, tags overrides and tokens.
- WHOOP: standard OAuth2 code flow, random `state`. Register the redirect as `http://127.0.0.1:5173/auth/whoop/callback`; if WHOOP's dashboard rejects it, report back rather than switching hosts silently.

## 10. Verify early (do not assume)
- Live shape of `GET /me/tracks`, `GET /artists/{id}` (is `genres` present?), `GET /me/player/devices`.
- Required scope for `DELETE /me/library` on a playlist URI.
- Whether editing a playing playlist interrupts playback.
- WHOOP cycle endpoint freshness during the day, and whether the current cycle's strain updates live.
- Last.fm / MusicBrainz coverage for the user's actual library (Phase 3 spike).
