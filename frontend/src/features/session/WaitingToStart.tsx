import { ExternalLink, RotateCw } from 'lucide-react'

import { ApiError } from '../../lib/api'
import { useStartPlayback } from '../../lib/queries'
import type { Session } from '../../lib/types'

/**
 * The mix is made, Spotify would not press play, and this is the way in.
 *
 * Spotify only lets an app start playback on a Premium account with its own app already open
 * somewhere, and neither can be checked beforehand. So instead of losing the session, the
 * playlist is handed over: opening it is an ordinary link, which is the one thing a browser
 * never blocks, and "Try again" is for when Spotify is open now and the API can do it after
 * all. Either way the session poll notices playback and this panel goes away on its own.
 */
export function WaitingToStart({ session, hue }: { session: Session; hue: string }) {
  const start = useStartPlayback(session.id)
  const error = start.error instanceof ApiError ? start.error : null

  return (
    <section className="glass rounded-sheet flex flex-col gap-3 p-5">
      <h2 className="text-headline">Press play in Spotify</h2>
      {/* The backend's sentence, shown as written: it knows which refusal this was. */}
      <p className="text-body text-fog">{session.manual_start_reason}</p>

      <div className="flex flex-wrap gap-2">
        {session.playlist_url ? (
          <a
            href={session.playlist_url}
            target="_blank"
            rel="noreferrer"
            style={{ background: hue }}
            className="text-body min-h-tap flex flex-1 items-center justify-center gap-2 rounded-full px-5 font-semibold text-midnight transition-opacity hover:opacity-90"
          >
            <ExternalLink aria-hidden="true" size={16} />
            Open in Spotify
          </a>
        ) : null}
        <button
          type="button"
          onClick={() => start.mutate()}
          disabled={start.isPending}
          className="text-body glass min-h-tap flex items-center justify-center gap-2 rounded-full px-5 text-mist transition-colors hover:border-white/20 disabled:text-fog"
        >
          <RotateCw aria-hidden="true" size={16} />
          {start.isPending ? 'Trying…' : 'Try again'}
        </button>
      </div>

      {error ? (
        <p className="text-caption text-danger" role="status">
          {error.message}
        </p>
      ) : null}
      <p className="text-caption text-fog">
        This screen picks the music up by itself once it starts, wherever you start it.
      </p>
    </section>
  )
}
