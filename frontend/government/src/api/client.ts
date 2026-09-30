/**
 * Shared HTTP plumbing for the CivicAI backend.
 *
 * The dashboard talks to the SAME FastAPI service the citizen frontend uses and
 * reuses its existing authentication contract verbatim -- there is no separate
 * government auth endpoint.
 *
 * Base URL and path prefix are both environment driven, so the same build works
 * in development and in production without editing source:
 *
 *  - `VITE_API_BASE_URL`
 *      Origin of the CivicAI service.
 *      Unset -> relative, same-origin URLs (correct when the app is served by
 *      the same host as the API, and what the dev server provides).
 *      Production, e.g. `https://api.civicai.example`.
 *
 *  - `VITE_API_PATH_PREFIX`
 *      Optional path prefix inserted before every route, e.g. `/api` when the
 *      service sits behind a gateway that mounts it there. Leave unset to call
 *      the backend's real paths (`/auth/login`, `/complaints`, ...).
 *
 * Why the prefix defaults to `/api` in development and to nothing in production:
 * the Vite dev server proxies `/api/*` and strips the prefix before forwarding
 * (see vite.config.ts), so dev needs the prefix while the FastAPI service does
 * not serve it. Defaulting per build mode means production calls the backend's
 * real paths with no configuration, and the local/prod mismatch that a
 * hardcoded `/api` would cause cannot happen.
 *
 * No secrets live here. Only browser-visible configuration.
 */
const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const BASE = RAW_BASE.replace(/\/+$/, '')

/** Explicit override wins; otherwise dev prefixes, production calls paths directly. */
const DEFAULT_PREFIX = import.meta.env.DEV ? '/api' : ''
const RAW_PREFIX = import.meta.env.VITE_API_PATH_PREFIX ?? DEFAULT_PREFIX
const PREFIX = RAW_PREFIX.replace(/\/+$/, '')

export const API_BASE = `${BASE}${PREFIX}`

/** The path the JWT is stored under, shared with frontend/citizen. */
const TOKEN_STORAGE_KEY = 'auth_token'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
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
      'Could not reach the CivicAI platform. Please check your connection and try again.',
      0,
    )
  }

  if (!response.ok) {
    const fallback =
      response.status === 401
        ? 'Your session is not valid. Please sign in again.'
        : `The request could not be completed (status ${response.status}).`
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
