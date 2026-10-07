import { useRef } from 'react'

import { SESSION_TYPES } from '../lib/types'
import type { SessionType } from '../lib/types'

/** A radiogroup of chips, each with its hue dot. Auto is the default. */
export function SessionTypeSegment({
  value,
  onChange,
}: {
  value: SessionType['id']
  onChange: (id: SessionType['id']) => void
}) {
  const group = useRef<HTMLDivElement>(null)

  const move = (from: number, delta: number) => {
    const next = (from + delta + SESSION_TYPES.length) % SESSION_TYPES.length
    onChange(SESSION_TYPES[next].id)
    group.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus()
  }

  return (
    <div
      ref={group}
      role="radiogroup"
      aria-label="Session"
      className="flex flex-wrap gap-2"
    >
      {SESSION_TYPES.map((type, index) => {
        const selected = type.id === value
        return (
          <button
            key={type.id}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(type.id)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                event.preventDefault()
                move(index, 1)
              } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                event.preventDefault()
                move(index, -1)
              }
            }}
            className="chip"
          >
            <span
              aria-hidden="true"
              className="size-[7px] rounded-full"
              style={{ background: type.hue, opacity: type.id === 'auto' ? 0.5 : 1 }}
            />
            {type.label}
          </button>
        )
      })}
    </div>
  )
}
