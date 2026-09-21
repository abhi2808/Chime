import { Library, RefreshCw } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { StatFigure } from '../../components/StatFigure'
import { useLibrarySyncStatus, useStartLibrarySync } from '../../lib/queries'
import type { LibrarySyncStatus } from '../../lib/types'

const count = (value: number) => value.toLocaleString()

/** "in about 4 minutes", or null once the wait is over. */
function waitFor(resumeAfter: string | null): string | null {
  if (!resumeAfter) return null
  const seconds = Math.round((new Date(resumeAfter).getTime() - Date.now()) / 1000)
  if (!Number.isFinite(seconds) || seconds <= 0) return null
  if (seconds < 90) return `in about ${seconds} seconds`
  return `in about ${Math.round(seconds / 60)} minutes`
}

interface Line {
  headline: string
  detail: string
  /** 0-1 when we know enough to draw a bar. */
  progress: number | null
  action: 'sync' | 'resync' | 'resume' | 'retry' | null
}

function describe(status: LibrarySyncStatus): Line {
  switch (status.state) {
    case 'running':
      if (status.phase === 'artists') {
        return {
          headline: 'Tagging artists',
          detail: `${count(status.artists_fetched)} of ${count(status.artists_total)} artists`,
          progress: status.artists_total ? status.artists_fetched / status.artists_total : null,
          action: null,
        }
      }
      return {
        headline: 'Syncing liked songs',
        detail: status.tracks_total
          ? `${count(status.tracks_synced)} of ${count(status.tracks_total)} songs`
          : `${count(status.tracks_synced)} songs so far`,
        progress:
          status.tracks_total && status.tracks_total > 0
            ? status.tracks_synced / status.tracks_total
            : null,
        action: null,
      }
    case 'complete':
      return {
        headline: `${count(status.liked_tracks)} songs synced`,
        detail: status.artists_failed
          ? `Up to date. ${count(status.artists_failed)} artists could not be read.`
          : status.stopped_early
            ? 'Up to date. Only the newly liked songs were checked.'
            : 'Up to date.',
        progress: null,
        action: 'resync',
      }
    case 'partial': {
      const wait = waitFor(status.resume_after)
      const tagged = `${count(status.artists_with_genres)} artists tagged, ${count(status.artists_remaining)} to go.`
      return {
        headline: `${count(status.liked_tracks)} songs synced`,
        detail: wait
          ? `${tagged} Spotify asked us to slow down; resuming ${wait}.`
          : `${tagged} The rest comes in on the next sync.`,
        progress: null,
        action: 'resume',
      }
    }
    case 'interrupted':
      return {
        headline: 'Sync stopped part way',
        detail: `${count(status.liked_tracks)} songs are in so far. Picking up where it left off.`,
        progress: null,
        action: 'resume',
      }
    case 'error':
      return {
        headline: 'Sync stopped',
        detail: status.error ?? 'Spotify did not answer. Try again.',
        progress: null,
        action: 'retry',
      }
    default:
      return {
        headline: 'Your library is not synced yet',
        detail: 'Chime needs your liked songs before it can build a mix.',
        progress: null,
        action: 'sync',
      }
  }
}

const ACTION_LABEL: Record<NonNullable<Line['action']>, string> = {
  sync: 'Sync now',
  resync: 'Sync again',
  resume: 'Resume sync',
  retry: 'Try again',
}

export function LibrarySyncCard() {
  const { data: status, error } = useLibrarySyncStatus()
  const startSync = useStartLibrarySync()
  const resumed = useRef(false)

  // A run that stopped short finishes itself the next time Home opens, as long as any
  // rate-limit penalty has expired. Once per mount, so a failing resume cannot loop.
  const state = status?.state
  const resumable = state === 'partial' || state === 'interrupted'
  const waiting = waitFor(status?.resume_after ?? null) !== null
  useEffect(() => {
    if (!resumable || waiting || resumed.current) return
    resumed.current = true
    startSync.mutate({ full: false })
  }, [resumable, waiting, startSync])

  if (error) {
    return (
      <div className="glass rounded-sheet px-screen py-5">
        <p className="text-body text-fog" role="alert">
          {error.message}
        </p>
      </div>
    )
  }

  if (!status) {
    return <div className="glass h-[132px] rounded-sheet" aria-hidden="true" />
  }

  const line = describe(status)
  const running = status.state === 'running'

  return (
    <section className="glass rounded-sheet px-screen flex flex-col gap-4 py-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-caption flex items-center gap-2 text-fog">
            <Library aria-hidden="true" size={14} />
            Library
          </span>
          <h2 className="text-headline">{line.headline}</h2>
          <p className="text-caption text-fog">{line.detail}</p>
        </div>
        {line.action ? (
          <button
            type="button"
            onClick={() => startSync.mutate({ full: line.action === 'resync' })}
            disabled={startSync.isPending}
            className="text-caption min-h-tap flex shrink-0 items-center gap-2 rounded-full border border-hairline px-4 transition-colors hover:border-white/20 disabled:opacity-60"
          >
            <RefreshCw aria-hidden="true" size={14} />
            {ACTION_LABEL[line.action]}
          </button>
        ) : null}
      </div>

      {running ? (
        <div
          className="h-1 overflow-hidden rounded-full bg-white/10"
          role="progressbar"
          aria-label="Library sync progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={line.progress === null ? undefined : Math.round(line.progress * 100)}
        >
          <div
            className="h-full rounded-full bg-ember transition-[width] duration-500"
            style={{ width: line.progress === null ? '15%' : `${Math.min(100, line.progress * 100)}%` }}
          />
        </div>
      ) : null}

      {status.state === 'complete' || status.state === 'partial' ? (
        <div className="flex gap-8">
          <StatFigure label="Songs" value={count(status.liked_tracks)} />
          <StatFigure label="Artists" value={count(status.artists_with_genres)} hint="with genres" />
        </div>
      ) : null}

      {startSync.error ? (
        <p className="text-caption text-danger" role="alert">
          {startSync.error.message}
        </p>
      ) : null}
    </section>
  )
}
