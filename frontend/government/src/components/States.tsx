import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="state">
      <span className="state-glyph" aria-hidden="true">
        ◌
      </span>
      <h3>{title}</h3>
      {hint ? <p className="muted">{hint}</p> : null}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: ApiError | Error | null
  onRetry?: () => void
}) {
  const message =
    error instanceof Error ? error.message : 'An unexpected error occurred.'
  const status = error instanceof ApiError ? error.status : null
  const isAuthIssue = status === 401

  return (
    <div className="state error" role="alert">
      <span className="state-glyph" aria-hidden="true">
        !
      </span>
      <h3>{isAuthIssue ? 'Session expired' : 'Could not load data'}</h3>
      <p>{message}</p>
      {status !== null ? <p className="muted small">HTTP status {status}</p> : null}
      {onRetry && !isAuthIssue ? (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      ) : null}
      {isAuthIssue ? (
        <p className="muted small">Sign in again to continue.</p>
      ) : null}
    </div>
  )
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="card">
      {title ? <h2 className="card-title">{title}</h2> : null}
      {children}
    </section>
  )
}
