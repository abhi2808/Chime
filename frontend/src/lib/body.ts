/** Formatting for WHOOP figures. Nothing here invents a number WHOOP did not send. */

import type { BodyState } from './types'

/** "41%", or null when WHOOP has not scored it yet. */
export function percent(value: number | null): string | null {
  return value === null ? null : `${Math.round(value)}%`
}

/** Day strain is a 0-21 scale; WHOOP shows one decimal, so we do too. */
export function strain(value: number | null): string | null {
  return value === null ? null : value.toFixed(1)
}

/** "90 minutes ago", "2 hours ago", "yesterday". */
export function agoFromMinutes(minutes: number | null): string | null {
  if (minutes === null || !Number.isFinite(minutes)) return null
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

export function ago(iso: string | null): string | null {
  if (!iso) return null
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000)
  return agoFromMinutes(Number.isFinite(minutes) ? Math.max(0, minutes) : null)
}

export interface Figure {
  label: string
  value: string
}

/**
 * The figures WHOOP has actually scored, in the order DESIGN lists them. A day
 * mid-morning has strain but no recovery yet, so this can be one item or none.
 */
export function figures(state: BodyState): Figure[] {
  const candidates: [string, string | null][] = [
    ['Recovery', percent(state.recovery)],
    ['Sleep', percent(state.sleep_performance)],
    ['Strain', strain(state.day_strain)],
  ]
  return candidates
    .filter((pair): pair is [string, string] => pair[1] !== null)
    .map(([label, value]) => ({ label, value }))
}
