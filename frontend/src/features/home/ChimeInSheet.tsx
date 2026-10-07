import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { IntentSegment } from '../../components/IntentSegment'
import { MoodChips } from '../../components/MoodChips'
import { SessionTypeSegment } from '../../components/SessionTypeSegment'
import { Sheet } from '../../components/Sheet'
import { ApiError } from '../../lib/api'
import { useChimeIn } from '../../lib/queries'
import { hueFor, moodId } from '../../lib/types'
import type { Intent, Mood, SessionType } from '../../lib/types'

export function ChimeInSheet({
  open,
  onClose,
  initialIntent = 'match',
}: {
  open: boolean
  onClose: () => void
  /** Holding the orb arrives here with `shift` already chosen. */
  initialIntent?: Intent
}) {
  const [mood, setMood] = useState<Mood | null>(null)
  const [type, setType] = useState<SessionType['id']>('auto')
  const [intent, setIntent] = useState<Intent>(initialIntent)
  const navigate = useNavigate()
  const chimeIn = useChimeIn()

  // Opening by hold preselects "somewhere else"; opening by tap resets to "here".
  useEffect(() => {
    if (open) setIntent(initialIntent)
  }, [open, initialIntent])

  const hue = hueFor(type)
  const error = chimeIn.error instanceof ApiError ? chimeIn.error : null

  const start = () => {
    // Mood is optional: without one the engine works from body data and the time of day
    // alone (SPEC section 3), so there is nothing to block on.
    // No `count`: how many songs a session queues is the engine's call, not the sheet's.
    chimeIn.mutate(
      { mood: mood ? moodId(mood) : null, type, intent },
      {
        onSuccess: (session) => {
          onClose()
          navigate('/session')
          // Spotify would not press play, so take the user to where they can. The tab is an
          // attempt, not the plan: a popup blocker may well refuse it this far from the
          // click, and the session screen carries the same link for when it does.
          if (session.needs_manual_start && session.playlist_url) {
            window.open(session.playlist_url, '_blank', 'noopener,noreferrer')
          }
        },
      },
    )
  }

  return (
    <Sheet open={open} title="How are you feeling?" onClose={onClose}>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <MoodChips value={mood} onChange={setMood} onClear={() => setMood(null)} />
          {!mood ? (
            <p className="text-caption text-fog">
              Optional. Skip it and the mix goes on your body data and the time of day.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-caption text-fog">Take me</span>
          <IntentSegment value={intent} onChange={setIntent} />
          {/* Shift rewrites the curve away from a mood, so with no mood the engine has
              nothing to move away from and does nothing at all. Say so rather than let it
              look like it worked. */}
          {intent === 'shift' && !mood ? (
            <p className="text-caption text-fog">
              Shifting needs a mood — without one there's nothing to move away from.
            </p>
          ) : null}
          {mood === 'Steady' && intent === 'shift' ? (
            <p className="text-caption text-fog">
              Steady has nowhere to move to, so this changes nothing.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-caption text-fog">Session</span>
          <SessionTypeSegment value={type} onChange={setType} />
        </div>

        {error ? (
          <div className="flex flex-col gap-1">
            <p className="text-caption text-danger">{error.message}</p>
            {/* The one failure with somewhere to go: a session is already running. */}
            {error.code === 'SESSION_ACTIVE' ? (
              <Link
                to="/session"
                onClick={onClose}
                className="text-caption min-h-tap flex items-center self-start underline"
              >
                Open the session
              </Link>
            ) : null}
          </div>
        ) : null}

        <button
          type="button"
          disabled={chimeIn.isPending}
          onClick={start}
          style={{ background: hue }}
          className="text-body min-h-tap rounded-full font-semibold text-midnight transition-opacity hover:opacity-90 disabled:opacity-70"
        >
          {chimeIn.isPending ? 'Building your mix…' : 'Start'}
        </button>
      </div>
    </Sheet>
  )
}
