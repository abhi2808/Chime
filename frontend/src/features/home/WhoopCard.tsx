import { HeartPulse, RefreshCw } from 'lucide-react'

import { ago, agoFromMinutes } from '../../lib/body'
import { useBodyState, useRefreshBodyState } from '../../lib/queries'

/**
 * The WHOOP row from DESIGN's Home sketch: connection state and anything WHOOP cannot
 * tell us yet. The figures themselves live under the greeting, not here.
 *
 * `note` comes from the backend already phrased for a person, so it is shown verbatim
 * rather than re-worded per state.
 */
export function WhoopCard() {
  const { data: state } = useBodyState()
  const refresh = useRefreshBodyState()

  if (!state) {
    return <div className="glass h-[92px] rounded-sheet" aria-hidden="true" />
  }

  const reconnect = state.needs_reconnect
  const connect = !state.connected || reconnect
  const headline = !state.connected
    ? 'Connect WHOOP'
    : reconnect
      ? 'WHOOP needs reconnecting'
      : 'WHOOP connected'

  const updated = state.has_data ? ago(state.fetched_at) : null
  const lastWorkout = agoFromMinutes(state.minutes_since_last_workout)
  const meta = [
    updated ? `Updated ${updated}` : null,
    lastWorkout ? `Last workout ${lastWorkout}` : null,
  ].filter((line): line is string => line !== null)

  return (
    <section className="glass rounded-sheet px-screen flex items-start justify-between gap-4 py-5">
      <div className="flex flex-col gap-1">
        <span className="text-caption flex items-center gap-2 text-fog">
          <HeartPulse aria-hidden="true" size={14} />
          WHOOP
        </span>
        <h2 className="text-headline">{headline}</h2>
        {state.note ? <p className="text-caption text-fog">{state.note}</p> : null}
        {meta.length > 0 ? <p className="text-caption text-fog">{meta.join(' · ')}</p> : null}
        {refresh.error ? (
          <p className="text-caption text-danger" role="alert">
            {refresh.error.message}
          </p>
        ) : null}
      </div>

      {connect ? (
        // A full page navigation, not fetch: the OAuth handshake cookie has to be set on
        // this origin and survive the redirect back from WHOOP.
        <a
          href="/auth/whoop/login"
          className="text-caption min-h-tap flex shrink-0 items-center rounded-full border border-hairline px-4 transition-colors hover:border-white/20"
        >
          {reconnect ? 'Reconnect' : 'Connect'}
        </a>
      ) : (
        <button
          type="button"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="text-caption min-h-tap flex shrink-0 items-center gap-2 rounded-full border border-hairline px-4 transition-colors hover:border-white/20 disabled:opacity-60"
        >
          <RefreshCw aria-hidden="true" size={14} />
          {refresh.isPending ? 'Reading…' : 'Refresh'}
        </button>
      )}
    </section>
  )
}
