import { History, House, Settings } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { cx } from '../lib/cx'
import { useActiveSession } from '../lib/queries'
import { MiniPlayer } from './MiniPlayer'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

// Insights stays out of the nav until the screen exists.
const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: House },
  { to: '/history', label: 'History', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings },
]

/** Bottom tab bar on mobile, left rail from 1024 px. Content is capped at 720 and
 *  centered in whatever space the rail leaves. */
export function AppShell() {
  const { data: active } = useActiveSession()

  return (
    <div className="min-h-dvh lg:pl-56">
      <nav
        aria-label="Sections"
        className="glass fixed top-0 bottom-0 left-0 z-40 hidden w-56 flex-col gap-1 border-y-0 border-l-0 p-4 lg:flex"
      >
        <span className="text-headline px-3 pt-2 pb-6">Chime</span>
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cx(
                'text-body flex min-h-tap items-center gap-3 rounded-row px-3 transition-colors',
                isActive ? 'bg-white/8 text-mist' : 'text-fog hover:text-mist',
              )
            }
          >
            <Icon aria-hidden="true" size={20} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* The mini player sits over the content, so a live session buys extra clearance. */}
      <main
        className={cx(
          'mx-auto w-full max-w-content px-screen pt-8 lg:pt-12',
          active?.session ? 'pb-44 lg:pb-28' : 'pb-28 lg:pb-12',
        )}
      >
        <Outlet />
      </main>

      <MiniPlayer />

      <nav
        aria-label="Sections"
        className="glass fixed inset-x-0 bottom-0 z-40 flex justify-around rounded-t-tile border-x-0 border-b-0 pb-[env(safe-area-inset-bottom)] lg:hidden"
      >
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cx(
                'text-caption flex min-h-tap flex-1 flex-col items-center justify-center gap-1 py-2 transition-colors',
                isActive ? 'text-mist' : 'text-fog hover:text-mist',
              )
            }
          >
            <Icon aria-hidden="true" size={20} />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
