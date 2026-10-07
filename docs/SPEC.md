# Chime spec

## 1. Product in one paragraph
Open the app, tap **Chime in**, and optionally pick a mood and a session type — both can be skipped, and then the mix rests on body data and the time of day alone (`intent: shift` is the one thing that needs a mood, having nothing to move away from without one). Chime reads your WHOOP daily state, ranks songs from your Spotify library for that moment, creates a private temporary playlist, and starts playback. While the session runs, it can gently adapt the queue. **Chime out** ends the session, asks how you feel now, and removes the playlist from your library unless you keep it. **History** remembers every session: how you entered, what played, how you left.

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
- `track_tags` (shared): track_id, energy (1-5 float), affinities (json), source (unknown|map|external|manual), confidence, raw_tags (json, nullable), updated_at. `source = unknown` records "we looked and found nothing", which a later run must be able to tell apart from "never looked". `raw_tags` keeps the source's own `[tag, weight]` pairs so an edited `tag_map.yaml` can be re-applied to the whole library in seconds instead of re-fetching it over a day.
- `user_tracks`: user_id, track_id, source (liked|playlist|top|recent), liked_at, plays, completes, fast_skips, kept_count, energy_override (nullable), last_played_at
- `whoop_daily`: user_id, date, cycle_id, timezone_offset, recovery, hrv_ms, rhr, sleep_performance, day_strain, spo2, skin_temp_c, calibrating, cycle_open, fetched_at (raw payloads NOT stored). `date` is the **member's** local date for the cycle and `timezone_offset` is their UTC offset, because a WHOOP day starts when they wake and matches neither UTC midnight nor the server's clock. Every figure is nullable: WHOOP fills a day in over time, and a re-read that arrives `PENDING_SCORE` must never overwrite a scored value.
- `whoop_workouts`: user_id, whoop_id (UUID in API v2), start, end, strain, avg_hr, max_hr, sport, fetched_at
- `sessions`: id, user_id, type, intent (match|shift), mood_in, mood_out, started_at, ended_at, body_in (json), body_out (json), playlist_uri, playlist_name, kept, playlist_removed_at, target_profile (json), why_text, summary (json: played, skipped, skip_rate, minutes)
- `session_tracks`: id, session_id, position, track_id, source (library|adapt), started_at, finished_at, played_ms, skipped, score_breakdown (json). `finished_at` (added Phase 6) is what separates "not played" from "played, verdict in": `skipped` can only be trusted once playback has *left* a song, and a null `finished_at` on a started song means either it is playing now or the session ended on it. `played_ms` is the highest progress ever *seen*, not a total — playback is sampled, so it is a floor.
- `session_events`: id, session_id, ts, type (mood_check|whoop_refresh|adapt|error|manual_start|restore), payload (json). `manual_start` records that Spotify would not press play and why, which is what lets the session screen explain itself after a reload without a column for it. `restore` records the playlist History rebuilt, because `playlist_uri` still names the temporary one that Chime out removed and that is a fact about what happened rather than a stale value to overwrite.
- `settings`: user_id, values (json): sources, explicit_ok, poll_seconds, default_keep

Retention note: `tracks` and `artists` cache Spotify metadata. Keep it minimal and refreshable, and re-read Spotify's Developer Policy on caching and retention before publishing the repo.

## 5. Song tagging and ranking (deterministic, no AI on Spotify content)
Spotify no longer exposes energy/tempo/valence, and Spotify content may not be fed to AI/ML models. So track "energy" comes from a rule pipeline:

