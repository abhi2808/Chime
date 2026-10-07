/** Mirrors of the backend response models in app/schemas. */

export interface Connections {
  spotify: boolean
  whoop: boolean
}

export interface Me {
  id: number
  display_name: string | null
  spotify_user_id: string | null
  created_at: string
  connections: Connections
}

/**
 * "partial" means the run stopped on purpose — Spotify rate limited us, or the artist
 * phase used up its time budget — and everything it did fetch is stored and usable.
 * "interrupted" means a previous run died mid-way and the next sync resumes it.
 */
export type SyncState =
  | 'never'
  | 'idle'
  | 'running'
  | 'complete'
  | 'partial'
  | 'error'
  | 'interrupted'

export interface LibrarySyncStatus {
  state: SyncState
  phase: 'tracks' | 'artists' | null
  mode: string | null
  tracks_synced: number
  tracks_total: number | null
  artists_fetched: number
  artists_total: number
  artists_failed: number
  artists_remaining: number
  liked_tracks: number
  artists_with_genres: number
  stopped_early: boolean
  error: string | null
  started_at: string | null
  finished_at: string | null
  /** When Spotify said it would answer again; null when nothing is waiting on a limit. */
  resume_after: string | null
}

export interface SyncStartResponse extends LibrarySyncStatus {
  started: boolean
}

export type Readiness = 'low' | 'medium' | 'high'

export type DayPart = 'late_night' | 'early_morning' | 'morning' | 'afternoon' | 'evening'

/**
 * Today's body context. Every figure is nullable: WHOOP fills a day in over time, so a
 * day mid-morning legitimately has strain but no recovery yet, and the whole thing is
 * absent when WHOOP is not connected. `note` is written to be shown verbatim.
 */
export interface BodyState {
  connected: boolean
  has_data: boolean
  day_part: DayPart
  recovery: number | null
  hrv_ms: number | null
  rhr: number | null
  sleep_performance: number | null
  day_strain: number | null
  minutes_since_last_workout: number | null
  readiness: Readiness | null
  calibrating: boolean
  /** The member's own date for the WHOOP day, which starts when they wake. */
  date: string | null
  fetched_at: string | null
  note: string | null
  /** The stored grant is dead: offer reconnect rather than refresh. */
  needs_reconnect: boolean
}

export const MOODS = ['Wired', 'Drained', 'Flat', 'Steady', 'Fired up'] as const
export type Mood = (typeof MOODS)[number]

/** What the API calls a mood. `MOODS` above are the labels shown on screen. */
export type MoodId = 'wired' | 'drained' | 'flat' | 'steady' | 'fired_up'

export function moodId(mood: Mood): MoodId {
  return mood.toLowerCase().replace(' ', '_') as MoodId
}

/** What the API calls a mood, turned back into the label on screen. */
export function moodLabel(mood: MoodId | null): string | null {
  if (!mood) return null
  const found = MOODS.find((option) => moodId(option) === mood)
  return found ?? null
}

/**
 * `match` takes the mix to where the body already is; `shift` moves it somewhere else.
 * Shift changes the energy curve, not the session type — so it does not change the hue.
 */
export type Intent = 'match' | 'shift'

export const INTENTS: readonly { id: Intent; label: string }[] = [
  { id: 'match', label: 'Here' },
  { id: 'shift', label: 'Somewhere else' },
]

/** Session hues live in tokens.css; `hue` is the CSS variable name. */
export interface SessionType {
  id: 'auto' | 'workout' | 'focus' | 'wind_down' | 'wake_up'
  label: string
  hue: string
}

export const SESSION_TYPES: readonly SessionType[] = [
  { id: 'auto', label: 'Auto', hue: 'var(--color-ember)' },
  { id: 'workout', label: 'Workout', hue: 'var(--color-ember)' },
  { id: 'focus', label: 'Focus', hue: 'var(--color-moss)' },
  { id: 'wind_down', label: 'Wind down', hue: 'var(--color-indigo)' },
  { id: 'wake_up', label: 'Wake up', hue: 'var(--color-amber)' },
]

