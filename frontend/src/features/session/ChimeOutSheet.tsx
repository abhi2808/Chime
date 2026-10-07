import { useId, useState } from 'react'

import { MoodChips } from '../../components/MoodChips'
import { Sheet } from '../../components/Sheet'
import { cx } from '../../lib/cx'
import { ApiError } from '../../lib/api'
import { useChimeOut } from '../../lib/queries'
import { moodId } from '../../lib/types'
import type { Mood, Session } from '../../lib/types'

/**
 * Wrapping up. Keeping is off by default: a Chime playlist is temporary unless the user says
 * otherwise, and that is the whole point of Chime out.
 *
 * Keep and remove both end the session — a Spotify failure on either is reported in the
 * summary's `problems` rather than blocking, so a session can always be closed.
 */
export function ChimeOutSheet({
  session,
  hue,
  open,
  onClose,
  onEnded,
}: {
  session: Session
  hue: string
  open: boolean
  /** "Keep going": nothing has happened. */
  onClose: () => void
  onEnded: (ended: Session) => void
}) {
  const [mood, setMood] = useState<Mood | null>(null)
  const [keep, setKeep] = useState(false)
  const [name, setName] = useState(session.playlist_name ?? '')
  const nameId = useId()
  const chimeOut = useChimeOut(session.id)

  const end = () => {
    chimeOut.mutate(
      {
        keep,
        name: keep ? name.trim() || null : null,
        mood_out: mood ? moodId(mood) : null,
      },
      { onSuccess: onEnded },
    )
  }

  return (
    <Sheet open={open} title="Wrap up this session?" onClose={onClose}>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <span className="text-caption text-fog">How do you feel now?</span>
          <MoodChips value={mood} onChange={setMood} label="How do you feel now?" />
        </div>

        <div className="flex flex-col gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={keep}
            onClick={() => setKeep(!keep)}
            className="text-body flex min-h-tap items-center justify-between gap-4"
          >
            Keep this playlist
            <span
              aria-hidden="true"
              className={cx(
                'relative h-7 w-12 shrink-0 rounded-full transition-colors',
                keep ? '' : 'bg-white/12',
              )}
              style={keep ? { background: hue } : undefined}
            >
              <span
                className={cx(
                  'absolute top-1 size-5 rounded-full bg-mist transition-[left]',
                  keep ? 'left-6' : 'left-1',
                )}
              />
            </span>
          </button>

          {keep ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={nameId} className="text-caption text-fog">
                Playlist name
              </label>
              <input
                id={nameId}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={session.playlist_name ?? 'Chime'}
                className="text-body glass min-h-tap rounded-tile px-3 text-mist placeholder:text-fog"
              />
            </div>
          ) : (
            <p className="text-caption text-fog">
              The playlist comes out of your library. Nothing else changes.
            </p>
          )}
        </div>

        {chimeOut.isError ? (
          <p className="text-caption text-danger">
            {chimeOut.error instanceof ApiError
              ? chimeOut.error.message
              : 'Something went wrong ending the session. Try again.'}
          </p>
        ) : null}

        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={onClose}
            style={{ background: hue }}
            className="text-body min-h-tap rounded-full font-semibold text-midnight transition-opacity hover:opacity-90"
          >
            Keep going
          </button>
          <button
            type="button"
            onClick={end}
            disabled={chimeOut.isPending}
            className="text-body glass min-h-tap rounded-full text-mist transition-colors hover:border-white/20 disabled:text-fog"
          >
            {chimeOut.isPending ? 'Chiming out…' : 'Chime out'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
