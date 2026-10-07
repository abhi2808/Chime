import { useCallback, useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

/** `inflating` is the bubble under pressure; `bursting` is the 120 ms pop. */
export type HoldPhase = 'idle' | 'inflating' | 'bursting'

const HOLD_MS = 1200
const BURST_MS = 120
/** How long a finished pointer sequence keeps swallowing the click it produces. */
const CLICK_GRACE_MS = 400

interface HoldOptions {
  /** A short press, or any keyboard activation. */
  onTap: () => void
  /** The hold completed and the orb burst. */
  onHold: () => void
  disabled?: boolean
}

export interface Hold {
  phase: HoldPhase
  /** Spread onto the element being held. */
  handlers: {
    onPointerDown: (event: ReactPointerEvent) => void
    onPointerUp: () => void
    onPointerLeave: () => void
    onPointerCancel: () => void
    onClick: () => void
  }
}

/**
 * Press and hold, per DESIGN: nothing happens on pointer-down, a hold of 1.2 s bursts and
 * calls `onHold`, an earlier release calls `onTap`, and dragging off cancels silently.
 *
 * Two things are easy to get wrong and are handled with refs rather than state, because
 * both are decided inside one event and must not wait for a render:
 * `resolved` stops a release that arrives after the burst from also firing the tap, and
 * `pointer` swallows the synthetic click a touch or mouse sequence leaves behind — without
 * it every tap would open the sheet twice. Keyboard activation arrives as a click with no
 * pointer sequence in front of it, which is exactly how Enter and Space reach `onTap`.
 */
export function useHold({ onTap, onHold, disabled = false }: HoldOptions): Hold {
  const [phase, setPhase] = useState<HoldPhase>('idle')
  const timers = useRef<number[]>([])
  const resolved = useRef(false)
  const pointer = useRef(false)

  const clearTimers = useCallback(() => {
    timers.current.forEach(window.clearTimeout)
    timers.current = []
  }, [])

  useEffect(() => clearTimers, [clearTimers])

  const cancel = useCallback(() => {
    clearTimers()
    setPhase('idle')
    resolved.current = true // a release after this must not count as a tap
    timers.current.push(window.setTimeout(() => (pointer.current = false), CLICK_GRACE_MS))
  }, [clearTimers])

  const onPointerDown = useCallback(
    (event: ReactPointerEvent) => {
      // Right-click and secondary touches are not a hold.
      if (disabled || !event.isPrimary || event.button !== 0) return
      clearTimers()
      resolved.current = false
      pointer.current = true
      setPhase('inflating')
      timers.current.push(
        window.setTimeout(() => {
          resolved.current = true
          setPhase('bursting')
        }, HOLD_MS),
        window.setTimeout(() => {
          setPhase('idle')
          onHold()
        }, HOLD_MS + BURST_MS),
      )
    },
    [clearTimers, disabled, onHold],
  )

  const onPointerUp = useCallback(() => {
    if (disabled || resolved.current) return
    clearTimers()
    setPhase('idle')
    timers.current.push(window.setTimeout(() => (pointer.current = false), CLICK_GRACE_MS))
    onTap()
  }, [clearTimers, disabled, onTap])

  const onClick = useCallback(() => {
    if (disabled) return
    if (pointer.current) {
      pointer.current = false
      return
    }
    onTap()
  }, [disabled, onTap])

  return {
    phase,
    handlers: { onPointerDown, onPointerUp, onPointerLeave: cancel, onPointerCancel: cancel, onClick },
  }
}
