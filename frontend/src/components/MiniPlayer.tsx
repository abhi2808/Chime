import { Pause, Play } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import { useActiveSession, useTransport } from '../lib/queries'
import { artistLine } from '../lib/music'
import { hueFor, typeLabel } from '../lib/types'
import { useProgress } from '../lib/useProgress'

/**
 * The bar above the tab bar while a session is live. Tapping it opens Session.
 *
 * Hidden on Session itself, where the full player is already on screen.
 */
export function MiniPlayer() {
  const { data } = useActiveSession()
  const { pathname } = useLocation()
  const session = data?.session ?? null
  const playing = data?.playing ?? null
  const transport = useTransport(session?.id ?? null)
  const progress = useProgress(playing)

  if (!session || pathname === '/session') return null

  const hue = hueFor(session.type)
  const fraction =
    playing && playing.duration_ms > 0 && progress !== null
      ? Math.min(1, progress / playing.duration_ms)
      : 0
  const title = playing?.name ?? session.playlist_name ?? typeLabel(session.type)
  // A session waiting to be started by hand is not paused, and saying so would send the user
  // looking for a play button that cannot help them. The session screen has the link.
  let under = data?.note ?? 'Paused'
  if (playing) under = artistLine(playing.artists)
  else if (session.needs_manual_start) under = 'Waiting for you to press play in Spotify'

  return (
    <div className="fixed inset-x-0 bottom-[calc(60px+env(safe-area-inset-bottom))] z-40 px-screen lg:bottom-4 lg:pl-56">
      <div className="glass mx-auto flex max-w-content items-center gap-3 overflow-hidden rounded-tile p-2">
        <Link
          to="/session"
          className="flex min-w-0 flex-1 items-center gap-3"
          aria-label="Open the session"
        >
          {playing?.image_url ? (
            <img
              src={playing.image_url}
              alt=""
              width={40}
              height={40}
              className="size-10 shrink-0 rounded-art object-cover"
            />
          ) : (
            <span
              aria-hidden="true"
              className="size-10 shrink-0 rounded-art"
              style={{ background: hue, opacity: 0.35 }}
            />
          )}
          <span className="min-w-0 flex-1">
            <span className="text-body block truncate">{title}</span>
            <span className="text-caption block truncate text-fog">{under}</span>
          </span>
        </Link>

        <button
          type="button"
          onClick={() => transport.mutate(playing?.is_playing ? 'pause' : 'resume')}
          disabled={transport.isPending}
          aria-label={playing?.is_playing ? 'Pause' : 'Play'}
          className="flex min-h-tap min-w-tap items-center justify-center rounded-full text-mist disabled:text-fog"
        >
          {playing?.is_playing ? (
            <Pause aria-hidden="true" size={20} />
          ) : (
            <Play aria-hidden="true" size={20} />
          )}
        </button>
      </div>

      {/* Progress in the session hue, under the bar so it reads as one object. */}
      <div className="mx-auto -mt-px h-0.5 max-w-content overflow-hidden rounded-full bg-hairline">
        <div
          className="h-full transition-[width] duration-500 ease-linear"
          style={{ width: `${fraction * 100}%`, background: hue }}
        />
      </div>
    </div>
  )
}
