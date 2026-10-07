import type { ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

import { cx } from '../lib/cx'
import { useActiveSession } from '../lib/queries'
import { MiniPlayer } from './MiniPlayer'
import { SettingsButton } from './SettingsButton'

interface NavItem {
  to: string
  label: string
  icon: ReactNode
}

// Line icons from docs/design/Home.dc.html, drawn at the tab bar's stroke weight.
const svg = (children: ReactNode) => (
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    aria-hidden="true"
  >
    {children}
  </svg>
)

const NAV: NavItem[] = [
  {
    to: '/',
    label: 'Home',
    icon: svg(
      <>
        <path d="M3 11l9-7 9 7" />
        <path d="M5 10v9a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1v-9" />
      </>,
    ),
  },
  {
    to: '/history',
    label: 'History',
    icon: svg(
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 3" />
      </>,
    ),
  },
  {
    to: '/insights',
    label: 'Insights',
    icon: svg(
      <>
        <path d="M12 20V10" />
        <path d="M18 20V4" />
        <path d="M6 20v-6" />
      </>,
    ),
  },
  {
    to: '/library',
    label: 'Library',
    icon: svg(<path d="M4 5v14M9 5v14M14 5l5 14" />),
  },
]

/**
 * Below 880 px: a bottom tab bar with Home, History, Insights, Library, and Settings behind
 * the gear on Home. From 880 px Home draws its own navigation as the petal ring, so the tab
 * bar goes away there; every other screen gets a slim top bar instead, because without one
 * the only way off History would be the browser's back button.
 */
export function AppShell() {
  const { data: active } = useActiveSession()
  const { pathname } = useLocation()
  const home = pathname === '/'

  return (
    <div className="min-h-dvh">
      {home ? null : (
        <header className="mx-auto hidden w-full max-w-content items-center justify-between gap-4 px-screen pt-7 dial:flex">
          <Link to="/" className="text-headline flex min-h-tap items-center gap-3 rounded-full pr-2">
            <span aria-hidden="true" className="orb-mark orb-hue-ember" />
            Chime
          </Link>
          <nav aria-label="Sections" className="flex items-center gap-1">
            {NAV.slice(1).map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cx(
                    'text-caption flex min-h-tap items-center rounded-full px-4 transition-colors',
                    isActive ? 'bg-white/8 text-ember-soft' : 'text-fog hover:text-mist',
                  )
                }
              >
                {label}
              </NavLink>
            ))}
            <span className="ml-2">
              <SettingsButton />
            </span>
          </nav>
        </header>
      )}

      {/* The mini player sits over the content, so a live session buys extra clearance. */}
      <main
        className={cx(
          'mx-auto w-full px-screen',
          home ? 'max-w-home pt-7 dial:max-w-dial' : 'max-w-content pt-8 dial:pt-6',
          active?.session ? 'pb-48 dial:pb-28' : 'pb-28 dial:pb-12',
        )}
      >
        <Outlet />
      </main>

      <MiniPlayer />

      <nav
        aria-label="Sections"
        className="fixed inset-x-0 bottom-0 z-40 flex justify-center border-t border-white/8 bg-midnight/85 pt-3 pb-[max(16px,env(safe-area-inset-bottom))] backdrop-blur-[24px] dial:hidden"
      >
        <div className="flex w-full max-w-home justify-around">
          {NAV.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cx(
                  'flex min-h-tap min-w-tap flex-col items-center gap-1 rounded-row px-2.5 py-1 text-[11px] leading-none transition-colors',
                  isActive ? 'font-semibold text-ember-soft' : 'font-medium text-fog hover:text-mist',
                )
              }
            >
              {icon}
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
