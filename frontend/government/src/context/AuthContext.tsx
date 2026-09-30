import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { getAuthToken, clearAuthToken, saveAuthToken } from '../api/client'
import { getCurrentUser, loginUser as loginRequest, type User } from '../api/auth'

/**
 * Which screen the app should be showing.
 * - `unauthenticated`: no usable token, go to the login page
 * - `officer`:        token is valid and the role is officer, dashboard allowed
 * - `forbidden`:       token is valid but the role is not officer
 * - `loading`:        still resolving the stored token
 */
export type AuthStatus = 'loading' | 'unauthenticated' | 'officer' | 'forbidden'

interface AuthContextValue {
  user: User | null
  status: AuthStatus
  isOfficer: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

function statusForUser(user: User | null): AuthStatus {
  if (!user) return 'unauthenticated'
  return (user.role ?? '').trim().toLowerCase() === 'officer' ? 'officer' : 'forbidden'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')

  // Resolve any token left in localStorage on first mount, exactly like the
  // citizen frontend does, so a refresh does not bounce the officer to login.
  useEffect(() => {
    let cancelled = false

    async function restore() {
      const token = getAuthToken()
      if (!token) {
        if (!cancelled) setStatus('unauthenticated')
        return
      }
      try {
        const current = await getCurrentUser(token)
        if (cancelled) return
        setUser(current)
        setStatus(statusForUser(current))
      } catch {
        // Expired token, or the backend's in-memory account store was cleared by
        // a restart. Either way the token is no longer usable.
        if (cancelled) return
        clearAuthToken()
        setUser(null)
        setStatus('unauthenticated')
      }
    }

    restore()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await loginRequest({ email, password })
    saveAuthToken(tokens.access_token)

    try {
      // Confirm the identity and, critically, the role. The login response
      // itself carries no user data.
      const current = await getCurrentUser(tokens.access_token)
      setUser(current)
      setStatus(statusForUser(current))
      if ((current.role ?? '').trim().toLowerCase() !== 'officer') {
        // A citizen token has no business in this app; do not keep it around.
        clearAuthToken()
        setUser(null)
      }
    } catch (error) {
      clearAuthToken()
      setUser(null)
      setStatus('unauthenticated')
      throw error
    }
  }, [])

  const logout = useCallback(() => {
    clearAuthToken()
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, isOfficer: status === 'officer', login, logout }),
    [user, status, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