1. ~~**Genres**: `GET /artists/{id}` gives artist genres.~~ **Gone as of Phase 3 (2026-09-21).** Spotify sent no `genres` key at all on any of the 808 artists in a real library — not an empty list, the field absent. The docs still list it as "Deprecated" rather than removed, so the code keeps reading it (`artists.genres` stays nullable, and `SpotifyGenreTagSource` still works if it ever comes back), but it supplies nothing today. That makes step 2 the only tag source rather than an optional extra.
2. **External tags** behind a `TagSource` interface. Phase 3 chose **MusicBrainz**: open data, no key, no account, ~1 request/second, and search hits carry their tags inline so one request tags one track. Last.fm was not needed. Sending titles to a non-AI tag service is fine; sending them to an LLM is not.
   - Recording tags are sparse (well-known songs often have none), so a miss falls back to the artist, cached per artist. On a real library: 83% of tracks tagged, 107 of 128 of those from the artist rather than the recording, 15% simply not in MusicBrainz.
   - Tag vote counts are weighted **relative to the entity's own top tag**, not against an absolute threshold: a famous artist collects 40 votes on its main genre and an obscure one collects 2, and both are that artist's consensus. Only the top 8 tags per entity are kept.
   - A tag's **rank** in that list also counts, in pairs: 1.0, 1.0, 0.55, 0.55, 0.3, 0.3, 0.15, 0.15 (`RANK_WEIGHTS`). The first two tags are what a thing *is*; the rest are qualifiers, moods and stray votes, and averaging eight of them flat pulls every track towards 3. Ignored tags do not consume a rank, or noise near the top would demote the real genre behind it. Ranks past the table are still recorded in `raw_tags` but do not score.
3. **Mapping table**: `data/tag_map.yaml` maps tag/genre -> `{energy, affinities}` (e.g. `ambient: {energy: 1, calm: .9, focus: .8}`; `hip hop: {energy: 4, workout: .7}`), plus `aliases` for spellings and an `ignore` list. A track's tags are the weighted average of its matches. Unknown = energy 3, confidence 0.
   - `ignore` holds real tags that carry no energy information — nationality, role, decade, release format, somebody's bookkeeping ("seen live"). They are skipped rather than counted as tags the map failed to understand; counting them halved confidence on well-tagged artists (mean 0.27 -> 0.47 on the same 150 tracks).
   - An unknown tag is read **through** to the longest known phrase inside it, at a 0.75 discount ("melodic death metal" -> death metal, "german hip hop" -> hip hop, rightmost match wins because English puts the head noun last). Tag vocabularies are open, so the long tail is mostly qualified spellings of things the map already has, and no hand-written map will ever enumerate them. On a real library this took mean confidence from 0.44 to 0.78 and rescued 32 tracks from unknown.
   - Confidence = coverage x strength: how much of the supplied tag weight the map understood, times how much understood weight there was. Ranking blends a track's energy towards neutral in proportion, so a badly tagged track neither wins nor loses on a guess.
   - `scripts/retag.py` re-applies the map to the whole library from `raw_tags` with no network, and writes `data/tag_influence.txt`: every map entry by how many tracks it tagged, with the energy it assigns. That is the file to edit when sessions feel wrong — the entries at the top decide most of the library, so an energy 0.5 out there moves hundreds of tracks.
4. **Manual override** (highest priority): user marks a track "calmer" or "more intense" from the UI -> `user_tracks.energy_override`.
5. **Behavior boost** (per user, plain arithmetic, no trained model): completions and keeps raise a bounded boost, fast skips (<10 s) lower it, decayed over time.

**Ranking**: `score = 0.50*energy_fit + 0.25*affinity(type) + 0.15*behavior_boost + 0.10*freshness`, where freshness penalizes tracks used in the last few sessions. Then shape the order to the energy curve, and avoid more than 2 tracks in a row from one artist. Store the per-component breakdown in `session_tracks.score_breakdown` so "Why this mix" and History can explain themselves.

Scoring and ordering are separate passes (`app/services/ranking.py`): a track's score must not depend on where it happens to land, and a workout that opens at 5 is not a workout. Ordering is greedy over the top `4 x count` scorers, minimising `|energy - target| - 2*score` per position. Two rules bend rather than break: a library that is mostly one artist gets a full playlist rather than a strict artist rule, and an untagged library still produces a session (every component falls back to 0.5, "no evidence", rather than 0).

