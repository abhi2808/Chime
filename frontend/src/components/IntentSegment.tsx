import { useRef } from 'react'

import { INTENTS } from '../lib/types'
import type { Intent } from '../lib/types'

/**
 * "Take me here" or "somewhere else" — `match` or `shift`. Arriving by holding the orb
 * preselects "somewhere else", and this control is what makes that reachable without the
 * gesture.
 */
export function IntentSegment({
  value,
  onChange,
}: {
  value: Intent
  onChange: (intent: Intent) => void
}) {
  const group = useRef<HTMLDivElement>(null)

  const move = (from: number, delta: number) => {
    const next = (from + delta + INTENTS.length) % INTENTS.length
    onChange(INTENTS[next].id)
    group.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus()
  }

  return (
    <div
      ref={group}
      role="radiogroup"
      aria-label="Take me"
      className="flex gap-2"
    >
      {INTENTS.map((intent, index) => {
        const selected = intent.id === value
        return (
          <button
            key={intent.id}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(intent.id)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                event.preventDefault()
                move(index, 1)
              } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                event.preventDefault()
                move(index, -1)
              }
            }}
            className="chip flex-1 justify-center"
          >
            {intent.label}
          </button>
        )
      })}
    </div>
  )
}
