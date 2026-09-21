import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { ApiError } from '../lib/api'
import { useMe } from '../lib/queries'

/** Gate on GET /api/me. A 401 means "not signed in" and goes to /login; anything else
 *  is a real failure and says so rather than bouncing in a loop. */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { data, error, isPending } = useMe()
  const location = useLocation()

  if (isPending) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <p className="text-caption text-fog" role="status">
          Loading…
        </p>
      </div>
    )
  }

  if (error instanceof ApiError && error.status === 401) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  if (error || !data) {
    return (
      <div className="px-screen flex min-h-dvh items-center justify-center">
        <p className="text-body text-center text-fog" role="alert">
          {error instanceof Error ? error.message : 'Something went wrong.'}
        </p>
      </div>
    )
  }

  return children
}
