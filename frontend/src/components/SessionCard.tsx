import { Bookmark } from 'lucide-react'
import { Link } from 'react-router-dom'

import { duration, timeLabel } from '../lib/dates'
import { hueFor, moodLabel, typeLabel } from '../lib/types'
import type { SessionListItem } from '../lib/types'

/**
 * One session in a list: when it was, what kind, how the mood moved, how long it ran.
 *
 * Songs are reported as "queued" unless something actually counted plays, because the number
 * we have is how many went into the playlist. The covers are decoration and carry no alt
 * text — the words next to them already say what this card is.
 */
export function SessionCard({ session }: { session: SessionListItem }) {
  const hue = hueFor(session.type)
  const from = moodLabel(session.mood_in)
  const to = moodLabel(session.mood_out)
  // Skips only join the line when there were some: "0 skipped" spends a line on nothing.
  const songs =
    session.played !== null
      ? `${session.played} played${session.skipped ? ` · ${session.skipped} skipped` : ''}`
      : `${session.queued} queued`

  return (
    <li>
      <Link
        to={`/history/${session.id}`}
        className="glass flex items-center gap-3 rounded-tile p-3 transition-colors hover:bg-white/6"
      >
        <Covers images={session.images} hue={hue} />

        <span className="min-w-0 flex-1">
          <span className="text-body flex items-center gap-2">
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-full"
              style={{ background: hue }}
            />
            <span className="truncate">{typeLabel(session.type)}</span>
            {session.kept ? (
              <Bookmark
                size={13}
                aria-label="Playlist kept"
                className="shrink-0 text-fog"
              />
            ) : null}
          </span>
          <span className="text-caption block truncate text-fog">
            {timeLabel(session.started_at)} · {duration(session.minutes)} · {songs}
          </span>
          {from || to ? (
            <span className="text-caption block truncate text-fog">
              {from && to ? `${from} → ${to}` : (from ?? to)}
            </span>
          ) : null}
        </span>
      </Link>
    </li>
  )
}

/**
 * Up to four covers, overlapped. A session with no artwork gets one tile in its own hue
 * rather than an empty gap, so every row is the same height.
 */
function Covers({ images, hue }: { images: string[]; hue: string }) {
  if (images.length === 0) {
    return (
      <span
        aria-hidden="true"
        className="size-12 shrink-0 rounded-art"
        style={{ background: hue, opacity: 0.3 }}
      />
    )
  }

  return (
    <span aria-hidden="true" className="flex shrink-0 -space-x-6">
      {images.map((image, index) => (
        <img
          key={image}
          src={image}
          alt=""
          width={48}
          height={48}
          loading="lazy"
          className="size-12 rounded-art object-cover ring-1 ring-midnight"
          style={{ zIndex: images.length - index }}
        />
      ))}
    </span>
  )
}
