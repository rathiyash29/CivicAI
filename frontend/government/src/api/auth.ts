/**
 * Authentication, against the existing CivicAI contract:
 *   POST /auth/login  -> { access_token, token_type }
 *   GET  /auth/me     -> the current user, including `role`
 *
 * Field names are the backend's, unchanged. No government-specific auth
 * endpoint is introduced.
 */
import { apiRequest } from './client'

export type UserRole = 'citizen' | 'officer'

export interface User {
  id: number
  full_name: string
  email: string
  role: UserRole
  created_at: string
}

export interface AuthTokens {
  access_token: string
  token_type: string
}

export interface LoginRequest {
  email: string
  password: string
}

export function loginUser(data: LoginRequest): Promise<AuthTokens> {
  return apiRequest<AuthTokens>('/auth/login', { method: 'POST', body: data })
}

export function getCurrentUser(token: string): Promise<User> {
  return apiRequest<User>('/auth/me', { token })
}

export function isOfficer(user: Pick<User, 'role'> | null): boolean {
  return (user?.role ?? '').trim().toLowerCase() === 'officer'
}
