# Prompt 05: History

## Before you paste this (human checklist)
1. Chime in and out at least three times so there is something to look at — ideally different session types, one kept and one removed.
2. At least one of those sessions should have a mood in *and* a mood out, so the "Entered / Left" rows have both halves.
3. Run Claude Code from the project root, then paste everything below the line.

---

Read `CLAUDE.md` fully, then `docs/SPEC.md` (sections 4, 6, 7), the History and Session detail parts of `docs/DESIGN.md`, and Phase 5 of `docs/PLAN.md`. Read `backend/app/models/session.py`, `backend/app/services/sessions.py` and `backend/app/api/routes/sessions.py` before writing anything: Phase 4 already stores everything History reads, and this phase should add no columns to `sessions` or `session_tracks`.

**Do not write code yet.** First reply with:
1. A short plan (files/modules you will create or change, in order).
2. Anything in these docs that looks wrong against what Phase 4 actually stored.
3. Questions, if any (max 3).

Wait for my OK. After my OK, build Phase 5 as follows.

## Goal
Every session I have ever run, grouped by day, filterable, with a detail page that explains itself months later — and a way to bring a removed playlist back from our own data.

## Build

**Backend**
- `GET /api/sessions` — list, newest first. Filters from SPEC section 7: `type`, `mood_in`, `kept`, `from`, `to`, plus `limit` (default 20, max 100) and `offset`. Returns a light row per session: id, type, intent, mood_in, mood_out, started_at, ended_at, minutes, queued count, played/skipped when measured, kept, playlist_removed_at, `why_text`, up to four `image_url`s for the artwork strip, and the recovery/sleep figures out of `body_in` that the card prints. No track list and no profile — that is what the detail endpoint is for.
  - `failed` sessions are excluded by default (nothing played, so they are noise); `?include_failed=true` shows them. A live session is included, so History is never mysteriously missing the thing playing right now.
- `GET /api/sessions/week` — the quiet summary above the list: sessions, total minutes, and the most common mood shift (`mood_in -> mood_out` pair) over the last seven days. Ignores the list's filters. Say plainly in the response when there is nothing to summarise rather than sending zeroes that look like a measurement.
- `GET /api/sessions/{id}` — extend the existing response with the `session_events` timeline (ts, type, payload) so Session detail can draw it. Keep the live Session screen's shape unchanged apart from the added field.
- `POST /api/sessions/{id}/restore` — "Bring it back". Create a **new** private playlist from `session_tracks` in `position` order (`POST /me/playlists`, then items in chunks of 100 via `POST /playlists/{id}/items`), named after the original where there is one. It is an explicit save, so it stays in the library — do not schedule it for removal. Do not touch `sessions.playlist_uri` (that playlist is gone); record the new URI on a `session_event` and read the latest one back on the detail page. Return the new URI and its web URL.
- `DELETE /api/sessions/{id}` — "Delete this record" from DESIGN, not in SPEC's list. Cascades to tracks and events. Refuse with 409 while the session is live. It does not touch Spotify: a kept playlist is the user's now.
- Put the reading and the restoring in `app/services/history.py`; keep the routes thin. Reuse `sessions.summarise` rather than recomputing minutes a second way.

**Frontend**
- `/history`: week summary card, the filter chip row from DESIGN (All, the four session types, Kept), the list grouped by local day with Today / Yesterday / weekday headings, `EmptyState` when there is nothing, and a "Load more" that pages by offset. Filters live in the URL query string so a filtered list can be linked and survives a reload.
- `components/SessionCard.tsx`, built once and reused on `/history` and as the real Home last-session card (which is a placeholder today). Left edge carries the 4 px bar in the session hue; Entered / Left are two aligned rows.
- `/history/:id` Session detail: hue header with name, date and duration; a **before and after** panel (mood in -> out, recovery/HRV/sleep at the start, day strain start -> end) that states in one line that WHOOP scores a day rather than a moment, so a short session shows little; Why this mix (reuse the Phase 4 panel); the full song list (reuse `TrackRow`) with energy dots and a thin outcome bar; the timeline from `session_events`; "Bring it back" and "Delete this record" with a confirmation.
- Grouping and all date formatting happen in the browser's local time from the ISO timestamps. Do not invent a timezone on the server.
- **Honesty, as in Phase 4:** played, skipped and per-song outcomes are null until the Phase 6 poller measures them. Omit them — no zeroes, no empty bars pretending a song was skipped at 0:00.

**Tests**
- Backend (pytest + respx): each list filter, the default exclusion of `failed`, pagination, week summary including the empty case, restore (chunking and the event it writes), delete including the 409 while live. No real network.
- `uv run pytest`, `npm run typecheck`, `npm run lint`, `npm run build` all pass.

## Allowed dependencies (ask before adding others)
None. Everything here is already installed; `useInfiniteQuery` is part of the TanStack Query already in use.

## Out of scope
Playback polling, skip capture and adaptation (Phase 6). Insights. Settings screens. Any new column on `sessions` or `session_tracks` — if History seems to need one, stop and say so instead of adding it.

## Definition of done
- I can open `/history`, see my real sessions grouped by day, filter to one type and to Kept, and open one.
- On a detail page I can see how I entered and left, why the mix was built that way, every song, the timeline, and I can bring a removed playlist back and then find it in Spotify.
- Home's last-session card shows the real last session.
- `docs/PLAN.md` Phase 5 is ticked, and your final message lists: what changed, how to run it, what I should click to verify, and anything you were unsure about.
