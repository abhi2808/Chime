import { figures } from '../../lib/body'
import type { BodyState } from '../../lib/types'

/**
 * "Recovery 41% · Sleep 63% · Strain 9.4" under the greeting, per DESIGN's Home sketch.
 *
 * Renders nothing when WHOOP has no scored figures yet — the WHOOP card below says why,
 * so an empty line here is better than a row of dashes.
 */
export function BodyFigures({ state }: { state: BodyState | undefined }) {
  if (!state?.has_data) return null

  const shown = figures(state)
  if (shown.length === 0) return null

  return (
    <p className="text-caption text-fog">
      {shown.map((figure, index) => (
        <span key={figure.label}>
          {index > 0 ? <span aria-hidden="true"> · </span> : null}
          {figure.label} {figure.value}
        </span>
      ))}
    </p>
  )
}