Until `session_tracks` exists, freshness reads `user_tracks.last_played_at`; `rank(..., recent_track_ids=...)` is where Phase 4 passes the last few sessions in.

**Where /dev/rank fits**: Phase 3 builds all of this before there is a session or playback to hear it through, so `GET /api/dev/rank?mood=&type=&intent=&count=` and the `/dev/rank` screen show the profile, its curve, the pool's tag coverage and every track's breakdown. Read-only, behind the login, mounted only when `ENABLE_DEV_API`. Not part of the product.

**LLM use (allowed)**: given only non-Spotify inputs (body state, mood, type, day_part, and the *numeric* target profile), Claude can write the one-sentence "why this mix". Never include track or artist data in that prompt. Optional; template fallback when no API key.

**Discovery (Phase 8, optional)**: an LLM may propose artist + title pairs from its own knowledge given only mood/type/user-typed taste seeds (typed by the user, not pulled from Spotify), each resolved through `/search`. Off by default; a discovery slider caps the share.

## 6. Session engine
State machine: `created -> active -> ended(kept | removed)`, or `failed`.

**Chime in** (`POST /api/sessions {type, mood, intent}`):
1. Refresh WHOOP if daily data is older than 10 min (else use cache). If WHOOP is disconnected or fails, continue with mood + time only and say so.
2. Build body state, resolve `auto` type, compute target profile.
3. Rank candidates from allowed sources (settings), take about 25 tracks (~90 minutes max).
4. `POST /me/playlists` (private), name `Chime · <Type> · <time>`. Add items in chunks of 100 via `POST /playlists/{id}/items`.
5. Find a device (`GET /me/player/devices`), transfer if needed, and `PUT /me/player/play` with `context_uri`. If there is no open device, or Spotify refuses (no Premium, restricted device), **this is not a failure**: the session stays `created` and keeps its playlist, and the answer carries `needs_manual_start`, a reason written for the user, and `playlist_url`. The user presses play in Spotify — the app tries to open that tab for them and always shows the link — or, once Spotify is open, `POST /api/sessions/{id}/start` retries from here without building anything again. The first `GET /api/sessions/active` poll that sees our own playlist playing promotes the session to `active`. The refusals that *do* fail a Chime in are the ones that leave nothing usable: a playlist we could not fill, and an expired login.
6. Persist session, session_tracks, session_events. Return session + tracks + why_text.

**While active** (APScheduler, per active session; the whole loop is off when `ENABLE_SCHEDULER=false`, which is how the tests run and how a second process stays quiet):
- every `PLAYBACK_POLL_SECONDS` (default 20): read playback state, record track transitions into session_tracks (started_at, played_ms, skipped = moved on before ~10 s or before 30% played).
- every `SESSION_POLL_SECONDS` (default 300): evaluate adaptation.
- every `WHOOP_POLL_SECONDS` (default 900): refresh WHOOP, but only for users who have a live session — everything else reads body state on demand, and polling an idle user spends the 100/min, 10,000/day budget on an answer nobody asked for. A refresh that changed nothing is not recorded as an event.
- Adapt only on a trigger: mood re-check, readiness/day_part bucket change, 3+ skips in the last 5, or fewer than 3 upcoming tracks. Adapting means appending new tracks and removing *upcoming unplayed* ones. Never replace the whole playlist while it is playing. Test early whether editing a playing playlist interrupts playback; if it does, use the queue endpoint instead (`scripts/probe_playlist_edit.py` is that measurement, and needs a live session on a real device).

