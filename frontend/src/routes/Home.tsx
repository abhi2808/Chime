import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Orb } from '../components/Orb'
import { PetalRing } from '../components/PetalRing'
import { SettingsButton } from '../components/SettingsButton'
import { BodyFigures } from '../features/home/BodyFigures'
import { ChimeInSheet } from '../features/home/ChimeInSheet'
import { LastSessionCard } from '../features/home/LastSessionCard'
import { homeLine } from '../lib/homeLine'
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
  const line = live ? 'A session is playing. The orb takes you back to it.' : homeLine(body)

  return (
    <div className="flex flex-col gap-6">
      <header className="rise flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-title">{name ? `${hello}, ${name}` : hello}</h1>
          <BodyFigures state={body} />
        </div>
        <SettingsButton />
      </header>

      {/* The dial: orb in the middle, and from 880 px the petal ring around it. Before a
          session the sphere is ember; once one is running it takes that session's hue and
          leads back to it — there is nothing to chime into while something is playing. */}
      <div className="rise relative h-[270px] w-full dial:h-[480px]">
        <PetalRing />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
          {live ? (
            <Orb
              hue={hueFor(live.type)}
              aura
              word="Your session"
              label="Open the session"
              onClick={() => navigate('/session')}
            />
          ) : (
            <Orb
              aura
              word="Chime in"
              state={hold.phase}
              onClick={hold.handlers.onClick}
              gesture={hold.handlers}
            />
          )}
        </div>
        {/* Under reduced motion the orb does not move, so the caption carries the hold. The
            700ms delay keeps it off screen for an ordinary tap; reduced motion shortens
            durations, not delays, so it still appears on time there. */}
        <span
          aria-hidden="true"
          className="text-caption absolute inset-x-0 bottom-0 text-center text-ember-soft transition-opacity delay-700 duration-200 dial:bottom-2"
          style={{ opacity: hold.phase === 'idle' ? 0 : 1 }}
        >
          Somewhere else
        </span>
      </div>

      {line ? (
        <p className="rise mx-auto max-w-[320px] text-center text-sm leading-normal text-fog">
          {line}
        </p>
      ) : null}

      <div className="rise">
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
