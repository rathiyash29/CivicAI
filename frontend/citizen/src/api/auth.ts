/**
 * Authentication for the citizen frontend.
 *
 * `API_BASE` is resolved from `VITE_API_BASE_URL` (see `api/client.ts`), so the
 * backend origin is environment-configurable. In local development the Vite
 * dev server is same-origin and the value is empty, which means these calls
 * go to the page's own origin and no CORS configuration is needed on the
 * backend.
 */
import { API_BASE, TOKEN_STORAGE_KEY, normalizeErrorMessage } from './client'

export interface User {
  id: number;
  full_name: string;
  email: string;
  role: 'citizen' | 'officer';
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  token_type: string;
}

/**
 * Public registration payload.
 *
 * There is deliberately no `role` field. Officer accounts are provisioned out
 * of band, and the public route rejects any request that asks for one, so the
 * client cannot offer it in the first place.
 */
export interface RegisterRequest {
  full_name: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

/**
 * Read a failure response and turn it into one readable sentence.
 *
 * Always resolves to a string so a caller can never end up rendering
 * "[object Object]" from a structured 422 payload.
 */
async function readFailure(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    return normalizeErrorMessage(body, fallback)
  } catch {
    // Non-JSON error body (proxy failure, HTML page, empty response).
    return normalizeErrorMessage(null, fallback)
  }
}

export async function registerUser(data: RegisterRequest): Promise<User> {
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw new Error(await readFailure(response, 'Registration failed. Please try again.'));
  }

  return response.json();
}

export async function loginUser(data: LoginRequest): Promise<AuthTokens> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw new Error(await readFailure(response, 'Sign-in failed. Please try again.'));
  }

  return response.json();
}

export async function getCurrentUser(token: string): Promise<User> {
  const response = await fetch(`${API_BASE}/auth/me`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error('Failed to get user info');
  }

  return response.json();
}

export function saveAuthToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}