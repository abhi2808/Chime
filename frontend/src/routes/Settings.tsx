import type { ReactNode } from 'react'

import { useBodyState, useLogout, useMe } from '../lib/queries'

function Row({ label, value, action }: { label: string; value: string; action?: ReactNode }) {
  return (
    <div className="flex min-h-tap items-center justify-between gap-4 px-4 py-3">
      <span className="text-body">{label}</span>
      <div className="flex items-center gap-3">
        <span className="text-caption text-fog">{value}</span>
        {action}
      </div>
    </div>
  )
}

export function Settings() {
  const { data } = useMe()
  const { data: body } = useBodyState()
  const logout = useLogout()

  const whoopConnected = body ? body.connected && !body.needs_reconnect : data?.connections.whoop

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title">Settings</h1>

      <section className="flex flex-col gap-3">
        <h2 className="text-caption text-fog">Connections</h2>
        <div className="glass divide-y divide-hairline rounded-sheet">
          <Row label="Spotify" value={data?.display_name ? `Connected as ${data.display_name}` : 'Connected'} />
          <Row
            label="WHOOP"
            value={
              whoopConnected
                ? 'Connected'
                : body?.needs_reconnect
                  ? 'Needs reconnecting'
                  : 'Not connected'
            }
            action={
              // A full page navigation, so the handshake cookie is set on this origin.
              <a
                href="/auth/whoop/login"
                className="text-caption min-h-tap flex items-center rounded-full border border-hairline px-4 transition-colors hover:border-white/20"
              >
                {whoopConnected ? 'Reconnect' : 'Connect'}
              </a>
            }
          />
        </div>
        {body?.note && !whoopConnected ? <p className="text-caption text-fog">{body.note}</p> : null}
      </section>

      <p className="text-caption text-fog">
        Sources, explicit songs, what happens on chime out and deleting your data all arrive in a
        later phase.
      </p>

      <button
        type="button"
        onClick={() => {
          logout.mutate(undefined, {
            // A full reload is the simplest way to drop every cached query and land on /login.
            onSuccess: () => window.location.assign('/login'),
          })
        }}
        disabled={logout.isPending}
        className="glass text-body min-h-tap self-start rounded-full px-5 transition-colors hover:border-white/20 disabled:opacity-60"
      >
        {logout.isPending ? 'Signing out…' : 'Sign out'}
      </button>

      {logout.error ? (
        <p className="text-caption text-danger" role="alert">
          {logout.error.message}
        </p>
      ) : null}
    </div>
  )
}
