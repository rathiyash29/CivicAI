import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/**
 * Shown when a valid session exists but the account is not an officer. The
 * citizen token has already been discarded, so the dashboard stays unreachable.
 */
export function AccessDeniedPage() {
  const { user, logout } = useAuth()

  return (
    <div className="login-screen">
      <div className="login-panel">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <div>
            <strong>CivicAI</strong>
            <small>Government Officer Portal</small>
          </div>
        </div>

        <span className="state-glyph danger" aria-hidden="true">
          ⛔
        </span>

        <h1>Access denied</h1>
        <p className="muted">
          This dashboard is limited to government officers. The account
          {user ? <strong> {user.email}</strong> : ''} is signed in with the
          <code> {user?.role ?? 'citizen'} </code> role and cannot open the
          dashboard.
        </p>

        <div className="form">
          <button type="button" className="btn primary block" onClick={logout}>
            Sign out
          </button>
          <Link to="/login" className="btn ghost block">
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  )
}
