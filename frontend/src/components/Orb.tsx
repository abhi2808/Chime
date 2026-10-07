import type { CSSProperties, DOMAttributes } from 'react'

import { cx } from '../lib/cx'

export type OrbState = 'idle' | 'pulsing' | 'inflating' | 'bursting' | 'expanding'

interface OrbProps {
  /** A session hue, e.g. `var(--color-ember)`. */
  hue?: string
  size?: number
  state?: OrbState
  /** 0-1. Home uses a reduced intensity until a session picks a real hue. */
  intensity?: number
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

/** The one bold thing. Glow and breathing live in tokens.css so reduced motion can
 *  switch them off in a single place. */
export function Orb({
  hue = 'var(--color-ember)',
  size = 200,
  state = 'idle',
  intensity = 1,
  label = 'Chime in',
  onClick,
  disabled = false,
  className,
  gesture,
}: OrbProps) {
  const style = {
    '--orb-hue': hue,
    '--orb-size': `${size}px`,
    '--orb-intensity': intensity,
  } as CSSProperties

  const classes = cx('orb-button', `orb--${state}`, className)

  if (!onClick) {
    return (
      <div className={classes} style={style} role="presentation">
        <span className="orb-halo" />
        <span className="orb-body" />
      </div>
    )
  }

  return (
    <button
      type="button"
      className={classes}
      style={style}
      onClick={onClick}
      {...gesture}
      disabled={disabled}
      aria-label={label}
    >
      <span className="orb-halo" />
      <span className="orb-body" />
    </button>
  )
}
