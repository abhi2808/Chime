import { useCallback, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Orb } from '../components/Orb'
import { BodyFigures } from '../features/home/BodyFigures'
import { ChimeInSheet } from '../features/home/ChimeInSheet'
import { LastSessionCard } from '../features/home/LastSessionCard'
import { LibrarySyncCard } from '../features/home/LibrarySyncCard'
import { WhoopCard } from '../features/home/WhoopCard'
import { useActiveSession, useBodyState, useMe } from '../lib/queries'
import { hueFor } from '../lib/types'
import type { Intent } from '../lib/types'
import { useHold } from '../lib/useHold'

function greeting(hour: number): string {
  if (hour < 5) return 'Still up'
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

export function Home() {
  const { data: me } = useMe()
  const { data: body } = useBodyState()
  const { data: active } = useActiveSession()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [intent, setIntent] = useState<Intent>('match')
  const navigate = useNavigate()

  const live = active?.session ?? null

  const openWith = useCallback((next: Intent) => {
    setIntent(next)
    setSheetOpen(true)
  }, [])

  // A tap opens the sheet as "here"; holding for 1.2s bursts the orb and opens it as
  // "somewhere else". Keyboard activation goes through onTap, which is why there is no
  // hold gesture to announce.
  const hold = useHold({
    onTap: () => openWith('match'),
    onHold: () => openWith('shift'),
    disabled: live !== null,
  })

  const name = me?.display_name?.split(' ')[0]
  const hello = greeting(new Date().getHours())

  return (
    <div className="flex flex-col gap-8">
      <header className="rise flex flex-col gap-1">
        <h1 className="text-title">{name ? `${hello}, ${name}` : hello}</h1>
        {/* Nothing stands in for the figures when WHOOP is quiet: the card below says why. */}
        <BodyFigures state={body} />
      </header>

      {/* Before a session picks a real hue the orb sits on ember at reduced intensity. Once
          one is running it takes that session's hue and breathes, and leads back to it —
          there is nothing to chime into while something is already playing. */}
      <div className="rise flex flex-col items-center gap-4 py-2">
        {live ? (
          <>
            <Orb
              hue={hueFor(live.type)}
              size={200}
              intensity={0.85}
              state="pulsing"
              label="Open the session"
              onClick={() => navigate('/session')}
            />
            <Link to="/session" className="text-headline min-h-tap flex items-center px-4">
              Back to your session
            </Link>
          </>
        ) : (
          <>
            <Orb
              size={200}
              intensity={0.55}
              state={hold.phase}
              onClick={hold.handlers.onClick}
              gesture={hold.handlers}
            />
            <button
              type="button"
              onClick={() => openWith('match')}
              className="text-headline min-h-tap px-4"
            >
              Chime in
            </button>
          </>
        )}
        {/* Under reduced motion the orb does not move, so the caption carries the hold. The
            700ms delay is what keeps it off screen for an ordinary tap; reduced motion
            shortens durations, not delays, so it still appears on time there. */}
        <span
          aria-hidden="true"
          className="text-caption text-fog transition-opacity delay-700 duration-200"
          style={{ opacity: hold.phase === 'idle' ? 0 : 1 }}
        >
          Somewhere else
        </span>
      </div>

      <div className="rise flex flex-col gap-4">
        <LibrarySyncCard />
        <WhoopCard />
        <LastSessionCard />
      </div>

      <ChimeInSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        initialIntent={intent}
      />
    </div>
  )
}
