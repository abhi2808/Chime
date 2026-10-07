import type { CSSProperties, DOMAttributes } from 'react'

import { cx } from '../lib/cx'

export type OrbState = 'idle' | 'still' | 'inflating' | 'bursting' | 'expanding'

interface OrbProps {
  /** A session hue, e.g. `var(--color-ember)`. Ember is the sphere as drawn; any other hue
   *  mixes the same lighting from itself. */
  hue?: string
  size?: number
  state?: OrbState
  /** Corona and pulse rings. Home has them; a small decorative orb does not. */
  aura?: boolean
  /** The word on the sphere. Omit for a wordless orb. */
  word?: string
  label?: string
  onClick?: () => void
  disabled?: boolean
  className?: string
  /**
   * The press-and-hold handlers from `useHold`. Kept separate from `onClick` so an orb
   * without a gesture stays a plain button: the hold is a shortcut, never the only route.
   */
  gesture?: Pick<
    DOMAttributes<HTMLButtonElement>,
    'onPointerDown' | 'onPointerUp' | 'onPointerLeave' | 'onPointerCancel'
  >
}

const EMBER = 'var(--color-ember)'

/** The one bold thing: a lit sphere that breathes. Every animation lives in tokens.css so
 *  reduced motion can switch them off in one place. */
export function Orb({
  hue = EMBER,
  size = 208,
  state = 'idle',
  aura = false,
  word,
  label = 'Chime in',
  onClick,
  disabled = false,
  className,
  gesture,
}: OrbProps) {
  const style = { '--orb-hue': hue, '--orb-size': `${size}px` } as CSSProperties
  const stage = cx(
    'orb-stage',
    `orb--${state}`,
    hue === EMBER ? 'orb-hue-ember' : 'orb-hue-mixed',
    className,
  )

  const surface = (
    <>
      <span className="orb-specular" aria-hidden="true" />
      <span className="orb-bounce" aria-hidden="true" />
      {word ? (
        <span className="orb-word" aria-hidden="true">
          {word}
        </span>
      ) : null}
    </>
  )

  return (
    <div className={stage} style={style}>
      {aura ? (
        <>
          <span className="orb-corona" aria-hidden="true" />
          <span className="orb-pulse" aria-hidden="true" />
          <span className="orb-pulse" aria-hidden="true" />
          <span className="orb-pulse" aria-hidden="true" />
        </>
      ) : null}

      {onClick ? (
        <button
          type="button"
          className="orb-sphere grid place-items-center"
          onClick={onClick}
          {...gesture}
          disabled={disabled}
          aria-label={label}
        >
          {surface}
        </button>
      ) : (
        <div className="orb-sphere grid place-items-center" role="presentation">
          {surface}
        </div>
      )}
    </div>
  )
}
