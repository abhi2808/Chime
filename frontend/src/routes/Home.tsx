import { useState } from 'react'

import { Orb } from '../components/Orb'
import { BodyFigures } from '../features/home/BodyFigures'
import { ChimeInSheet } from '../features/home/ChimeInSheet'
import { LastSessionCard } from '../features/home/LastSessionCard'
import { LibrarySyncCard } from '../features/home/LibrarySyncCard'
import { WhoopCard } from '../features/home/WhoopCard'
import { useBodyState, useMe } from '../lib/queries'

function greeting(hour: number): string {
  if (hour < 5) return 'Still up'
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

export function Home() {
  const { data: me } = useMe()
  const { data: body } = useBodyState()
  const [sheetOpen, setSheetOpen] = useState(false)

  const name = me?.display_name?.split(' ')[0]
  const hello = greeting(new Date().getHours())

  return (
    <div className="flex flex-col gap-8">
      <header className="rise flex flex-col gap-1">
        <h1 className="text-title">{name ? `${hello}, ${name}` : hello}</h1>
        {/* Nothing stands in for the figures when WHOOP is quiet: the card below says why. */}
        <BodyFigures state={body} />
      </header>

      {/* Before a session picks a real hue the orb sits on ember at reduced intensity. */}
      <div className="rise flex flex-col items-center gap-4 py-2">
        <Orb size={200} intensity={0.55} state="idle" onClick={() => setSheetOpen(true)} />
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          className="text-headline min-h-tap px-4"
        >
          Chime in
        </button>
      </div>

      <div className="rise flex flex-col gap-4">
        <LibrarySyncCard />
        <WhoopCard />
        <LastSessionCard />
      </div>

      <ChimeInSheet open={sheetOpen} onClose={() => setSheetOpen(false)} />
    </div>
  )
}