/** The hue a session type owns. Auto has no hue of its own until the engine resolves it. */
export function hueFor(type: string | null | undefined): string {
  return SESSION_TYPES.find((option) => option.id === type)?.hue ?? 'var(--color-ember)'
}

export function typeLabel(type: string): string {
  return SESSION_TYPES.find((option) => option.id === type)?.label ?? type
}

// --- Ranking preview (dev only; /api/dev/rank) -------------------------------------

/** Why a track is where it is. Each component is 0-1; 0.5 means "no evidence". */
export interface ScoreBreakdown {
  energy_fit: number
  affinity: number
  behavior: number
  freshness: number
  score: number
  energy: number
  confidence: number
  /** Target energy at this position, so the curve can be read against what it got. */
  target: number
  tags: string[]
}

export interface RankedTrack {
  position: number
  track_id: number
  spotify_track_id: string
  name: string
  artists: string[]
  score: number
  breakdown: ScoreBreakdown
}

/** `TargetProfile.as_dict()` on the backend. */
export interface TargetProfile {
  type: Exclude<SessionType['id'], 'auto'>
  intent: Intent
  mood: MoodId | null
  energy_start: number
  energy_end: number
  ceiling: number
  floor: number
  ease_off: number
  affinities: Record<string, number>
  curve: number[]
  /** Plain-language reasons, in the order the engine applied them. */
  notes: string[]
}

export interface PoolSummary {
  size: number
  tagged: number
  untagged: number
  mean_confidence: number
}

export interface RankPreview {
  body: BodyState
  profile: TargetProfile
  pool: PoolSummary
  tracks: RankedTrack[]
}

// --- Sessions (/api/sessions) ------------------------------------------------------

/** `created` and `active` are both live; `failed` is a Chime in that never got playing. */
export type SessionStatus = 'created' | 'active' | 'ended' | 'failed'

/** The body snapshot stored on a session. A subset of `BodyState`: no note, no cache age. */
export interface SessionBody {
  connected: boolean
  has_data: boolean
  day_part: DayPart
  recovery: number | null
  hrv_ms: number | null
  rhr: number | null
  sleep_performance: number | null
  day_strain: number | null
  minutes_since_last_workout: number | null
  readiness: Readiness | null
  calibrating: boolean
  date: string | null
}

export interface SessionTrack {
  position: number
  track_id: number
  spotify_track_id: string
  name: string
  artists: string[]
  album: string | null
  image_url: string | null
  duration_ms: number
  /** `'library'` if the ranking chose it at Chime in, `'adapt'` if it was added mid-session. */
  source: string
  /**
   * When playback first reached this song, or null.
   *
   * Null is ambiguous on its own: it means "never reached" on a measured session and "nobody
   * was counting" on an unmeasured one. Use the summary's `played` to tell them apart before
   * showing anything per song.
   */
  started_at: string | null
  /** The furthest into the song playback was seen. Sampled, so a floor, not an exact total. */
  played_ms: number
  /** Left early, judged once playback moved on. Never set for the song a session ended on. */
  skipped: boolean
  /** The track's energy and the target at this position, for Why this mix. */
  energy: number | null
  target: number | null
}

/** Counts are null while unmeasured, which is honest rather than claiming zero. */
export interface SessionSummary {
  minutes: number
  queued: number
  played: number | null
  skipped: number | null
  skip_rate: number | null
  /** Anything that went wrong at Chime out and is worth saying out loud. */
  problems: string[]
  abandoned: boolean
}

export type SessionEventType =
  | 'mood_check'
  | 'whoop_refresh'
  | 'adapt'
  | 'error'
  | 'manual_start'
  | 'restore'

/** One line of a session's timeline. `payload` is ours, so a screen reads the keys it knows. */
export interface SessionEvent {
  ts: string
  /**
   * The list above plus whatever a later phase adds. Left open on purpose: this is a wire
   * format, and a screen that pretends the set is closed cannot handle a new kind of entry.
   */
  type: SessionEventType | (string & {})
  payload: Record<string, unknown> | null
}

