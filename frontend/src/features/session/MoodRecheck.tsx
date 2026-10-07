import { useState } from 'react'

import { MoodChips } from '../../components/MoodChips'
import { useMoodCheck } from '../../lib/queries'
import { moodId } from '../../lib/types'
import type { Mood } from '../../lib/types'

/**
 * A mid-session check-in. Recorded as an event on the session; it does not rewrite how the
 * session started, and in this phase it does not re-rank what is queued either — it is the
 * record that later adaptation reads.
 */
export function MoodRecheck({ sessionId }: { sessionId: number }) {
  const [open, setOpen] = useState(false)
  const [mood, setMood] = useState<Mood | null>(null)
  const check = useMoodCheck(sessionId)

  const send = (next: Mood) => {
    setMood(next)
    check.mutate(moodId(next))
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-caption min-h-tap self-start text-fog underline decoration-hairline transition-colors hover:text-mist"
      >
        Feeling different now?
      </button>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-caption text-fog">
        {check.isSuccess ? 'Noted.' : 'How are you feeling now?'}
      </span>
      <MoodChips value={mood} onChange={send} label="How are you feeling now?" />
      {check.isError ? (
        <span className="text-caption text-danger">That didn't save. Try again.</span>
      ) : null}
    </div>
  )
}
