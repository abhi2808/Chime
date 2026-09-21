import { Navigate } from 'react-router-dom'

import { Orb } from '../components/Orb'
import { useMe } from '../lib/queries'

export function Login() {
  const { data, isPending } = useMe()

  if (isPending) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <p className="text-caption text-fog" role="status">
          Loading…
        </p>
      </div>
    )
  }

  if (data) return <Navigate to="/" replace />

  return (
    <main className="px-screen mx-auto flex min-h-dvh max-w-content flex-col items-center justify-center gap-10 py-12">
      <Orb size={132} intensity={0.55} className="rise" />

      <div className="flex flex-col items-center gap-3 text-center">
        <h1 className="text-display">Chime</h1>
        <p className="text-body max-w-[34ch] text-fog">
          One tap turns how your body and mood feel into a playlist that fits.
        </p>
      </div>

      {/* A plain link, not fetch: the OAuth handshake needs a full page navigation so
          the state cookie is set on this origin and survives the redirect back. */}
      <a
        href="/auth/spotify/login"
        className="text-body flex min-h-tap items-center justify-center rounded-full bg-mist px-6 font-semibold text-midnight transition-opacity hover:opacity-90"
      >
        Continue with Spotify
      </a>

      <p className="text-caption max-w-[40ch] text-center text-fog">
        Chime reads your liked songs and controls playback. It never posts anything to your
        account.
      </p>
    </main>
  )
}
