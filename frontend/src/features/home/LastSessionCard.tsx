import { ListMusic } from 'lucide-react'

/** Placeholder for the real last-session card. Sessions do not exist until Phase 5. */
export function LastSessionCard() {
  return (
    <section className="glass rounded-sheet px-screen flex flex-col gap-1 py-5">
      <span className="text-caption flex items-center gap-2 text-fog">
        <ListMusic aria-hidden="true" size={14} />
        Last session
      </span>
      <h2 className="text-headline">Nothing here yet</h2>
      <p className="text-caption text-fog">
        Your most recent session will sit here once you have chimed in.
      </p>
    </section>
  )
}