export interface Session {
  id: number
  status: SessionStatus
  type: string
  intent: Intent
  mood_in: MoodId | null
  mood_out: MoodId | null
  started_at: string
  ended_at: string | null
  playlist_uri: string | null
  playlist_name: string | null
  playlist_url: string | null
  kept: boolean
  why_text: string | null
  profile: TargetProfile | null
  body_in: SessionBody | null
  body_out: SessionBody | null
  summary: SessionSummary | null
  tracks: SessionTrack[]
  /** Where Chime in ended up playing. Only present on the response that started it. */
  device_name: string | null
  /**
   * The mix is built and in the playlist, but Spotify would not let Chime press play —
   * nothing open to play on, or no Premium. `playlist_url` is where to press it by hand,
   * and `POST /api/sessions/{id}/start` is the retry once Spotify is open.
   */
  needs_manual_start: boolean
  /** Written to be shown verbatim. */
  manual_start_reason: string | null
  manual_start_code: ManualStartCode | null
  /** The timeline. Only filled in by `GET /api/sessions/{id}`, empty on the live poll. */
  events: SessionEvent[]
  /**
   * Where History put this session when it was brought back. `playlist_url` still refers to
   * the playlist the session originally made, which is usually gone.
   */
  restored_playlist_url: string | null
  restored_playlist_name: string | null
}

export type ManualStartCode =
  | 'NO_ACTIVE_DEVICE'
  | 'PREMIUM_REQUIRED'
  | 'DEVICE_RESTRICTED'
  | 'PLAYBACK_REFUSED'

/** A read of Spotify's player, for the mini player and the session artwork. */
export interface NowPlaying {
  is_playing: boolean
  progress_ms: number | null
  spotify_track_id: string | null
  name: string | null
  artists: string[]
  image_url: string | null
  duration_ms: number
  device_name: string | null
  /** True when playback has wandered off this session's playlist. */
  off_context: boolean
}

export interface ActiveSession {
  session: Session | null
  playing: NowPlaying | null
  /** Why there is no playback to report, in the user's words. Shown verbatim. */
  note: string | null
}

export interface ChimeInRequest {
  mood: MoodId | null
  type: SessionType['id']
  intent: Intent
  count?: number
}

export interface ChimeOutRequest {
  keep: boolean
  name?: string | null
  mood_out?: MoodId | null
  pause?: boolean
}

export type Transport = 'next' | 'previous' | 'pause' | 'resume'

// --- History (/api/sessions) -------------------------------------------------------

/**
 * A session as a card. Lighter than `Session` on purpose: the list draws figures and a few
 * covers, and does not need every track, both body snapshots and the target profile.
 */
export interface SessionListItem {
  id: number
  status: SessionStatus
  type: string
  intent: Intent
  mood_in: MoodId | null
  mood_out: MoodId | null
  started_at: string
  ended_at: string | null
  playlist_name: string | null
  /** Null once Chime out removed the playlist: the link would lead nowhere. */
  playlist_url: string | null
  kept: boolean
  why_text: string | null
  minutes: number
  queued: number
  /** Null means nothing measured this session, not that nothing played. */
  played: number | null
  skipped: number | null
  /** Up to four distinct covers, in playing order. */
  images: string[]
}

export interface SessionListPage {
  sessions: SessionListItem[]
  /** The filtered count, so "load more" knows when it has everything. */
  total: number
  limit: number
  offset: number
}

/** Anything unset is left off the query string, so the backend keeps its own defaults. */
export interface SessionFilters {
  type?: string
  mood_in?: MoodId
  kept?: boolean
  from?: string
  to?: string
}

/** `note` is set when there is nothing to count, or nothing to say about mood. */
export interface WeekSummary {
  days: number
  sessions: number
  minutes: number
  shift_from: MoodId | null
  shift_to: MoodId | null
  shift_count: number
  note: string | null
}

/** What `POST /api/sessions/{id}/restore` gives back: a new playlist that stays. */
export interface RestoredPlaylist {
  playlist_uri: string
  playlist_url: string
  name: string
  tracks: number
}
