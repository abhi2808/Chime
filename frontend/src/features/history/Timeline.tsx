import { timeLabel } from '../../lib/dates'
import { moodLabel } from '../../lib/types'
import type { MoodId, SessionEvent } from '../../lib/types'

/**
 * What happened during a session, in the order it happened.
 *
 * Every line is written here rather than stored, except the ones whose payload already holds
 * a sentence meant for a person (a refused play, an error). An event type this does not know
 * is still shown: the timeline is append-only and a new kind of entry should appear as
 * something rather than silently vanish.
 */
export function Timeline({ events }: { events: SessionEvent[] }) {
  if (events.length === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-headline">Timeline</h2>
      <ol className="flex flex-col gap-2">
        {events.map((event, index) => (
          <li key={`${event.ts}-${index}`} className="flex gap-3">
            <span className="text-caption w-16 shrink-0 text-fog tabular-nums">
              {timeLabel(event.ts)}
            </span>
            <span className="text-caption text-fog">{describe(event)}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function describe(event: SessionEvent): string {
  const payload = event.payload ?? {}
  switch (event.type) {
    case 'mood_check': {
      const mood = moodLabel(payload.mood as MoodId)
      return mood ? `Checked in: ${mood.toLowerCase()}` : 'Checked in'
    }
    case 'whoop_refresh':
      return 'WHOOP data refreshed'
    case 'adapt': {
      const added = count(payload.added)
      const removed = count(payload.removed)
      const what =
        added && removed
          ? `Swapped in ${songs(added)} for ${removed} that hadn't played`
          : added
            ? `Added ${songs(added)} to the queue`
            : 'Reworked the queue'
      const why = triggers(payload.triggers)
      return why ? `${what} — ${why}` : what
    }
    case 'manual_start':
      return text(payload.message) ?? 'Spotify would not start on its own'
    case 'restore': {
      const name = text(payload.name)
      return name ? `Brought back as "${name}"` : 'Brought back as a playlist'
    }
    case 'error':
      return text(payload.message) ?? 'Something went wrong'
    default:
      return event.type.replace(/_/g, ' ')
  }
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function songs(n: number): string {
  return `${n} song${n === 1 ? '' : 's'}`
}

/** The four reasons the mix changes mid-session (SPEC section 6), in a person's words. */
const REASONS: Record<string, string> = {
  mood: 'you checked in again',
  body: 'your body data had moved',
  skips: 'a run of skips',
  running_out: 'it was running out',
}

/** An unknown reason is dropped rather than printed raw: a bare slug reads like a bug. */
function triggers(value: unknown): string | null {
  if (!Array.isArray(value)) return null
  const words = value.map((reason) => REASONS[String(reason)]).filter(Boolean)
  return words.length > 0 ? words.join(' and ') : null
}
