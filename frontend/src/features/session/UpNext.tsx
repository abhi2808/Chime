import { TrackRow } from '../../components/TrackRow'
import type { Session } from '../../lib/types'

/**
 * The rest of the queue.
 *
 * "The rest" is worked out from what Spotify says is playing rather than from a cursor of
 * our own, because the user can skip from any device. When the current song is not in the
 * playlist at all — playback wandered off, or is paused between songs — it falls back to the
 * songs the poller has not seen play yet, and to the whole queue if nothing was measured.
 *
 * Songs the mix picked up mid-session carry an "added later" chip from `TrackRow`, so a queue
 * that grew while you listened says so instead of quietly changing length.
 */
export function UpNext({
  session,
  hue,
  currentTrackId,
}: {
  session: Session
  hue: string
  currentTrackId: string | null
}) {
  if (session.tracks.length === 0) return null

  const index = currentTrackId
    ? session.tracks.findIndex((track) => track.spotify_track_id === currentTrackId)
    : -1
  // One song seen playing is enough to trust the poller's record of the others.
  const measured = session.tracks.some((track) => track.started_at !== null)
  const upcoming =
    index >= 0
      ? session.tracks.slice(index + 1)
      : measured
        ? session.tracks.filter((track) => track.started_at === null)
        : session.tracks

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <h2 className="text-headline">Up next</h2>
        <span className="text-caption text-fog">
          {upcoming.length === 0 ? 'End of the mix' : `${upcoming.length} to go`}
        </span>
      </div>

      {upcoming.length > 0 ? (
        <ul className="glass flex flex-col rounded-tile p-2">
          {upcoming.map((track) => (
            <TrackRow key={track.position} track={track} hue={hue} />
          ))}
        </ul>
      ) : (
        <p className="text-body text-fog">
          Everything queued has been through. Spotify keeps playing from the playlist.
        </p>
      )}

      {session.playlist_url ? (
        <a
          href={session.playlist_url}
          target="_blank"
          rel="noreferrer"
          className="text-caption min-h-tap self-start py-2 text-fog underline decoration-hairline transition-colors hover:text-mist"
        >
          Playing from Spotify · open the playlist
        </a>
      ) : null}
    </section>
  )
}
