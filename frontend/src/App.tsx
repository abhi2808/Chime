import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { AuthGuard } from './components/AuthGuard'
import { DevRank } from './routes/DevRank'
import { Home } from './routes/Home'
import { History } from './routes/History'
import { Insights } from './routes/Insights'
import { Library } from './routes/Library'
import { Login } from './routes/Login'
import { Session } from './routes/Session'
import { SessionDetail } from './routes/SessionDetail'
import { Settings } from './routes/Settings'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <AuthGuard>
            <AppShell />
          </AuthGuard>
        }
      >
        <Route path="/" element={<Home />} />
        {/* Not in the nav: the session is reached from the orb or the mini player. */}
        <Route path="/session" element={<Session />} />
        <Route path="/history" element={<History />} />
        <Route path="/history/:id" element={<SessionDetail />} />
        <Route path="/insights" element={<Insights />} />
        <Route path="/library" element={<Library />} />
        <Route path="/settings" element={<Settings />} />
        {/* Development view of the ranking. Deliberately not in the nav. */}
        <Route path="/dev/rank" element={<DevRank />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
