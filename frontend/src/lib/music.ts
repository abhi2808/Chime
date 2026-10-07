/** Formatting for tracks and playback. Spotify links are built here so every row uses
 *  the same one — the design guidelines ask that songs link back to Spotify. */

export function spotifyTrackUrl(spotifyTrackId: string): string {
  return `https://open.spotify.com/track/${spotifyTrackId}`
}

/** "1:12". Anything unreadable becomes "0:00" rather than NaN. */
export function clock(ms: number | null | undefined): string {
  const total = Math.max(0, Math.floor((ms ?? 0) / 1000))
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(total % 60).padStart(2, '0')}`
}

export function artistLine(artists: string[]): string {
  return artists.join(', ')
}

/** Energy is the engine's 1-5 scale, drawn as five dots. Untagged tracks show none. */
export function energyDots(energy: number | null): number {
  if (energy === null) return 0
  return Math.min(5, Math.max(1, Math.round(energy)))
}

/** Whole minutes since an ISO timestamp, for the session timer. */
export function minutesSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60_000))
}
