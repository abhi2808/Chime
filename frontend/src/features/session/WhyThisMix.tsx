import { ChevronDown } from 'lucide-react'

import { typeLabel } from '../../lib/types'
import type { Session } from '../../lib/types'

/**
 * The sentence the engine wrote, plus the rules it applied, in the order it applied them.
 *
 * `<details>` rather than a hand-rolled disclosure: it is collapsible, keyboard operable and
 * announced correctly without any state of ours.
 */
export function WhyThisMix({ session }: { session: Session }) {
  const profile = session.profile
  if (!session.why_text && !profile) return null

  return (
    <details className="glass group rounded-tile px-4 py-3">
      <summary className="text-body flex min-h-tap cursor-pointer list-none items-center justify-between gap-3">
        Why this mix
        <ChevronDown
          aria-hidden="true"
          size={18}
          className="shrink-0 text-fog transition-transform group-open:rotate-180"
        />
      </summary>

      <div className="flex flex-col gap-3 pt-2 pb-1">
        {session.why_text ? <p className="text-body text-fog">{session.why_text}</p> : null}

        {profile ? (
          <>
            <ul className="text-caption flex flex-col gap-1 text-fog">
              {profile.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
            <p className="text-caption text-fog">
              {typeLabel(profile.type)} · energy {profile.energy_start.toFixed(1)} to{' '}
              {profile.energy_end.toFixed(1)}
              {session.intent === 'shift' ? ' · taking you somewhere else' : ' · matching where you are'}
            </p>
          </>
        ) : null}
      </div>
    </details>
  )
}