Phase 6 (2026-09-23) pinned these down, because measuring playback through a "what is playing now" endpoint is not the same as logging plays:
- **A song is judged only once playback has left it.** `played_ms` is the *highest* `progress_ms` ever seen for the row, so a seek backwards cannot lower it and a song shorter than one poll interval can be missed entirely. Every number Phase 6 produces is sampled, and a skip rate is an estimate.
- **Silence never counts.** A pause, an unreadable read, an expired grant, or playback on someone else's playlist leaves every row exactly as it was. Treating a failed read as a skip would poison the behaviour boost with the app's own outages.
- **Chime out closes the song it ended on without a verdict.** Stopping Chime is not rejecting a song, so that row keeps its `played_ms` and stays unjudged.
- **Skips and completions write `user_tracks.completes` / `fast_skips` / `kept_count`**, which is section 5 step 5 finally having data: 15% of the ranking score was inert before this phase.
- **Each trigger fires once per run of events, not once per tick.** The last `adapt` event is the watermark for all four, so the same three skips would otherwise re-trigger every five minutes and the mix would churn. An adaptation *adds before it removes* (a failed append leaves the playlist as it was; the other order can leave someone listening to a playlist that runs out), samples the target curve from where the session has got to rather than restarting it, and deletes the rows it trims so they never enter History's record of what was listened to. `sessions.target_profile` is not rewritten — it is the brief the session began with — so each adaptation records its own numbers on its own `adapt` event.

**Chime out** (`POST /api/sessions/{id}/end {keep, name?, mood_out}`):
1. Pause playback (optional per request). Take a final WHOOP snapshot into `body_out` (daily-level; expect small deltas).
2. Compute summary: minutes, tracks played, skips, skip rate. A session where nothing was measured reports played/skipped/skip_rate as **null** rather than zero — "0 played" is a claim about listening, when the fact is that nobody was counting — and every screen that shows a per-song outcome is gated on that.
3. If `keep`: rename via `PUT /playlists/{id}`. Else `DELETE /playlists/{id}/followers`, then confirm with `GET /me/library/contains` before setting `playlist_removed_at`. A removal that answers 200 and changes nothing is reported in `summary.problems` instead of being recorded as done — measured, not hypothetical: `DELETE /me/library` (what this said until 2026-09-22) needs two scopes we do not hold and left two real sessions claiming a tidy-up that never happened.
4. Session tracks stay in the DB either way. History can **bring it back** by recreating a playlist from `session_tracks`.

## 7. API surface (all under /api except auth)
`GET /auth/spotify/login`, `GET /auth/spotify/callback`, `GET /auth/whoop/login`, `GET /auth/whoop/callback`, `POST /auth/logout`
`GET /api/me`, `POST /api/library/sync`, `GET /api/library/status`, `GET /api/body-state`
`POST /api/sessions`, `GET /api/sessions/active`, `POST /api/sessions/{id}/start`, `POST /api/sessions/{id}/mood`, `POST /api/sessions/{id}/end`, `GET /api/sessions` (filters: type, mood_in, kept, from, to, include_failed; paged with limit/offset), `GET /api/sessions/week`, `GET /api/sessions/{id}`, `POST /api/sessions/{id}/restore`, `DELETE /api/sessions/{id}`

History notes (Phase 5): `from`/`to` are whole days and `to` is inclusive; a `failed` session is left out of the list and the week summary unless `include_failed`, because it played nothing. Minutes come off `sessions.summary` for a finished session and off the clock only for a live one, so an old row reads the same today as it did the day it ended. `GET /api/sessions/{id}` carries the `session_events` timeline; the list does not, and neither does `/active`. `restore` creates a new playlist that *stays* in the library and never touches `playlist_uri`. `DELETE` refuses a live session (409) and never touches Spotify: a kept playlist belongs to the user.
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
- ~~Required scope for `DELETE /me/library` on a playlist URI.~~ **Answered 2026-09-22:** all three of `user-library-modify`, `user-follow-modify`, `playlist-modify-public`, which is why Chime uses `DELETE /playlists/{id}/followers` instead (section 6, Chime out). Also found: the `public` field reads back `true` on a playlist created with `public: false`, and stays `true` after an explicit `PUT`, while the create response itself echoes `false` — Spotify's read side appears unreliable here, so do not treat that field as evidence either way.
- Whether editing a playing playlist interrupts playback.
- WHOOP cycle endpoint freshness during the day, and whether the current cycle's strain updates live.
- Last.fm / MusicBrainz coverage for the user's actual library (Phase 3 spike).
