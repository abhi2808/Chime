import { StatFigure } from '../../components/StatFigure'
import { percent, strain } from '../../lib/body'
import { useBodyState } from '../../lib/queries'
import type { Session } from '../../lib/types'

/**
 * What the body looked like when the session started, and the one figure that moves during
 * it. Recovery and sleep are scored once a day, so showing them "now" would be the same
 * number pretending to be new; strain climbs as the day goes on, so it gets both readings.
 */
export function BodyPanel({ session }: { session: Session }) {
  const { data: now } = useBodyState()
  const start = session.body_in

  if (!start || !start.connected) {
    return (
      <section className="flex flex-col gap-2">
        <h2 className="text-headline">Body</h2>
        <p className="text-body text-fog">
          WHOOP isn't connected, so this mix uses your mood and the time of day.
        </p>
      </section>
    )
  }

  const recovery = percent(start.recovery)
  const sleep = percent(start.sleep_performance)
  const strainAtStart = strain(start.day_strain)
  const strainNow = strain(now?.day_strain ?? null)
  const moved = strainNow !== null && strainNow !== strainAtStart

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-headline">Body</h2>
      <div className="glass flex flex-wrap gap-x-8 gap-y-4 rounded-tile p-4">
        {recovery ? <StatFigure label="Recovery" value={recovery} hint="at start" /> : null}
        {sleep ? <StatFigure label="Sleep" value={sleep} hint="at start" /> : null}
        {strainAtStart ? (
          <StatFigure
            label="Strain"
            value={moved ? `${strainAtStart} → ${strainNow}` : strainAtStart}
            hint={moved ? 'since you started' : 'at start'}
          />
        ) : null}
        {!recovery && !sleep && !strainAtStart ? (
          <p className="text-body text-fog">WHOOP hadn't scored today yet when this started.</p>
        ) : null}
      </div>
      <p className="text-caption text-fog">
        WHOOP updates through the day, so a short session shows little change.
      </p>
    </section>
  )
}
