import { useRef } from 'react'

import { cx } from '../lib/cx'
import { MOODS } from '../lib/types'
import type { Mood } from '../lib/types'

/** Single-select chips as a real radiogroup: one tab stop, arrow keys move and select. */
export function MoodChips({
  value,
  onChange,
  label = 'How are you feeling?',
}: {
  value: Mood | null
  onChange: (mood: Mood) => void
  label?: string
}) {
  const group = useRef<HTMLDivElement>(null)

  const move = (from: number, delta: number) => {
    const next = (from + delta + MOODS.length) % MOODS.length
    onChange(MOODS[next])
    group.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus()
  }

  return (
    <div ref={group} role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {MOODS.map((mood, index) => {
        const selected = mood === value
        return (
          <button
            key={mood}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected || (!value && index === 0) ? 0 : -1}
            onClick={() => onChange(mood)}
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
              'text-body min-h-tap rounded-tile px-4 transition-colors',
              selected
                ? 'bg-mist font-semibold text-midnight'
                : 'glass text-mist hover:border-white/20',
            )}
          >
            {mood}
          </button>
        )
      })}
    </div>
  )
}
