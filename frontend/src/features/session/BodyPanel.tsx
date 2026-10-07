import { percent, strain } from '../../lib/body'
import { useBodyState } from '../../lib/queries'
import type { Session } from '../../lib/types'

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass flex flex-1 flex-col gap-0.5 rounded-tile px-3.5 py-3">
      <span className="text-[11px] text-fog">{label}</span>
      <span className="text-base font-bold tabular-nums">{value}</span>
    </div>
  )
}

/**
 * Three tiles: recovery and sleep as they were when the session started, and strain now.
 * Recovery and sleep are scored once a day, so showing them "now" would be the same number
 * pretending to be new; strain climbs as the day goes on, so it is the one live figure, and
 * it says where it started from when it has moved.
 */
export function BodyPanel({ session }: { session: Session }) {
  const { data: now } = useBodyState()
  const start = session.body_in

  if (!start || !start.connected) {
    return (
      <p className="text-caption text-fog">
        WHOOP isn't connected, so this mix runs on your mood and the time of day.
      </p>
    )
  }

  const recovery = percent(start.recovery)
  const sleep = percent(start.sleep_performance)
  const strainAtStart = strain(start.day_strain)
  const strainNow = strain(now?.day_strain ?? null) ?? strainAtStart
  const moved = strainNow !== null && strainAtStart !== null && strainNow !== strainAtStart

  if (!recovery && !sleep && !strainNow) {
    return <p className="text-caption text-fog">WHOOP hadn't scored today yet when this started.</p>
  }

  return (
    <section aria-label="Body" className="flex flex-col gap-2">
      <div className="flex gap-2.5">
        {recovery ? <Tile label="Recovery" value={recovery} /> : null}
        {sleep ? <Tile label="Sleep" value={sleep} /> : null}
        {strainNow ? <Tile label="Strain now" value={strainNow} /> : null}
      </div>
      <p className="text-caption text-fog">
        {moved ? `Strain was ${strainAtStart} when you started. ` : ''}
        Recovery and sleep are from the start; WHOOP scores them once a day.
      </p>
    </section>
  )
}
