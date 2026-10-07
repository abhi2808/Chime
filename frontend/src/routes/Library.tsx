import { LibrarySyncCard } from '../features/home/LibrarySyncCard'

/**
 * Where the songs Chime picks from come from. For now that is liked songs only, synced from
 * Spotify; the card used to sit on Home and moved here when the petal ring took over its job
 * of saying how many songs are in.
 */
export function Library() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-title">Library</h1>
        <p className="text-caption text-fog">
          Chime builds every mix from your liked songs on Spotify.
        </p>
      </header>
      <LibrarySyncCard />
    </div>
  )
}
