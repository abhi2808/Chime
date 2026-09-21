import { useState } from 'react'

import { MoodChips } from '../../components/MoodChips'
import { SessionTypeSegment } from '../../components/SessionTypeSegment'
import { Sheet } from '../../components/Sheet'
import { SESSION_TYPES } from '../../lib/types'
import type { Mood, SessionType } from '../../lib/types'

/** Phase 1 is UI only: Start closes the sheet. Building the playlist comes later. */
export function ChimeInSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [mood, setMood] = useState<Mood | null>(null)
  const [type, setType] = useState<SessionType['id']>('auto')

  const hue = SESSION_TYPES.find((option) => option.id === type)?.hue ?? 'var(--color-ember)'

  return (
    <Sheet open={open} title="How are you feeling?" onClose={onClose}>
      <div className="flex flex-col gap-6">
        <MoodChips value={mood} onChange={setMood} />

        <div className="flex flex-col gap-2">
          <span className="text-caption text-fog">Session</span>
          <SessionTypeSegment value={type} onChange={setType} />
        </div>

        <button
          type="button"
          disabled={!mood}
          onClick={onClose}
          style={mood ? { background: hue } : undefined}
          className="text-body min-h-tap rounded-full font-semibold text-midnight transition-opacity hover:opacity-90 disabled:bg-white/10 disabled:text-fog"
        >
          Start
        </button>

        {!mood ? (
          <p className="text-caption -mt-4 text-center text-fog">Pick a mood to start.</p>
        ) : null}
      </div>
    </Sheet>
  )
}
