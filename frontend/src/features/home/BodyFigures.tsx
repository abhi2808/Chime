import { Fragment } from 'react'

import { figures } from '../../lib/body'
import type { BodyState } from '../../lib/types'

/**
 * "Recovery 41% · Sleep 63% · Strain 9.4" under the greeting.
 *
 * With the WHOOP card gone from Home, this line is where a missing connection shows: a
 * single "Connect WHOOP" link in place of the figures, as DESIGN asks. A connected WHOOP that
 * has not scored the day yet shows nothing rather than a row of dashes.
 */
export function BodyFigures({ state }: { state: BodyState | undefined }) {
  if (!state) return null

  if (!state.connected || state.needs_reconnect) {
    return (
      // A full page navigation, not fetch: the OAuth handshake cookie has to be set on this
      // origin and survive the redirect back from WHOOP.
      <a
        href="/auth/whoop/login"
        className="text-caption self-start text-fog underline decoration-hairline underline-offset-4 transition-colors hover:text-ember-bright"
      >
        {state.needs_reconnect ? 'Reconnect WHOOP' : 'Connect WHOOP'}
      </a>
    )
  }

  if (!state.has_data) return null
  const shown = figures(state)
  if (shown.length === 0) return null

  return (
    <p className="text-caption flex flex-wrap gap-x-3.5 text-fog">
      {shown.map((figure, index) => (
        <Fragment key={figure.label}>
          {index > 0 ? <span aria-hidden="true">·</span> : null}
          <span>
            {figure.label} {figure.value}
          </span>
        </Fragment>
      ))}
    </p>
  )
}
