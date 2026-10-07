import { useSearchParams } from 'react-router-dom'

import { EmptyState } from '../components/EmptyState'
import { SessionCard } from '../components/SessionCard'
import { WeekCard } from '../features/history/WeekCard'
import { dayKey, dayLabel } from '../lib/dates'
import { cx } from '../lib/cx'
import { useSessionList } from '../lib/queries'
import { MOODS, SESSION_TYPES, moodId } from '../lib/types'
import type { MoodId, SessionFilters, SessionListItem } from '../lib/types'

/** Auto is not a filter: the engine resolves it, so no stored session is ever of that type. */
const TYPE_FILTERS = SESSION_TYPES.filter((type) => type.id !== 'auto')

/**
 * Every session, newest first, grouped by the day it happened on.
 *
 * Filters live in the URL rather than in state, so a filtered list can be reloaded, kept in
 * a back button, or sent to yourself as a link — and each combination gets its own cache
 * entry for free.
 */
export function History() {
  const [params, setParams] = useSearchParams()
  const type = params.get('type')
  const mood = params.get('mood') as MoodId | null
  const kept = params.get('kept') === '1'

  const filters: SessionFilters = {
    ...(type ? { type } : {}),
    ...(mood ? { mood_in: mood } : {}),
    ...(kept ? { kept: true } : {}),
  }
  const list = useSessionList(filters)

  // A chip toggles: tapping the one already on takes the filter off again.
  const toggle = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (next.get(key) === value) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const sessions = list.data?.pages.flatMap((page) => page.sessions) ?? []
  const total = list.data?.pages[0]?.total ?? 0
  const filtered = Boolean(type || mood || kept)

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title">History</h1>

      <WeekCard />

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          {TYPE_FILTERS.map((option) => (
            <Chip
              key={option.id}
              label={option.label}
              on={type === option.id}
              hue={option.hue}
              onClick={() => toggle('type', option.id)}
            />
          ))}
          <Chip label="Kept" on={kept} onClick={() => toggle('kept', '1')} />
        </div>
        <div className="flex flex-wrap gap-2">
          {MOODS.map((option) => (
            <Chip
              key={option}
              label={option}
              on={mood === moodId(option)}
              onClick={() => toggle('mood', moodId(option))}
            />
          ))}
        </div>
      </div>

      {list.isPending ? <p className="text-caption text-fog">Loading…</p> : null}

      {list.isError ? (
        <p className="text-caption text-danger">
          Could not load your history. {(list.error as Error).message}
        </p>
      ) : null}

      {!list.isPending && sessions.length === 0 ? (
        <EmptyState
          title={filtered ? 'Nothing matches those filters' : 'No sessions yet'}
          body={
            filtered
              ? 'Turn a filter off to see the rest.'
              : 'Chime in and they will show up here.'
          }
          action={
            filtered ? (
              <button
                type="button"
                onClick={() => setParams(new URLSearchParams(), { replace: true })}
                className="text-body min-h-tap px-4 underline"
              >
                Clear filters
              </button>
            ) : undefined
          }
        />
      ) : null}

      {groupByDay(sessions).map(([key, day]) => (
        <section key={key} className="flex flex-col gap-2">
          <h2 className="text-caption sticky top-0 z-10 bg-midnight/80 py-1 text-fog backdrop-blur">
            {dayLabel(day[0].started_at)}
          </h2>
          <ul className="flex flex-col gap-2">
            {day.map((session) => (
              <SessionCard key={session.id} session={session} />
            ))}
          </ul>
        </section>
      ))}

      {list.hasNextPage ? (
        <button
          type="button"
          onClick={() => void list.fetchNextPage()}
          disabled={list.isFetchingNextPage}
          className="glass text-body min-h-tap rounded-full px-4 disabled:text-fog"
        >
          {list.isFetchingNextPage ? 'Loading…' : `Load more (${sessions.length} of ${total})`}
        </button>
      ) : null}
    </div>
  )
}

/** Consecutive sessions on the same local day. The list is already newest first. */
function groupByDay(sessions: SessionListItem[]): [string, SessionListItem[]][] {
  const days: [string, SessionListItem[]][] = []
  for (const session of sessions) {
    const key = dayKey(session.started_at)
    const last = days.at(-1)
    if (last && last[0] === key) last[1].push(session)
    else days.push([key, [session]])
  }
  return days
}

function Chip({
  label,
  on,
  hue,
  onClick,
}: {
  label: string
  on: boolean
  /** A type's own colour, so the chips read as the same language as the cards. */
  hue?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cx(
        'text-caption flex min-h-tap items-center gap-2 rounded-full px-4 transition-colors',
        on ? 'bg-white/12 text-mist' : 'glass text-fog hover:text-mist',
      )}
    >
      {hue ? (
        <span
          aria-hidden="true"
          className="size-2 rounded-full"
          style={{ background: hue, opacity: on ? 1 : 0.55 }}
        />
      ) : null}
      {label}
    </button>
  )
}
