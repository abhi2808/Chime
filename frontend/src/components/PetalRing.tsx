import { Link, useLocation } from 'react-router-dom'

import { useBodyState, useLibrarySyncStatus } from '../lib/queries'

interface Petal {
  key: string
  to: string
  label: string
  /** Arc geometry from docs/design/Home.dc.html: radius 170 in a 460 box, centre 230,230.
   *  The bottom two run counter-clockwise so their labels read left to right. */
  d: string
}

const PETALS: Petal[] = [
  { key: 'home', to: '/', label: 'Home', d: 'M 163.58 73.51 A 170 170 0 0 1 296.42 73.51' },
  { key: 'history', to: '/history', label: 'History', d: 'M 358.30 118.46 A 170 170 0 0 1 399.35 244.82' },
  { key: 'insights', to: '/insights', label: 'Insights', d: 'M 268.25 395.65 A 170 170 0 0 0 375.72 317.55' },
  { key: 'library', to: '/library', label: 'Library', d: 'M 84.28 317.55 A 170 170 0 0 0 191.75 395.65' },
  { key: 'whoop', to: '/settings', label: 'WHOOP', d: 'M 60.65 244.82 A 170 170 0 0 1 101.70 118.46' },
]

/**
 * Five arc sectors around the orb, clockwise from the top: Home, History, Insights, Library,
 * WHOOP. Only drawn from 880 px, where there is room for them; below that the tab bar does
 * the same job. Each petal is a real link, so Tab walks the ring and Enter follows it.
 *
 * Two petals carry data: Library shows how many songs are synced, and WHOOP a dot for whether
 * the grant is alive. WHOOP has no screen of its own, so it leads to Settings, where connect
 * and reconnect live.
 */
export function PetalRing() {
  const { pathname } = useLocation()
  const { data: library } = useLibrarySyncStatus()
  const { data: body } = useBodyState()

  const songs = library && library.liked_tracks > 0 ? library.liked_tracks.toLocaleString() : null
  const whoopOn = body ? body.connected && !body.needs_reconnect : null

  const aria = (petal: Petal): string => {
    if (petal.key === 'library' && songs) return `Library, ${songs} songs synced`
    if (petal.key === 'whoop' && whoopOn !== null) {
      return whoopOn ? 'WHOOP, connected' : body?.needs_reconnect ? 'WHOOP, needs reconnecting' : 'WHOOP, not connected'
    }
    return petal.label
  }

  return (
    <svg
      width="460"
      height="460"
      viewBox="0 0 460 460"
      className="absolute top-1/2 left-1/2 hidden -translate-x-1/2 -translate-y-1/2 overflow-visible dial:block"
    >
      <defs>
        {PETALS.map((petal) => (
          <path key={petal.key} id={`petal-arc-${petal.key}`} d={petal.d} />
        ))}
      </defs>

      {PETALS.map((petal) => {
        const active = petal.to === '/' ? pathname === '/' : pathname.startsWith(petal.to)
        return (
          <Link
            key={petal.key}
            to={petal.to}
            aria-label={aria(petal)}
            aria-current={active ? 'page' : undefined}
            className="petal"
          >
            <path className="petal-edge" d={petal.d} fill="none" strokeWidth="48" strokeLinecap="round" />
            <path className="petal-well" d={petal.d} fill="none" strokeWidth="46" strokeLinecap="round" />
            <path className="petal-band" d={petal.d} fill="none" strokeWidth="46" strokeLinecap="round" />
            <text
              className="petal-label"
              fontSize="12"
              fontWeight="650"
              letterSpacing="1.2"
              dominantBaseline="middle"
              aria-hidden="true"
            >
              <textPath href={`#petal-arc-${petal.key}`} startOffset="50%" textAnchor="middle">
                {petal.key === 'whoop' && whoopOn !== null ? (
                  <tspan className={whoopOn ? 'petal-dot-on' : 'petal-dot-off'}>● </tspan>
                ) : null}
                {petal.label.toUpperCase()}
                {petal.key === 'library' && songs ? (
                  <tspan className="petal-count" fontWeight="500">
                    {' '}
                    {songs}
                  </tspan>
                ) : null}
              </textPath>
            </text>
          </Link>
        )
      })}
    </svg>
  )
}
