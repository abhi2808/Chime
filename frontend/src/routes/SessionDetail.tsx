import { useState } from 'react'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { EmptyState } from '../components/EmptyState'
import { StatFigure } from '../components/StatFigure'
import { TrackRow } from '../components/TrackRow'
import { Timeline } from '../features/history/Timeline'
import { WhyThisMix } from '../features/session/WhyThisMix'
import { ApiError } from '../lib/api'
import { percent, strain } from '../lib/body'
import { dayLabel, duration, timeLabel } from '../lib/dates'
import { useDeleteSession, useRestoreSession, useSession } from '../lib/queries'
import { hueFor, moodLabel, typeLabel } from '../lib/types'
import type { Session, SessionBody } from '../lib/types'

/**
 * One session, months later: how you went in, what played, how it ended.
 *
 * The playlist it made is almost always gone by now — that is the point of a temporary
 * playlist — so the action here is "bring it back", which rebuilds one from the tracks we
 * stored rather than from anything of Spotify's.
 */
export function SessionDetail() {
  const { id } = useParams()
  const sessionId = Number(id)
  const { data: session, isPending, error } = useSession(Number.isFinite(sessionId) ? sessionId : null)

  if (isPending) {
    return <p className="text-caption text-fog">Loading…</p>
  }

  if (error || !session) {
    return (
      <EmptyState
        title="No such session"
        body={error instanceof ApiError ? error.message : 'It may have been deleted.'}
        action={
          <Link to="/history" className="text-body min-h-tap flex items-center px-4 underline">
            Back to history
          </Link>
        }
      />
    )
  }

  return <Detail session={session} />
}

