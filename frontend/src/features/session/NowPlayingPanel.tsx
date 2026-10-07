import { Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'

import { Orb } from '../../components/Orb'
import { artistLine, clock } from '../../lib/music'
import type { NowPlaying, Session, Transport } from '../../lib/types'

/**
 * The top of the Session screen: a ring of elapsed time around the artwork, with the orb
 * glowing behind it in the session hue, and the transport underneath.
 *
 * `playing` is null when Spotify has nothing to report — paused for long enough to drop the
 * player, or unreadable. The panel still stands, because the session is a fact either way
 * and Chime out has to stay reachable.
 */
export function NowPlayingPanel({
  session,
  playing,
  note,
  hue,
  elapsed,
  progress,
  onTransport,
  pending,
}: {
  session: Session
  playing: NowPlaying | null
  note: string | null
  hue: string
  /** 0-1 of the queued playlist's length, for the ring. */
  elapsed: number
  /** Milliseconds into the current song, smoothed between polls. */
  progress: number | null
  onTransport: (action: Transport) => void
  pending: boolean
}) {
  const duration = playing?.duration_ms ?? 0
  const played = progress ?? 0
  const fraction = duration > 0 ? Math.min(1, played / duration) : 0
  const title = playing?.name ?? session.playlist_name ?? 'Nothing playing'
  const subtitle = playing ? artistLine(playing.artists) : (note ?? '')

  return (
    <section className="flex flex-col items-center gap-5">
      <div className="relative grid size-[280px] place-items-center">
        <div
          aria-hidden="true"
          className="ring absolute inset-0"
          style={{ '--ring-hue': hue, '--ring-progress': elapsed } as CSSProperties}
        />
        {/* The glow behind the art is the same orb, breathing while the music runs. */}
        <Orb
          hue={hue}
          size={216}
          intensity={0.7}
          state={playing?.is_playing ? 'pulsing' : 'idle'}
          className="absolute"
        />
        {playing?.image_url ? (
          <img
            src={playing.image_url}
            alt=""
            width={192}
            height={192}
            className="relative size-48 rounded-art object-cover shadow-none"
          />
        ) : null}
      </div>

      <div className="flex flex-col items-center gap-1 text-center">
        <h1 className="text-headline">{title}</h1>
        {subtitle ? <p className="text-body text-fog">{subtitle}</p> : null}
        {playing?.off_context ? (
          <p className="text-caption text-fog">
            Playback moved off this session's playlist. Skipping will follow whatever is
            playing now.
          </p>
        ) : null}
      </div>

      <div className="flex w-full max-w-sm flex-col gap-1">
        <div
          role="progressbar"
          aria-label="Song progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(fraction * 100)}
          className="relative h-1 rounded-full bg-hairline"
        >
          <div
            className="h-full rounded-full transition-[width] duration-500 ease-linear"
            style={{ width: `${fraction * 100}%`, background: hue }}
          />
          <span
            aria-hidden="true"
            className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-mist transition-[left] duration-500 ease-linear"
            style={{ left: `${fraction * 100}%` }}
          />
        </div>
        <div className="text-caption flex justify-between text-fog tabular-nums">
          <span>{clock(played)}</span>
          <span>{clock(duration)}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <TransportButton label="Previous" onClick={() => onTransport('previous')} disabled={pending}>
          <SkipBack aria-hidden="true" size={22} />
        </TransportButton>
        <button
          type="button"
          onClick={() => onTransport(playing?.is_playing ? 'pause' : 'resume')}
          disabled={pending}
          aria-label={playing?.is_playing ? 'Pause' : 'Play'}
          style={{ background: hue }}
          className="grid size-14 place-items-center rounded-full text-midnight transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {playing?.is_playing ? (
            <Pause aria-hidden="true" size={24} />
          ) : (
            <Play aria-hidden="true" size={24} />
          )}
        </button>
        <TransportButton label="Next" onClick={() => onTransport('next')} disabled={pending}>
          <SkipForward aria-hidden="true" size={22} />
        </TransportButton>
      </div>
    </section>
  )
}

function TransportButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  disabled: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="grid min-h-tap min-w-tap place-items-center rounded-full text-mist transition-colors hover:bg-white/8 disabled:text-fog"
    >
      {children}
    </button>
  )
}
