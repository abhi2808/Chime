import { StatFigure } from '../../components/StatFigure'
import { duration } from '../../lib/dates'
import { useWeekSummary } from '../../lib/queries'
import { moodLabel } from '../../lib/types'

/**
 * The last seven days in three figures.
 *
 * The backend sends a `note` for the two cases a number cannot cover — a week with nothing
 * in it, and a week whose sessions never recorded a second mood — and it is shown verbatim
 * rather than dressed up as a zero.
 */
export function WeekCard() {
  const { data: week } = useWeekSummary()
  if (!week) return null

  const from = moodLabel(week.shift_from)
  const to = moodLabel(week.shift_to)

  return (
    <section className="glass flex flex-col gap-3 rounded-sheet px-screen py-5">
      <span className="text-caption text-fog">This week</span>

      {week.sessions === 0 ? (
        <p className="text-body text-fog">{week.note}</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-x-8 gap-y-4">
            <StatFigure
              label="Sessions"
              value={String(week.sessions)}
              hint={`in ${week.days} days`}
            />
            <StatFigure label="Listening" value={duration(week.minutes)} />
            {from && to ? (
              <StatFigure
                label="Most often"
                value={`${from} → ${to}`}
                hint={week.shift_count > 1 ? `${week.shift_count} times` : 'once'}
              />
            ) : null}
          </div>
          {week.note ? <p className="text-caption text-fog">{week.note}</p> : null}
        </>
      )}
    </section>
  )
}
