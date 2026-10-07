import { ChevronDown } from 'lucide-react'

import { typeLabel } from '../../lib/types'
import type { Session } from '../../lib/types'

/**
 * The sentence the engine wrote, always on show as in docs/design/Session.dc.html, and under
 * it the rules it applied, folded away because they are for the curious.
 *
 * `<details>` rather than a hand-rolled disclosure: it is collapsible, keyboard operable and
 * announced correctly without any state of ours.
 */
export function WhyThisMix({ session }: { session: Session }) {
  const profile = session.profile
  if (!session.why_text && !profile) return null

  return (
    <section className="glass flex flex-col gap-1.5 rounded-tile px-4 py-3.5">
      <h2 className="text-caption font-[650] text-fog">Why this mix</h2>
      {session.why_text ? <p className="text-sm leading-normal">{session.why_text}</p> : null}

      {profile ? (
        <details className="group">
          <summary className="text-caption flex min-h-tap cursor-pointer list-none items-center gap-1.5 text-fog transition-colors hover:text-mist">
            How it was built
            <ChevronDown
              aria-hidden="true"
              size={14}
              className="shrink-0 transition-transform group-open:rotate-180"
            />
          </summary>
          <div className="flex flex-col gap-2 pb-1">
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
          </div>
        </details>
      ) : null}
    </section>
  )
}
