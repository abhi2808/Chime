/**
 * Day and time labels for History.
 *
 * All of it on the browser's own clock. The backend stores UTC and filters by UTC days,
 * which is right for a query; a person reading a list wants the day they lived through, so
 * the grouping happens here where the timezone is known.
 */

/** A stable key for "the same local day", for grouping. Not shown to anyone. */
export function dayKey(iso: string): string {
  const date = new Date(iso)
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
}

/** "Today", "Yesterday", "Mon 3 Sep", or "3 Sep 2025" once the year has turned. */
export function dayLabel(iso: string): string {
  const date = new Date(iso)
  const today = new Date()
  if (dayKey(iso) === dayKey(today.toISOString())) return 'Today'

  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (dayKey(iso) === dayKey(yesterday.toISOString())) return 'Yesterday'

  if (date.getFullYear() !== today.getFullYear()) {
    return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
  }
  return date.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

/** "9:20 am", on whatever the browser's locale calls that. */
export function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/** "42 min", or "1 h 12 min" once it is long enough that minutes stop being readable. */
export function duration(minutes: number): string {
  const whole = Math.round(minutes)
  if (whole < 60) return `${whole} min`
  const hours = Math.floor(whole / 60)
  const rest = whole % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

/** Today as `YYYY-MM-DD` on the local clock, for a date filter the user typed. */
export function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}
