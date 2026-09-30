/**
 * Shared HTTP plumbing for the CivicAI backend.
 *
 * The citizen app talks to the same FastAPI service the government dashboard
 * uses, reusing its existing authentication contract verbatim.
 *
 * Base URL resolution:
 *  - local dev:  `VITE_API_BASE_URL` unset -> relative URLs, which the Vite
 *    dev server serves from the same origin as the app, so no CORS change is
 *    needed on the backend.
 *  - deployed:   `VITE_API_BASE_URL` set to the origin the built app is served
 *    from, e.g. `https://api.civicai.example`.
 *
 * No secrets live here. Only the browser-visible base URL, which is never a
 * credential.
 */
/**
 * Optional-chained: `import.meta.env` only exists under a bundler, and this
 * module is also imported directly by a Node check script. Under Vite the
 * behaviour is unchanged.
 */
const RAW_BASE = import.meta.env?.VITE_API_BASE_URL ?? ''
const BASE = RAW_BASE.replace(/\/+$/, '')

/**
 * The API base the app calls. Empty in local development, which means the
 * browser talks to the same origin the page was loaded from.
 */
export const API_BASE = BASE

/** The path the JWT is stored under, shared with frontend/government. */
export const TOKEN_STORAGE_KEY = 'auth_token'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Shown when the CivicAI service could not be reached at all. */
export const NETWORK_ERROR_MESSAGE =
  'Unable to connect to CivicAI. Please try again.'

/**
 * Markers of an internal failure that must never be rendered to a citizen.
 *
 * A raw driver or traceback string is not an explanation, it is a leak: it can
 * carry SQL, file paths, connection strings or a token. When one of these
 * appears the caller gets the generic fallback instead.
 */
const INTERNAL_MARKERS = [
  'traceback',
  'sqlalchemy',
  'psycopg2',
  'sqlstate',
  'stack trace',
  'exception',
  'at line',
  'select ',
  'insert ',
  'update ',
  'password',
  'token',
  'secret',
  '/usr/',
  'site-packages',
]

function looksInternal(text: string): boolean {
  const lower = text.toLowerCase()
  return INTERNAL_MARKERS.some((marker) => lower.includes(marker))
}

/**
 * Pull a readable sentence out of the error shapes this API actually produces.
 *
 * The important case is a FastAPI 422, where `detail` is an ARRAY of objects
 * like `{msg, loc, input, type}`. Coercing that with `String(error)` yields
 * "[object Object]", which is the bug this replaces. Only the `msg` of each
 * entry is used, never `input` -- `input` echoes back what the user submitted,
 * including a password.
 *
 * Returns an empty string when nothing readable can be found, so the caller can
 * substitute its own fallback.
 */
function extractMessage(value: unknown, depth = 0): string {
  // A malformed payload must not send us into infinite recursion.
  if (value === null || value === undefined || depth > 5) return ''

  if (typeof value === 'string') return value.trim()

  if (Array.isArray(value)) {
    const parts = value
      .map((entry) => extractMessage(entry, depth + 1))
      .filter((part) => part.length > 0)
    // De-duplicate while preserving order: a 422 often repeats one cause.
    return [...new Set(parts)].join(' ')
  }

  if (typeof value !== 'object') return ''

  const record = value as Record<string, unknown>

  // A validation entry: prefer its human-readable message.
  if (typeof record.msg === 'string') return record.msg.trim()

  // FastAPI and several frameworks put the payload under `detail`; some use
  // `message`, and `error` covers the odd gateway shape.
  for (const key of ['detail', 'message', 'error']) {
    if (record[key] !== undefined) {
      const nested = extractMessage(record[key], depth + 1)
      if (nested) return nested
    }
  }

  return ''
}

/**
 * Normalise anything thrown by a fetch or an API call into one safe sentence.
 *
 * Ordered so the most specific, most useful message wins, and so that an
 * unreachable service is never reported as a validation problem.
 */
export function normalizeErrorMessage(error: unknown, fallback: string): string {
  // A browser-level network failure: no response was ever received.
  if (
    error instanceof TypeError ||
    (error instanceof Error && /failed to fetch|networkerror|load failed/i.test(error.message))
  ) {
    return NETWORK_ERROR_MESSAGE
  }

  const message =
    error instanceof Error
      ? extractMessage(error.message) || error.message
      : extractMessage(error)

  if (!message) return fallback

  const cleaned = message.replace(/\s+/g, ' ').trim()
  if (!cleaned || cleaned === '[object Object]') return fallback
  if (looksInternal(cleaned)) return fallback

  // Backend wording -> citizen wording. The rest of the sentence is preserved.
  if (/email already registered|already exists|duplicate/i.test(cleaned)) {
    return 'An account with this email already exists.'
  }

  return cleaned.length > 240 ? `${cleaned.slice(0, 237)}...` : cleaned
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (body && typeof body.detail === 'string' && body.detail) return body.detail
  } catch {
    // Non-JSON error body (proxy failure, HTML error page, empty response).
  }
  return fallback
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH'
  body?: unknown
  token?: string | null
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, token } = options

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(
      'Could not reach the CivicAI backend. Check that the API is running and reachable.',
      0,
    )
  }

  if (!response.ok) {
    const fallback =
      response.status === 401
        ? 'Your session is not valid. Please sign in again.'
        : `Request failed with status ${response.status}.`
    throw new ApiError(await readErrorDetail(response, fallback), response.status)
  }

  return (await response.json()) as T
}

export function saveAuthToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}