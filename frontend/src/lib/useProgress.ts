import { useEffect, useState } from 'react'

import type { NowPlaying } from './types'

const TICK_MS = 500

/**
 * Where the song has got to, between polls.
 *
 * `GET /me/player` is read every five seconds, which would make the progress line jump in
 * five-second steps. This carries it forward locally and is corrected by every poll, so it
 * is an estimate that never drifts far and never contradicts Spotify.
 */
export function useProgress(playing: NowPlaying | null | undefined): number | null {
  const reported = playing?.progress_ms ?? null
  const [progress, setProgress] = useState<number | null>(reported)

  // Snap to whatever the last poll said, including after a skip.
  useEffect(() => {
    setProgress(reported)
  }, [reported, playing?.spotify_track_id])

  const running = Boolean(playing?.is_playing) && reported !== null
  const duration = playing?.duration_ms ?? 0

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      setProgress((current) =>
        current === null ? current : Math.min(duration || current + TICK_MS, current + TICK_MS),
      )
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [running, duration])

  return progress
}
