import { Link } from 'react-router-dom'

import { dayLabel, duration, timeLabel } from '../../lib/dates'
import { useSessionList } from '../../lib/queries'
import { hueFor, moodLabel, typeLabel } from '../../lib/types'

/**
 * The last session that finished: type, length, and how the mood moved.
 *
 * Asks for three and takes the first finished one: a session that is still running is already
 * on this screen as the orb, and offering it here as "last session" would be reading the same
 * thing twice.
 */
export function LastSessionCard() {
  const { data } = useSessionList({}, 3)
  const recent = data?.pages[0]?.sessions ?? []
  const session = recent.find((candidate) => candidate.status === 'ended') ?? null

  if (!session) {
    return (
      <section className="glass flex flex-col gap-1 rounded-sheet px-5 py-[18px]">
        <h2 className="text-[15px] font-[650]">No sessions yet</h2>
        <p className="text-caption text-fog">Your most recent one sits here once you chime in.</p>
      </section>
    )
  }

  const hue = hueFor(session.type)
  const from = moodLabel(session.mood_in)
  const to = moodLabel(session.mood_out)
  // "yesterday, 7:15 PM" mid-sentence, but a date like "Mon 3 Sep" keeps its capitals.
  const day = dayLabel(session.started_at)
  const midSentence = from !== null && (day === 'Today' || day === 'Yesterday')
  const when = `${midSentence ? day.toLowerCase() : day}, ${timeLabel(session.started_at)}`

  return (
    <Link
      to={`/history/${session.id}`}
      aria-label={`Last session: ${typeLabel(session.type)}, ${duration(session.minutes)}`}
      className="glass flex flex-col gap-2.5 rounded-sheet px-5 py-[18px] transition-colors hover:bg-white/8 focus-visible:rounded-sheet"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[15px] font-[650]">
          <span aria-hidden="true" className="size-2 rounded-full" style={{ background: hue }} />
          {typeLabel(session.type)}
          {session.kept ? <span className="text-caption font-medium text-fog">· kept</span> : null}
        </span>
        <span className="text-caption text-fog">{duration(session.minutes)}</span>
      </div>
      <p className="text-caption text-fog">
        {from && to ? (
          <>
            {from} <span className="text-mist">→</span> {to} ·{' '}
          </>
        ) : from ? (
          `${from} · `
        ) : null}
        {when}
      </p>
    </Link>
  )
}
