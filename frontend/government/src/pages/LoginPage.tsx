import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/**
 * Officer sign-in. Uses the shared POST /auth/login contract; there is no
 * separate government login endpoint.
 */
export function LoginPage() {
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'

  if (status === 'officer') {
    return <Navigate to={from} replace />
  }
  if (status === 'forbidden') {
    return <Navigate to="/access-denied" replace />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email.trim(), password)
      navigate(from, { replace: true })
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Sign-in failed. Please try again.',
      )
      setSubmitting(false)
    }
  }

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

        <h1>Officer sign in</h1>
        <p className="muted">
          Access is restricted to accounts with the <code>officer</code> role.
        </p>

        <form onSubmit={handleSubmit} className="form">
          <label htmlFor="email">Official email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
            placeholder="officer@mc.gov.in"
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            placeholder="••••••••"
          />

          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn primary block" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="muted small">
          Credentials come from the same CivicAI accounts used by the citizen portal.
        </p>
      </div>
    </div>
  )
}
