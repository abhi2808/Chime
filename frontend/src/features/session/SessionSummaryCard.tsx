import { Link } from 'react-router-dom'

import { StatFigure } from '../../components/StatFigure'
import { percent, strain } from '../../lib/body'
import { moodLabel, typeLabel } from '../../lib/types'
import type { Session } from '../../lib/types'

/**
 * What just happened, then back to Home.
 *
 * Counts that were never measured are left out rather than shown as zero — the session knows
 * how many songs it queued, and claiming it knows how many played would be a lie.
 */
export function SessionSummaryCard({ session, hue }: { session: Session; hue: string }) {
  const summary = session.summary
  const start = session.body_in
  const from = moodLabel(session.mood_in)
  const to = moodLabel(session.mood_out)

  return (
    <div className="fade-enter flex flex-col gap-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <span
          aria-hidden="true"
          className="size-3 rounded-full"
          style={{ background: hue, boxShadow: `0 0 28px ${hue}` }}
        />
        <h1 className="text-title">That's a wrap</h1>
        <p className="text-body text-fog">
          {typeLabel(session.type)}
          {session.kept ? ' · playlist kept' : ' · playlist removed'}
        </p>
      </div>

      <div className="glass flex flex-wrap gap-x-8 gap-y-4 rounded-tile p-4">
        {summary ? <StatFigure label="Time" value={`${summary.minutes} min`} /> : null}
        {summary ? (
          <StatFigure
            label="Songs"
            value={summary.played !== null ? String(summary.played) : String(summary.queued)}
            hint={summary.played !== null ? 'played' : 'queued'}
          />
        ) : null}
        {summary?.skipped !== null && summary?.skipped !== undefined ? (
          <StatFigure
            label="Skips"
            value={String(summary.skipped)}
            hint={
              summary.skip_rate !== null
                ? `${percent(summary.skip_rate * 100)} of plays`
                : undefined
            }
          />
        ) : null}
        {from || to ? (
          <StatFigure
            label="Mood"
            value={from && to ? `${from} → ${to}` : (to ?? from ?? '')}
            hint={from && to ? undefined : 'no second check-in'}
          />
        ) : null}
      </div>

      {start?.connected ? (
        <p className="text-caption text-fog">
          At the start:{' '}
          {[
            percent(start.recovery) && `recovery ${percent(start.recovery)}`,
            percent(start.sleep_performance) && `sleep ${percent(start.sleep_performance)}`,
            strain(start.day_strain) && `strain ${strain(start.day_strain)}`,
          ]
            .filter(Boolean)
            .join(' · ') || 'WHOOP had not scored the day yet'}
          .
        </p>
      ) : null}

      {summary?.abandoned ? (
        <p className="text-caption text-fog">
          This session was still open from earlier, so it was closed without a check-out.
        </p>
      ) : null}

      {summary && summary.problems.length > 0 ? (
        <ul className="text-caption flex flex-col gap-1 text-danger">
          {summary.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}

      <Link
        to="/"
        className="text-body min-h-tap grid place-items-center rounded-full font-semibold text-midnight transition-opacity hover:opacity-90"
        style={{ background: hue }}
      >
        Back to home
      </Link>
    </div>
  )
}
