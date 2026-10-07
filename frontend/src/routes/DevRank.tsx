/**
 * Ranking preview: a development screen, not part of the product.
 *
 * Phase 3 builds the ranking before there is a session or playback to hear it through,
 * so this shows what Chime in would queue and why. Nothing here starts anything.
 */

import { useState } from 'react'

import { MoodChips } from '../components/MoodChips'
import { SessionTypeSegment } from '../components/SessionTypeSegment'
import { cx } from '../lib/cx'
import { useRankPreview } from '../lib/queries'
import { moodId } from '../lib/types'
import type { Intent, Mood, RankedTrack, SessionType, TargetProfile } from '../lib/types'

const COMPONENTS: { key: keyof RankedTrack['breakdown']; label: string; weight: string }[] = [
  { key: 'energy_fit', label: 'Energy', weight: '50%' },
  { key: 'affinity', label: 'Affinity', weight: '25%' },
  { key: 'behavior', label: 'Behaviour', weight: '15%' },
  { key: 'freshness', label: 'Freshness', weight: '10%' },
]

/** Energy 1-5 as a fraction of the bar. */
function share(energy: number): string {
  return `${((energy - 1) / 4) * 100}%`
}

function Curve({ profile }: { profile: TargetProfile }) {
  const { curve } = profile
  return (
    <figure className="flex flex-col gap-2">
      <div aria-hidden="true" className="flex h-16 items-end gap-[3px]">
        {curve.map((value, index) => (
          <span
            key={index}
            className="flex-1 rounded-t-[3px] bg-mist/25"
            style={{ height: `${(value / 5) * 100}%` }}
          />
        ))}
      </div>
      <figcaption className="text-caption text-fog">
        Target energy, {profile.energy_start} to {profile.energy_end} across{' '}
        {curve.length} tracks{profile.ceiling < 5 ? `, capped at ${profile.ceiling}` : ''}.
      </figcaption>
    </figure>
  )
}

function Row({ track }: { track: RankedTrack }) {
  const { breakdown } = track
  const drift = breakdown.energy - breakdown.target

  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      <div className="flex items-baseline gap-3">
        <span className="text-caption w-6 shrink-0 text-fog">{track.position + 1}</span>
        <div className="min-w-0 flex-1">
          <p className="text-body truncate">{track.name}</p>
          <p className="text-caption truncate text-fog">{track.artists.join(', ')}</p>
        </div>
        <span className="text-body tabular-nums">{breakdown.score.toFixed(2)}</span>
      </div>

      <div className="flex items-center gap-3 pl-9">
        <div className="relative h-1.5 flex-1 rounded-full bg-white/8">
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 rounded-full bg-mist/40"
            style={{ width: share(breakdown.energy) }}
          />
          <span
            aria-hidden="true"
            className="absolute -top-1 h-3.5 w-px bg-mist"
            style={{ left: share(breakdown.target) }}
          />
        </div>
        <span className="text-caption tabular-nums text-fog">
          {breakdown.energy.toFixed(1)}
          <span className="text-fog/70">
            {' '}
            / {breakdown.target.toFixed(1)}
            {Math.abs(drift) >= 1 ? ` (${drift > 0 ? '+' : ''}${drift.toFixed(1)})` : ''}
          </span>
        </span>
      </div>

      <dl className="text-caption flex flex-wrap gap-x-4 gap-y-1 pl-9 text-fog">
        {COMPONENTS.map(({ key, label }) => (
          <div key={key} className="flex gap-1">
            <dt>{label}</dt>
            <dd className="tabular-nums text-mist/80">
              {(breakdown[key] as number).toFixed(2)}
            </dd>
          </div>
        ))}
        <div className="flex gap-1">
          <dt>Confidence</dt>
          <dd
            className={cx(
              'tabular-nums',
              breakdown.confidence === 0 ? 'text-danger' : 'text-mist/80',
            )}
          >
            {breakdown.confidence.toFixed(2)}
          </dd>
        </div>
      </dl>

      {breakdown.tags.length > 0 ? (
        <p className="text-caption pl-9 text-fog/70">{breakdown.tags.join(' · ')}</p>
      ) : (
        <p className="text-caption pl-9 text-fog/70">No tags — energy is an assumption.</p>
      )}
    </li>
  )
}

