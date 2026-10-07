import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { ApiError, api } from './api'
import type {
  ActiveSession,
  BodyState,
  ChimeInRequest,
  ChimeOutRequest,
  Intent,
  LibrarySyncStatus,
  Me,
  MoodId,
  RankPreview,
  RestoredPlaylist,
  Session,
  SessionFilters,
  SessionListPage,
  SessionType,
  SyncStartResponse,
  Transport,
  WeekSummary,
} from './types'

export const keys = {
  me: ['me'] as const,
  librarySyncStatus: ['library', 'status'] as const,
  bodyState: ['body-state'] as const,
  rankPreview: (options: RankOptions) => ['dev', 'rank', options] as const,
  activeSession: ['sessions', 'active'] as const,
  session: (id: number) => ['sessions', id] as const,
  sessionList: (filters: SessionFilters) => ['sessions', 'list', filters] as const,
  week: ['sessions', 'week'] as const,
}

/** 401 is a normal answer here (nobody is signed in), so it must not be retried. */
export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api.get<Me>('/api/me'),
    retry: (_failureCount, error) => !(error instanceof ApiError && error.status === 401),
    staleTime: 60_000,
  })
}

const ACTIVE_STATES = new Set(['running', 'interrupted'])

export function useLibrarySyncStatus(enabled = true) {
  return useQuery({
    queryKey: keys.librarySyncStatus,
    queryFn: () => api.get<LibrarySyncStatus>('/api/library/status'),
    enabled,
    // Poll only while there is something to watch; the backend caps out at
    // 100 WHOOP/Spotify requests a minute and this page should stay cheap.
    refetchInterval: (query) => (ACTIVE_STATES.has(query.state.data?.state ?? '') ? 1500 : false),
  })
}

export function useStartLibrarySync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (options?: { full?: boolean }) =>
      api.post<SyncStartResponse>(`/api/library/sync${options?.full ? '?full=true' : ''}`),
    onSuccess: (status) => {
      queryClient.setQueryData(keys.librarySyncStatus, status)
    },
  })
}

/**
 * Today's body state. The backend serves a cached WHOOP day for ten minutes and answers
 * 200 even when WHOOP is missing or broken, so there is no error state to handle here:
 * the gap is described in `note`.
 */
export function useBodyState(enabled = true) {
  return useQuery({
    queryKey: keys.bodyState,
    queryFn: () => api.get<BodyState>('/api/body-state'),
    enabled,
    // Matches BODY_STATE_TTL_SECONDS, so a remount inside the window costs nothing.
    staleTime: 600_000,
  })
}

/** Ask WHOOP now instead of waiting for the cache to expire. */
export function useRefreshBodyState() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.get<BodyState>('/api/body-state?refresh=true'),
    onSuccess: (state) => {
      queryClient.setQueryData(keys.bodyState, state)
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/auth/logout'),
    onSuccess: () => queryClient.clear(),
  })
}

export interface RankOptions {
  type: SessionType['id']
  mood: MoodId | null
  intent: Intent
  count: number
}

/**
 * What Chime in would queue right now, and why. A development view: it ranks without
 * creating a session, touching a playlist or starting playback.
 *
 * Not cached for long — the point of the screen is to change an input and look again.
 */
export function useRankPreview(options: RankOptions) {
  const query = new URLSearchParams({
    type: options.type,
    intent: options.intent,
    count: String(options.count),
  })
  if (options.mood) query.set('mood', options.mood)

  return useQuery({
    queryKey: keys.rankPreview(options),
    queryFn: () => api.get<RankPreview>(`/api/dev/rank?${query}`),
    staleTime: 10_000,
  })
}

// --- Sessions ----------------------------------------------------------------------

const LIVE_STATES = new Set(['created', 'active'])

/**
 * The live session and what Spotify says is playing.
 *
 * Polled while something is live so the ring timer and the mini player stay honest about
 * a track that was changed from another device, and left alone otherwise. Each poll costs
 * one `GET /me/player`, so 5s keeps a long session well inside the rate limit.
 */
export function useActiveSession(enabled = true) {
  return useQuery({
    queryKey: keys.activeSession,
    queryFn: () => api.get<ActiveSession>('/api/sessions/active'),
    enabled,
    refetchInterval: (query) =>
      LIVE_STATES.has(query.state.data?.session?.status ?? '') ? 5000 : false,
  })
}

/** One session by id, for the summary after Chime out and for history. */
export function useSession(id: number | null) {
  return useQuery({
    queryKey: keys.session(id ?? 0),
    queryFn: () => api.get<Session>(`/api/sessions/${id}`),
    enabled: id !== null,
  })
}

/**
 * Chime in. Resolves to the session that is now playing, or throws an `ApiError` whose
 * `code` the sheet turns into something to do about it — NO_ACTIVE_DEVICE, PREMIUM_REQUIRED,
 * NO_TRACKS, SESSION_ACTIVE.
 */
