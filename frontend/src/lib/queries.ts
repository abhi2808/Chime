import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from './api'
import type { BodyState, LibrarySyncStatus, Me, SyncStartResponse } from './types'

export const keys = {
  me: ['me'] as const,
  librarySyncStatus: ['library', 'status'] as const,
  bodyState: ['body-state'] as const,
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