export function DevRank() {
  const [type, setType] = useState<SessionType['id']>('auto')
  const [mood, setMood] = useState<Mood | null>(null)
  const [intent, setIntent] = useState<Intent>('match')
  const [count, setCount] = useState(20)

  const options = { type, mood: mood ? moodId(mood) : null, intent, count }
  const { data, error, isFetching } = useRankPreview(options)

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-title">Ranking preview</h1>
        <p className="text-caption text-fog">
          A development view of the engine. Nothing here creates a session, builds a playlist
          or plays anything.
        </p>
      </header>

      <section className="flex flex-col gap-3">
        <h2 className="text-caption text-fog">Inputs</h2>
        <SessionTypeSegment value={type} onChange={setType} />
        <MoodChips value={mood} onChange={setMood} label="Mood" />
        <div className="flex flex-wrap items-center gap-3">
          <div role="radiogroup" aria-label="Intent" className="glass flex gap-1 rounded-tile p-1">
            {(['match', 'shift'] as const).map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={intent === option}
                tabIndex={intent === option ? 0 : -1}
                onClick={() => setIntent(option)}
                className={cx(
                  'text-caption min-h-tap rounded-[14px] px-4 transition-colors',
                  intent === option ? 'bg-white/12 text-mist' : 'text-fog hover:text-mist',
                )}
              >
                {option === 'match' ? 'Match how I feel' : 'Shift me out of it'}
              </button>
            ))}
          </div>
          <label className="text-caption flex items-center gap-2 text-fog">
            Tracks
            <input
              type="number"
              min={1}
              max={100}
              value={count}
              onChange={(event) => setCount(Number(event.target.value) || 1)}
              className="glass text-body min-h-tap w-20 rounded-tile px-3 tabular-nums"
            />
          </label>
          {mood ? (
            <button
              type="button"
              onClick={() => setMood(null)}
              className="text-caption min-h-tap text-fog underline decoration-hairline hover:text-mist"
            >
              Clear mood
            </button>
          ) : null}
        </div>
      </section>

      {error ? (
        <p className="text-caption text-danger" role="alert">
          {error.message}
        </p>
      ) : null}

      {data ? (
        <>
          <section className="glass flex flex-col gap-4 rounded-sheet p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-headline">
                {data.profile.type.replace('_', ' ')}
                <span className="text-caption text-fog"> · {data.profile.intent}</span>
              </h2>
              <p className="text-caption text-fog">
                {data.pool.size} tracks in the pool, {data.pool.tagged} tagged, mean confidence{' '}
                {data.pool.mean_confidence.toFixed(2)}
              </p>
            </div>

            <Curve profile={data.profile} />

            {data.profile.notes.length > 0 ? (
              <ul className="text-caption flex flex-col gap-1 text-fog">
                {data.profile.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}

            <p className="text-caption text-fog">
              Wants{' '}
              {Object.entries(data.profile.affinities)
                .filter(([, weight]) => weight > 0)
                .map(([name, weight]) => `${name.replace('_', ' ')} ${weight}`)
                .join(', ')}
              .{data.body.connected ? '' : ' WHOOP is not connected, so this is mood and clock only.'}
            </p>
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="text-caption text-fog">
                Running order · the bar is energy, the tick is the target
              </h2>
              {isFetching ? <span className="text-caption text-fog">Ranking…</span> : null}
            </div>
            {data.tracks.length > 0 ? (
              <ol className="glass divide-y divide-hairline rounded-sheet">
                {data.tracks.map((track) => (
                  <Row key={track.track_id} track={track} />
                ))}
              </ol>
            ) : (
              <p className="text-caption text-fog">
                Nothing to rank yet. Sync your library on Home first.
              </p>
            )}
          </section>
        </>
      ) : null}
    </div>
  )
}