export function useChimeIn() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: ChimeInRequest) => api.post<Session>('/api/sessions', request),
    onSuccess: (session) => {
      queryClient.setQueryData(keys.session(session.id), session)
      // Seed the active query so the session screen paints before its first poll. The
      // playback read comes with that poll; the device we just started on is on `session`.
      queryClient.setQueryData<ActiveSession>(keys.activeSession, {
        session,
        playing: null,
        note: null,
      })
    },
  })
}

/**
 * Try again to play a session that is built but waiting, after opening Spotify.
 *
 * Throws an `ApiError` with the same codes as Chime in when Spotify still refuses, so the
 * screen can say what is in the way now rather than repeating the original reason.
 */
export function useStartPlayback(sessionId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<Session>(`/api/sessions/${sessionId}/start`),
    onSuccess: (session) => cacheSession(queryClient, session),
  })
}

/** A mood re-check mid-session. Recorded as an event; it does not rewrite `mood_in`. */
export function useMoodCheck(sessionId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (mood: MoodId) =>
      api.post<Session>(`/api/sessions/${sessionId}/mood`, { mood }),
    onSuccess: (session) => cacheSession(queryClient, session),
  })
}

export function useChimeOut(sessionId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: ChimeOutRequest) =>
      api.post<Session>(`/api/sessions/${sessionId}/end`, request),
    onSuccess: (session) => {
      queryClient.setQueryData(keys.session(session.id), session)
      // Nothing is live now, which also stops the poll.
      queryClient.setQueryData<ActiveSession>(keys.activeSession, {
        session: null,
        playing: null,
        note: null,
      })
      // There is a new record in History, and the week has one more session in it.
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'list'] })
      void queryClient.invalidateQueries({ queryKey: keys.week })
    },
  })
}

/**
 * Skip, go back, pause, resume. The endpoints answer 204 as soon as Spotify accepts the
 * command, but the player takes a moment to report the new track, so the refetch waits
 * rather than reading back the state we are trying to leave.
 */
export function useTransport(sessionId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (action: Transport) => api.post<void>(`/api/sessions/${sessionId}/${action}`),
    onSuccess: async () => {
      await new Promise((resolve) => setTimeout(resolve, 400))
      await queryClient.invalidateQueries({ queryKey: keys.activeSession })
    },
  })
}

// --- History -----------------------------------------------------------------------

const PAGE = 20

function listQuery(filters: SessionFilters, offset: number, limit: number): string {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (filters.type) query.set('type', filters.type)
  if (filters.mood_in) query.set('mood_in', filters.mood_in)
  if (filters.kept !== undefined) query.set('kept', String(filters.kept))
  if (filters.from) query.set('from', filters.from)
  if (filters.to) query.set('to', filters.to)
  return query.toString()
}

/**
 * Every session, newest first, a page at a time.
 *
 * Paged rather than fetched whole: a year of daily sessions is a few hundred cards, and the
 * screen only ever shows the top of the list.
 */
export function useSessionList(filters: SessionFilters = {}, limit = PAGE) {
  return useInfiniteQuery({
    queryKey: [...keys.sessionList(filters), limit],
    queryFn: ({ pageParam }) =>
      api.get<SessionListPage>(`/api/sessions?${listQuery(filters, pageParam, limit)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const seen = lastPage.offset + lastPage.sessions.length
      return seen < lastPage.total ? seen : undefined
    },
  })
}

/** The line above the list: sessions, minutes and the commonest mood shift this week. */
export function useWeekSummary() {
  return useQuery({
    queryKey: keys.week,
    queryFn: () => api.get<WeekSummary>('/api/sessions/week'),
    staleTime: 60_000,
  })
}

/**
 * Bring a session back as a playlist, rebuilt from the tracks we stored.
 *
 * Invalidates the session so the detail page picks up the `restore` event and can link to
 * the new playlist after a reload as well as right now.
 */
export function useRestoreSession(sessionId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<RestoredPlaylist>(`/api/sessions/${sessionId}/restore`),
    onSuccess: () => {
      if (sessionId !== null) {
        void queryClient.invalidateQueries({ queryKey: keys.session(sessionId) })
      }
    },
  })
}

/** Forget a session. Spotify is untouched: a kept playlist is the user's now. */
export function useDeleteSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: number) => api.del<void>(`/api/sessions/${sessionId}`),
    onSuccess: (_result, sessionId) => {
      queryClient.removeQueries({ queryKey: keys.session(sessionId) })
      // Every list and the week summary counted it, so both are wrong now. Named rather
      // than invalidating all of `['sessions']`, which would also refetch the live poll and
      // spend a `GET /me/player` on a screen that is not showing it.
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'list'] })
      void queryClient.invalidateQueries({ queryKey: keys.week })
    },
  })
}

function cacheSession(queryClient: ReturnType<typeof useQueryClient>, session: Session): void {
  queryClient.setQueryData(keys.session(session.id), session)
  queryClient.setQueryData<ActiveSession>(keys.activeSession, (previous) =>
    previous ? { ...previous, session } : { session, playing: null, note: null },
  )
}
