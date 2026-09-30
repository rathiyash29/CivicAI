/**
 * Gate for every dashboard route.
 *
 * Loading      -> full-screen splash, no dashboard chrome flashes
 * no token     -> redirect to /login, remembering where the officer was going
 * citizen      -> /access-denied, never the dashboard
 * officer      -> render the route
 */
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="app-splash">
        <div className="spinner" aria-hidden="true" />
        <p>Verifying officer session…</p>
      </div>
    )
  }

  if (status === 'forbidden') {
    return <Navigate to="/access-denied" replace />
  }

  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
