import { useRef } from 'react'

import { cx } from '../lib/cx'
import { SESSION_TYPES } from '../lib/types'
import type { SessionType } from '../lib/types'

/** Segmented control with a hue dot per option. Auto is the default. */
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
      className="glass flex gap-1 overflow-x-auto rounded-tile p-1"
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
            className={cx(
              'text-caption flex min-h-tap shrink-0 items-center gap-2 rounded-[14px] px-3 whitespace-nowrap transition-colors',
              selected ? 'bg-white/12 text-mist' : 'text-fog hover:text-mist',
            )}
          >
            <span
              aria-hidden="true"
              className="size-2 rounded-full"
              style={{ background: type.hue, opacity: type.id === 'auto' ? 0.5 : 1 }}
            />
            {type.label}
          </button>
        )
      })}
    </div>
  )
}
