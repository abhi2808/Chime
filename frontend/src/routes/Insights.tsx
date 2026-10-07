import { Link } from 'react-router-dom'

import { WeekCard } from '../features/history/WeekCard'

/**
 * The week in figures. The day-level insights in PLAN's Phase 8 (skip rate by mix type,
 * next-morning recovery after a wind down) are not built, so this screen says so rather than
 * standing empty behind a petal.
 */
export function Insights() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title">Insights</h1>
      <WeekCard />
      <section className="glass flex flex-col gap-1 rounded-sheet px-screen py-5">
        <h2 className="text-headline">More to come</h2>
        <p className="text-caption text-fog">
          Which mixes you skip least, and how you recover the morning after a wind down, land
          here once there are enough sessions to say anything honest.
        </p>
        <Link
          to="/history"
          className="text-caption min-h-tap flex items-center self-start text-fog underline decoration-hairline underline-offset-4 hover:text-mist"
        >
          See every session in History
        </Link>
      </section>
    </div>
  )
}
