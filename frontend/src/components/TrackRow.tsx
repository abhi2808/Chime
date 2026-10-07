import { ExternalLink } from 'lucide-react'

import { cx } from '../lib/cx'
import { artistLine, clock, energyDots, spotifyTrackUrl } from '../lib/music'
import type { SessionTrack } from '../lib/types'

/**
 * One song in a session: art, title, artist, energy dots, and — on a session that is a
 * record rather than a queue — what became of it.
 *
 * DESIGN gives this row an overflow menu ("Feels calmer", "Feels more intense", "Remove
 * from this session", "Open in Spotify"). The first two are the deferred `energy_override`
 * and the third has no endpoint yet, so for now the row carries only the action that does
 * work — it opens the song in Spotify, which is also the attribution the design guidelines
 * ask for.
 */
export function TrackRow({
  track,
  hue,
  current = false,
  outcome = false,
}: {
  track: SessionTrack
  hue: string
  /** The song playing now, lifted out of the list. */
  current?: boolean
  /**
   * Show what became of the song — played, skipped, or still to come.
   *
   * Off in a queue, where it would be meaningless, and on where the session is a record of
   * something that happened. Kept a prop rather than inferred from the data, because
   * `started_at: null` means "not measured" as well as "not yet played" and only the screen
   * knows which of those it is looking at.
   */
  outcome?: boolean
}) {
  const dots = energyDots(track.energy)
  const mark = outcome ? outcomeOf(track, current) : null

  return (
    <li
      className={cx(
        'flex items-center gap-3 rounded-row px-2 py-2 transition-colors',
        current ? 'bg-white/8' : 'hover:bg-white/4',
      )}
    >
      {track.image_url ? (
        <img
          src={track.image_url}
          alt=""
          width={48}
          height={48}
          loading="lazy"
          className="size-12 shrink-0 rounded-art object-cover"
        />
      ) : (
        <div aria-hidden="true" className="glass size-12 shrink-0 rounded-art" />
      )}

      <div className="min-w-0 flex-1">
        <p className={cx('text-body truncate', current && 'font-semibold')}>
          {current ? <span className="sr-only">Playing now: </span> : null}
          {track.name}
        </p>
        <p className="text-caption flex items-center gap-1.5 text-fog">
          <span className="truncate">{artistLine(track.artists)}</span>
          {track.source === 'adapt' ? <Chip>added later</Chip> : null}
          {mark ? <Chip tone={mark.tone}>{mark.label}</Chip> : null}
        </p>
      </div>

      <span className="flex shrink-0 items-center gap-1" aria-label={`Energy ${dots} of 5`}>
        {[1, 2, 3, 4, 5].map((step) => (
          <span
            key={step}
            aria-hidden="true"
            className="size-1.5 rounded-full"
            style={{
              background: step <= dots ? hue : 'var(--color-hairline)',
              opacity: step <= dots ? 1 : 0.8,
            }}
          />
        ))}
      </span>

      <span className="text-caption shrink-0 text-fog tabular-nums">
        {clock(track.duration_ms)}
      </span>

      <a
        href={spotifyTrackUrl(track.spotify_track_id)}
        target="_blank"
        rel="noreferrer"
        aria-label={`Open ${track.name} in Spotify`}
        className="flex min-h-tap shrink-0 items-center px-1 text-fog transition-colors hover:text-mist"
      >
        <ExternalLink aria-hidden="true" size={16} />
      </a>
    </li>
  )
}

/** A small word beside the artist. Borderless, so it never competes with the song title. */
function Chip({ children, tone = 'quiet' }: { children: string; tone?: 'quiet' | 'warn' }) {
  return (
    <span
      className={cx(
        'shrink-0 rounded-full border border-hairline px-1.5 py-px whitespace-nowrap',
        tone === 'warn' ? 'text-danger' : 'text-fog',
      )}
    >
      {children}
    </span>
  )
}

/**
 * What became of one song — the exceptions only, so a bare row means it played.
 *
 * Marking every played song would put the same chip on twenty rows and say nothing; the
 * count at the top of the screen already reports how many played. So this labels the two
 * things that carry information: a song left early, and a song the session never reached.
 * The song playing now gets no mark either, because its verdict is not in yet and the row
 * already announces itself.
 *
 * A skip is the only one coloured, because it is the only one that is feedback: a skip is
 * what the ranking learns from, and running out of session is not a fault of the song.
 */
function outcomeOf(
  track: SessionTrack,
  current: boolean,
): { label: string; tone: 'quiet' | 'warn' } | null {
  if (current) return null
  if (track.skipped) return { label: 'skipped', tone: 'warn' }
  if (!track.started_at) return { label: 'not reached', tone: 'quiet' }
  return null
}
