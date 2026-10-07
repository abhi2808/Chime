/** Thin fetch wrapper. Vite proxies /api and /auth to the backend, so everything is
 *  same-origin and the session cookie rides along without CORS. */

export class ApiError extends Error {
  readonly status: number
  /**
   * The backend's machine-readable reason, when it sent one: NO_ACTIVE_DEVICE,
   * PREMIUM_REQUIRED, SESSION_ACTIVE, NO_TRACKS. Screens branch on this, never on the
   * message, which is written to be shown rather than matched.
   */
  readonly code: string | null
  /** Set when the failure points at a session, e.g. one already running. */
  readonly sessionId: number | null

  constructor(
    status: number,
    message: string,
    options: { code?: string | null; sessionId?: number | null } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = options.code ?? null
    this.sessionId = options.sessionId ?? null
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, 'Could not reach Chime. Check that the backend is running on port 8000.')
  }

  if (!response.ok) {
    throw await readError(response)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

interface ErrorDetail {
  message?: unknown
  code?: unknown
  session_id?: unknown
}

/**
 * FastAPI puts the human-readable message in `detail`. Ours is sometimes an object,
 * because "Spotify isn't open on any device" needs a code the UI can act on as well as a
 * sentence it can show.
 */
async function readError(response: Response): Promise<ApiError> {
  const fallback = `Request failed (${response.status}).`
  let detail: unknown
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail
  } catch {
    return new ApiError(response.status, fallback)
  }

  if (typeof detail === 'string') {
    return new ApiError(response.status, detail)
  }
  if (detail && typeof detail === 'object') {
    const { message, code, session_id: sessionId } = detail as ErrorDetail
    return new ApiError(response.status, typeof message === 'string' ? message : fallback, {
      code: typeof code === 'string' ? code : null,
      sessionId: typeof sessionId === 'number' ? sessionId : null,
    })
  }
  return new ApiError(response.status, fallback)
}

function withBody(body: unknown): RequestInit {
  if (body === undefined) return { method: 'POST' }
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, withBody(body)),
  /** `delete` is a reserved word as a bare function name, so the method is `del`. */
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
