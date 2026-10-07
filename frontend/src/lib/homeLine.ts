import type { BodyState, DayPart, Readiness } from './types'

/**
 * The one plain sentence under the orb on Home: what the body and the clock say, and the kind
 * of mix that would fit. Deterministic, from `/api/body-state` alone.
 *
 * It is a hint, not a prediction of what Chime in will build — the mood in the sheet can
 * change the answer — so it names a feel ("slow, warm") rather than a session type.
 */

const RECOVERY: Record<Readiness, string> = {
  low: 'Low recovery',
  medium: 'Middling recovery',
  high: 'Strong recovery',
}

const WHEN: Record<DayPart, string> = {
  late_night: 'a late night',
  early_morning: 'an early start',
  morning: 'the morning',
  afternoon: 'the afternoon',
  evening: 'a late evening',
}

function fit(part: DayPart, readiness: Readiness | null): string {
  switch (part) {
    case 'early_morning':
    case 'morning':
      return readiness === 'low' ? 'A soft lift into the day would fit.' : 'A bright lift into the day would fit.'
    case 'afternoon':
      return readiness === 'low' ? 'Something easy and steady would fit.' : 'Something steady to work to would fit.'
    default:
      return 'A slow, warm mix would fit.'
  }
}

// Mirrors RECENT_WORKOUT_MINUTES in backend/app/services/profile_rules.py.
const RECENT_WORKOUT_MINUTES = 60

export function homeLine(state: BodyState | undefined): string | null {
  if (!state) return null

  const since = state.minutes_since_last_workout
  if (since !== null && since <= RECENT_WORKOUT_MINUTES) {
    return 'Fresh off a workout. Something that brings you back down would fit.'
  }

  const part = state.day_part
  if (!state.connected || !state.readiness) {
    const when = WHEN[part]
    return `${when.charAt(0).toUpperCase()}${when.slice(1)}. ${fit(part, null)}`
  }

  return `${RECOVERY[state.readiness]} and ${WHEN[part]}. ${fit(part, state.readiness)}`
}
