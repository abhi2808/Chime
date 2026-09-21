import type { CSSProperties } from 'react'

import { cx } from '../lib/cx'

export type OrbState = 'idle' | 'pulsing' | 'expanding'

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
      disabled={disabled}
      aria-label={label}
    >
      <span className="orb-halo" />
      <span className="orb-body" />
    </button>
  )
}
