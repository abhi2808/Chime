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
