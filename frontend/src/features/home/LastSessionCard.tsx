import { ListMusic } from 'lucide-react'
import { Link } from 'react-router-dom'

import { dayLabel, duration, timeLabel } from '../../lib/dates'
import { useSessionList } from '../../lib/queries'
import { hueFor, moodLabel, typeLabel } from '../../lib/types'

/**
 * The last session that finished, and a way into the rest of them.
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
      <section className="glass rounded-sheet px-screen flex flex-col gap-1 py-5">
        <span className="text-caption flex items-center gap-2 text-fog">
          <ListMusic aria-hidden="true" size={14} />
          Last session
        </span>
        <h2 className="text-headline">Nothing here yet</h2>
        <p className="text-caption text-fog">
          Your most recent session will sit here once you have chimed in.
        </p>
      </section>
    )
  }

  const hue = hueFor(session.type)
  const from = moodLabel(session.mood_in)
  const to = moodLabel(session.mood_out)

  return (
    <Link
      to={`/history/${session.id}`}
      className="glass rounded-sheet px-screen flex flex-col gap-1 py-5 transition-colors hover:bg-white/6"
    >
      <span className="text-caption flex items-center gap-2 text-fog">
        <ListMusic aria-hidden="true" size={14} />
        Last session
      </span>
      <h2 className="text-headline flex items-center gap-2">
        <span aria-hidden="true" className="size-2 rounded-full" style={{ background: hue }} />
        {typeLabel(session.type)}
        {session.kept ? <span className="text-caption text-fog">· kept</span> : null}
      </h2>
      <p className="text-caption text-fog">
        {dayLabel(session.started_at)}, {timeLabel(session.started_at)} ·{' '}
        {duration(session.minutes)} ·{' '}
        {session.played !== null ? `${session.played} played` : `${session.queued} queued`}
        {from && to ? ` · ${from} → ${to}` : ''}
      </p>
    </Link>
  )
}
