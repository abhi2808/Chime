import { Music, Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import type { ReactNode } from 'react'

import { artistLine, clock } from '../../lib/music'
import type { NowPlaying, Session, Transport } from '../../lib/types'

/**
 * The top of the Session screen: a ring of elapsed time around the artwork, which glows in
 * the session hue, and the transport underneath (docs/design/Session.dc.html).
 *
 * `playing` is null when Spotify has nothing to report — paused for long enough to drop the
 * player, or unreadable. The panel still stands, because the session is a fact either way
 * and Chime out has to stay reachable.
 */
/** Circumference of the r=116 ring. */
const RING = 2 * Math.PI * 116

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
    <section className="flex flex-col gap-[22px]">
      {/* Elapsed-time ring around the artwork, glowing in the session hue. */}
      <div className="flex justify-center py-1.5">
        <div className="relative size-[248px]">
          <svg
            width="248"
            height="248"
            viewBox="0 0 248 248"
            aria-hidden="true"
            className="absolute inset-0 -rotate-90"
          >
            <circle cx="124" cy="124" r="116" fill="none" stroke="var(--color-hairline)" strokeWidth="4" />
            <circle
              cx="124"
              cy="124"
              r="116"
              fill="none"
              stroke={hue}
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray={RING}
              strokeDashoffset={RING * (1 - elapsed)}
              className="transition-[stroke-dashoffset] duration-1000 ease-linear"
            />
          </svg>
          <div
            className="absolute inset-[18px] grid place-items-center overflow-hidden rounded-[22px]"
            style={{
              background: `linear-gradient(155deg, color-mix(in oklab, ${hue} 30%, var(--color-midnight)) 0%, color-mix(in oklab, ${hue} 10%, var(--color-midnight)) 60%, var(--color-midnight) 100%)`,
              boxShadow: `0 0 60px 6px color-mix(in oklab, ${hue} 22%, transparent)`,
            }}
          >
            {playing?.image_url ? (
              <img src={playing.image_url} alt="" width={212} height={212} className="size-full object-cover" />
            ) : (
              <Music aria-hidden="true" size={56} strokeWidth={1.3} className="text-white/55" />
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-col items-center gap-1 text-center">
        <h1 className="text-[19px] leading-tight font-bold">{title}</h1>
        {subtitle ? <p className="text-sm text-fog">{subtitle}</p> : null}
        {playing?.off_context ? (
          <p className="text-caption mt-1 text-fog">
            Playback moved off this session's playlist. Skipping will follow whatever is
            playing now.
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <div
          role="progressbar"
          aria-label="Song progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(fraction * 100)}
          className="h-1 overflow-hidden rounded-full bg-rim"
        >
          <div
            className="h-full rounded-full transition-[width] duration-500 ease-linear"
            style={{ width: `${fraction * 100}%`, background: hue }}
          />
        </div>
        <div className="flex justify-between text-xs text-fog tabular-nums">
          <span>{clock(played)}</span>
          <span>{clock(duration)}</span>
        </div>
      </div>

      <div className="flex items-center justify-center gap-7">
        <TransportButton label="Previous track" onClick={() => onTransport('previous')} disabled={pending}>
          <SkipBack aria-hidden="true" size={22} fill="currentColor" />
        </TransportButton>
        <button
          type="button"
          onClick={() => onTransport(playing?.is_playing ? 'pause' : 'resume')}
          disabled={pending}
          aria-label={playing?.is_playing ? 'Pause' : 'Play'}
          className="grid size-14 place-items-center rounded-full bg-mist text-midnight transition-opacity hover:opacity-90 focus-visible:rounded-full disabled:opacity-60"
        >
          {playing?.is_playing ? (
            <Pause aria-hidden="true" size={20} fill="currentColor" />
          ) : (
            <Play aria-hidden="true" size={20} fill="currentColor" />
          )}
        </button>
        <TransportButton label="Next track" onClick={() => onTransport('next')} disabled={pending}>
          <SkipForward aria-hidden="true" size={22} fill="currentColor" />
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
