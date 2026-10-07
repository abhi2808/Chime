import { useState } from 'react'
import { Link } from 'react-router-dom'

import { EmptyState } from '../components/EmptyState'
import { BodyPanel } from '../features/session/BodyPanel'
import { ChimeOutSheet } from '../features/session/ChimeOutSheet'
import { MoodRecheck } from '../features/session/MoodRecheck'
import { NowPlayingPanel } from '../features/session/NowPlayingPanel'
import { SessionSummaryCard } from '../features/session/SessionSummaryCard'
import { UpNext } from '../features/session/UpNext'
import { WaitingToStart } from '../features/session/WaitingToStart'
import { WhyThisMix } from '../features/session/WhyThisMix'
import { ApiError } from '../lib/api'
import { minutesSince } from '../lib/music'
import { useActiveSession, useTransport } from '../lib/queries'
import { hueFor, typeLabel } from '../lib/types'
import type { Session as SessionModel } from '../lib/types'
import { useProgress } from '../lib/useProgress'

export function Session() {
  const { data, isPending } = useActiveSession()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [ended, setEnded] = useState<SessionModel | null>(null)

  const session = data?.session ?? null
  const playing = data?.playing ?? null
  const transport = useTransport(session?.id ?? null)
  const progress = useProgress(playing)

  // The summary replaces the player in place, so Chime out stays on one screen.
  if (ended) {
    return <SessionSummaryCard session={ended} hue={hueFor(ended.type)} />
  }

  if (!session) {
    return (
      <EmptyState
        title={isPending ? 'Looking for a session…' : 'Nothing is running'}
        body={isPending ? undefined : 'Chime in from Home and this screen fills up.'}
        action={
          isPending ? undefined : (
            <Link to="/" className="text-body min-h-tap flex items-center px-4 underline">
              Go to Home
            </Link>
          )
        }
      />
    )
  }

  const hue = hueFor(session.type)
  const minutes = minutesSince(session.started_at)
  const device = playing?.device_name ?? session.device_name
  // The ring reads against the length of what was queued, which is the only honest total a
  // session has: there is no fixed duration to run down.
  const queuedMs = session.tracks.reduce((total, track) => total + track.duration_ms, 0)
  const elapsed = queuedMs > 0 ? Math.min(1, (minutes * 60_000) / queuedMs) : 0

  return (
    <div className="flex flex-col gap-8">
      <header className="flex items-center justify-between gap-3">
        <span className="text-caption flex items-center gap-2 text-fog">
          <span aria-hidden="true" className="size-2 rounded-full" style={{ background: hue }} />
          {typeLabel(session.type)}
          {session.intent === 'shift' ? ' · shifting' : null}
        </span>
        <span className="text-caption text-fog tabular-nums">
          {minutes} min
          {/* The live read knows the device; the session row only knows where it started. */}
          {device ? ` · ${device}` : ''}
        </span>
      </header>

      {/* Above the player, because until it is dealt with there is nothing to play. */}
      {session.needs_manual_start ? <WaitingToStart session={session} hue={hue} /> : null}

      <NowPlayingPanel
        session={session}
        playing={playing}
        note={data?.note ?? null}
        hue={hue}
        elapsed={elapsed}
        progress={progress}
        onTransport={(action) => transport.mutate(action)}
        pending={transport.isPending}
      />

      {transport.isError ? (
        <p className="text-caption text-center text-danger">
          {transport.error instanceof ApiError
            ? transport.error.message
            : 'Spotify did not take that. Try again.'}
        </p>
      ) : null}

      <WhyThisMix session={session} />
      <MoodRecheck sessionId={session.id} />
      <UpNext session={session} hue={hue} currentTrackId={playing?.spotify_track_id ?? null} />
      <BodyPanel session={session} />

      <button
        type="button"
        onClick={() => setSheetOpen(true)}
        className="text-body glass min-h-tap rounded-full text-mist transition-colors hover:border-white/20"
      >
        Chime out
      </button>

      <ChimeOutSheet
        session={session}
        hue={hue}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onEnded={(finished) => {
          setSheetOpen(false)
          setEnded(finished)
        }}
      />
    </div>
  )
}