function Detail({ session }: { session: Session }) {
  const hue = hueFor(session.type)
  const navigate = useNavigate()
  const restore = useRestoreSession(session.id)
  const remove = useDeleteSession()
  const [confirming, setConfirming] = useState(false)

  const from = moodLabel(session.mood_in)
  const to = moodLabel(session.mood_out)
  const summary = session.summary
  // Null plays means nobody was counting, which is different from counting zero. Everything
  // that reports an outcome per song is gated on this.
  const measured = summary?.played != null
  // Whichever playlist is actually there: the one it made if it was kept, else a rebuilt one.
  const openUrl = restore.data?.playlist_url ?? session.restored_playlist_url ?? session.playlist_url

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-4">
        <Link
          to="/history"
          className="text-caption flex min-h-tap items-center gap-2 self-start text-fog transition-colors hover:text-mist"
        >
          <ArrowLeft aria-hidden="true" size={16} />
          History
        </Link>

        <header className="flex flex-col gap-1">
          <span className="text-caption flex items-center gap-2 text-fog">
            <span aria-hidden="true" className="size-2 rounded-full" style={{ background: hue }} />
            {typeLabel(session.type)}
            {session.intent === 'shift' ? ' · shifting' : null}
          </span>
          <h1 className="text-title">
            {dayLabel(session.started_at)}, {timeLabel(session.started_at)}
          </h1>
          <p className="text-caption text-fog">
            {duration(summary?.minutes ?? 0)}
            {session.status === 'ended'
              ? session.kept
                ? ' · playlist kept'
                : ' · playlist removed'
              : session.status === 'failed'
                ? ' · never got playing'
                : ' · still open'}
          </p>
        </header>
      </div>

      <div className="glass flex flex-wrap gap-x-8 gap-y-4 rounded-tile p-4">
        <StatFigure
          label="Songs"
          value={String(summary?.played ?? session.tracks.length)}
          hint={summary?.played != null ? 'played' : 'queued'}
        />
        {summary?.skipped != null ? (
          <StatFigure
            label="Skips"
            value={String(summary.skipped)}
            hint={
              summary.skip_rate != null
                ? `${percent(summary.skip_rate * 100)} of plays`
                : undefined
            }
          />
        ) : null}
        {from || to ? (
          <StatFigure
            label="Mood"
            value={from && to ? `${from} → ${to}` : (from ?? to ?? '')}
            hint={from && to ? undefined : 'only one check-in'}
          />
        ) : null}
      </div>

      {/* A zero here would read as "you skipped nothing" rather than "nobody was counting",
          so an unmeasured session says so in words. It happens to every session recorded
          before Chime watched playback, and to any session played while the backend was down. */}
      {measured ? null : (
        <p className="text-caption text-fog">
          Chime wasn't watching playback during this session, so only what it queued is
          recorded — not what you actually heard.
        </p>
      )}

      <WhyThisMix session={session} />

      <BeforeAfter start={session.body_in} end={session.body_out} />

      {session.tracks.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-headline">Songs</h2>
          <ul className="flex flex-col gap-1">
            {session.tracks.map((track) => (
              <TrackRow key={track.position} track={track} hue={hue} outcome={measured} />
            ))}
          </ul>
        </section>
      ) : null}

      <Timeline events={session.events} />

      <section className="flex flex-col gap-2">
        {openUrl ? (
          <a
            href={openUrl}
            target="_blank"
            rel="noreferrer"
            className="text-body min-h-tap flex items-center justify-center gap-2 rounded-full font-semibold text-midnight transition-opacity hover:opacity-90"
            style={{ background: hue }}
          >
            <ExternalLink aria-hidden="true" size={16} />
            Open the playlist
          </a>
        ) : null}

        {session.tracks.length > 0 ? (
          <button
            type="button"
            onClick={() => restore.mutate()}
            disabled={restore.isPending}
            className="text-body glass min-h-tap rounded-full text-mist transition-colors hover:border-white/20 disabled:text-fog"
          >
            {restore.isPending
              ? 'Building the playlist…'
              : openUrl
                ? 'Bring it back again'
                : 'Bring it back as a playlist'}
          </button>
        ) : null}

        {restore.isSuccess ? (
          <p className="text-caption text-fog">
            {restore.data.tracks} songs are back in "{restore.data.name}". This one stays in your
            library until you remove it.
          </p>
        ) : null}

        {restore.isError ? (
          <p className="text-caption text-danger">
            {restore.error instanceof ApiError
              ? restore.error.message
              : 'Could not rebuild that playlist.'}
          </p>
        ) : null}

        {/* Two taps, because there is no undo. A kept playlist is untouched either way: this
            deletes Chime's record, not the user's music. */}
        {confirming ? (
          <div className="flex flex-col gap-2">
            <p className="text-caption text-fog">
              Delete this record? The songs and the timeline go with it
              {session.kept ? ', but the playlist you kept stays in Spotify' : ''}.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() =>
                  remove.mutate(session.id, { onSuccess: () => navigate('/history') })
                }
                disabled={remove.isPending}
                className="text-body min-h-tap flex-1 rounded-full border border-danger text-danger disabled:opacity-60"
              >
                {remove.isPending ? 'Deleting…' : 'Delete'}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="text-body glass min-h-tap flex-1 rounded-full"
              >
                Keep it
              </button>
            </div>
            {remove.isError ? (
              <p className="text-caption text-danger">
                {remove.error instanceof ApiError
                  ? remove.error.message
                  : 'Could not delete that session.'}
              </p>
            ) : null}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="text-caption min-h-tap self-center px-4 text-fog transition-colors hover:text-danger"
          >
            Delete this record
          </button>
        )}
      </section>
    </div>
  )
}

/**
 * The body either side of the session.
 *
 * WHOOP scores recovery and sleep once a day, so those two are the same number at both ends
 * by definition and are shown once. Strain climbs through the day, so it is the one figure
 * that can honestly be shown as a movement.
 */
function BeforeAfter({ start, end }: { start: SessionBody | null; end: SessionBody | null }) {
  if (!start || !start.connected) {
    return (
      <section className="flex flex-col gap-2">
        <h2 className="text-headline">Body</h2>
        <p className="text-body text-fog">
          WHOOP wasn't connected, so this mix came from your mood and the time of day.
        </p>
      </section>
    )
  }

  const recovery = percent(start.recovery)
  const sleep = percent(start.sleep_performance)
  const before = strain(start.day_strain)
  const after = strain(end?.day_strain ?? null)
  const moved = after !== null && after !== before

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-headline">Body</h2>
      <div className="glass flex flex-wrap gap-x-8 gap-y-4 rounded-tile p-4">
        {recovery ? <StatFigure label="Recovery" value={recovery} hint="that day" /> : null}
        {sleep ? <StatFigure label="Sleep" value={sleep} hint="that night" /> : null}
        {before ? (
          <StatFigure
            label="Strain"
            value={moved ? `${before} → ${after}` : before}
            hint={moved ? 'during the session' : 'at the start'}
          />
        ) : null}
        {!recovery && !sleep && !before ? (
          <p className="text-body text-fog">WHOOP hadn't scored that day when this started.</p>
        ) : null}
      </div>
    </section>
  )
}
