/**
 * The officer decision controls for one recommendation.
 *
 * Every button here performs a real, persisted call. Nothing is optimistic and
 * nothing is local: a decision shows as saved only after the backend has
 * returned 200 and the decision history has been re-read, so a refresh always
 * agrees with what is on screen. A conflict (409, e.g. approving something that
 * already has a project) shows the server's own message.
 */
import { useCallback, useEffect, useState } from 'react'
import { getAuthToken } from '../api/client'
import {
  approveRecommendation,
  listDecisions,
  modifyRecommendation,
  rejectRecommendation,
  type Decision,
} from '../api/projects'

type Mode = 'idle' | 'confirm-approve' | 'modify' | 'reject' | 'busy'

interface Props {
  recommendationId: number
  onDecided: () => void
}

export function DecisionControls({ recommendationId, onDecided }: Props) {
  const [mode, setMode] = useState<Mode>('idle')
  const [decisions, setDecisions] = useState<Decision[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  // Modify form state.
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [reason, setReason] = useState('')

  /**
   * The id has to be a positive integer or the decision cannot be recorded.
   *
   * The backend declares this path parameter as an `int`, so anything else --
   * `undefined` above all -- is rejected with 422 before the decision service
   * is ever reached. Rendering the buttons anyway would offer an officer an
   * action that is guaranteed to fail; sending the request would produce a
   * validation error with no actionable context. Both are worse than saying the
   * id is unusable, so this is checked once here rather than at each call site.
   */
  const idIsUsable = Number.isInteger(recommendationId) && recommendationId > 0

  const loadDecisions = useCallback(async () => {
    const token = getAuthToken()
    // Nothing to look up without a usable id, and asking anyway would put a
    // guaranteed 422 in front of the officer.
    if (!token || !idIsUsable) return
    try {
      setDecisions(await listDecisions(token, recommendationId))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load decisions')
    }
  }, [recommendationId, idIsUsable])

  useEffect(() => {
    loadDecisions()
  }, [loadDecisions])

  const latest = decisions && decisions.length > 0 ? decisions[decisions.length - 1] : null
  const hasProject = Boolean(latest && latest.project_id !== null)
  const isRejected = latest?.decision === 'Rejected'

  if (!idIsUsable) {
    return (
      <div className="decision-panel">
        <h4 className="detail-subhead">Officer decision</h4>
        <p className="form-error" role="alert">
          This recommendation cannot be actioned right now because its record is
          missing a unique reference. Please contact the system administrator
          before recording a decision.
        </p>
      </div>
    )
  }

  function reset() {
    setMode('idle')
    setError(null)
    setTitle('')
    setDescription('')
    setReason('')
  }

  /** Run a decision, then re-read the history so the screen matches the database. */
  async function run(action: () => Promise<{ label: string }>) {
    setError(null)
    setSaved(null)
    setMode('busy')
    const token = getAuthToken()
    if (!token) {
      setError('No active session. Please sign in again.')
      setMode('idle')
      return
    }
    try {
      const { label } = await action()
      await loadDecisions()
      setSaved(label)
      reset()
      setMode('idle')
      onDecided()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The decision failed')
      setMode('idle')
    }
  }

  const busy = mode === 'busy'

  if (isRejected) {
    return (
      <div className="decision-panel rejected">
        <h4 className="detail-subhead">Decision</h4>
        <p className="decision-outcome">
          <span className="chip chip-rejected">Rejected</span>
          {latest?.reason ? <span className="decision-reason"> “{latest.reason}”</span> : null}
        </p>
        <p className="muted small">
          Rejected by {latest?.officer?.name ?? latest?.officer?.email ?? 'an officer'}. No
          project was created. A rejection is part of the record and is not undone from
          here.
        </p>
      </div>
    )
  }

  return (
    <div className="decision-panel">
      <h4 className="detail-subhead">Officer decision</h4>

      {decisions && decisions.length > 0 ? (
        <div className="decision-history">
          {decisions.map((entry) => (
            <div key={entry.id} className="decision-entry">
              <span className={`chip chip-${entry.decision.toLowerCase().replace(' ', '-')}`}>
                {entry.decision}
              </span>
              <span className="muted small">
                {entry.officer?.name ?? entry.officer?.email ?? 'Officer'}
                {entry.created_at ? ` · ${new Date(entry.created_at).toLocaleString()}` : ''}
              </span>
              {entry.reason ? <p className="decision-reason">{entry.reason}</p> : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted small">No decision recorded yet.</p>
      )}

      {saved ? (
        <p className="decision-success" role="status">
          {saved} — saved to the database.
        </p>
      ) : null}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      {mode === 'confirm-approve' ? (
        <div className="decision-confirm">
          <p>
            Approve this recommendation as proposed and create a project? The
            recommendation itself is not modified.
          </p>
          <div className="decision-row">
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await approveRecommendation(getAuthToken() ?? '', recommendationId)
                  return { label: 'Recommendation approved' }
                })
              }
            >
              {busy ? 'Saving…' : 'Confirm approval'}
            </button>
            <button type="button" className="btn ghost" onClick={reset} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {mode === 'modify' ? (
        <div className="decision-form">
          <label htmlFor={`modify-title-${recommendationId}`}>Modified action / title</label>
          <input
            id={`modify-title-${recommendationId}`}
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="What should be done, in your words"
          />

          <label htmlFor={`modify-desc-${recommendationId}`}>Description (optional)</label>
          <textarea
            id={`modify-desc-${recommendationId}`}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            placeholder="Scope, phasing, constraints"
          />

          <label htmlFor={`modify-reason-${recommendationId}`}>Reason (optional)</label>
          <input
            id={`modify-reason-${recommendationId}`}
            type="text"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Why the plan was changed"
          />

          <div className="decision-row">
            <button
              type="button"
              className="btn primary"
              disabled={busy || title.trim() === ''}
              onClick={() =>
                run(async () => {
                  await modifyRecommendation(getAuthToken() ?? '', recommendationId, {
                    title: title.trim(),
                    description: description.trim() || undefined,
                    reason: reason.trim() || undefined,
                  })
                  return { label: 'Modification saved' }
                })
              }
            >
              {busy ? 'Saving…' : 'Save modification'}
            </button>
            <button type="button" className="btn ghost" onClick={reset} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {mode === 'reject' ? (
        <div className="decision-form">
          <label htmlFor={`reject-reason-${recommendationId}`}>
            Rejection reason (required)
          </label>
          <textarea
            id={`reject-reason-${recommendationId}`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            placeholder="Why this recommendation is not being taken forward"
          />
          <div className="decision-row">
            <button
              type="button"
              className="btn danger"
              disabled={busy || reason.trim() === ''}
              onClick={() =>
                run(async () => {
                  await rejectRecommendation(
                    getAuthToken() ?? '',
                    recommendationId,
                    reason.trim(),
                  )
                  return { label: 'Recommendation rejected' }
                })
              }
            >
              {busy ? 'Saving…' : 'Confirm rejection'}
            </button>
            <button type="button" className="btn ghost" onClick={reset} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {mode === 'idle' ? (
        <div className="decision-row">
          <button
            type="button"
            className="btn primary"
            disabled={busy || hasProject}
            title={
              hasProject
                ? 'This recommendation already has a project. Modify it or update its status from the Projects page.'
                : undefined
            }
            onClick={() => setMode('confirm-approve')}
          >
            Approve
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => {
              setTitle(latest?.action_snapshot ?? '')
              setMode('modify')
            }}
          >
            Modify
          </button>
          <button
            type="button"
            className="btn danger"
            disabled={busy || hasProject}
            title={hasProject ? 'A recommendation with a project cannot be rejected.' : undefined}
            onClick={() => setMode('reject')}
          >
            Reject
          </button>
        </div>
      ) : null}

      {hasProject && mode === 'idle' ? (
        <p className="muted small decision-note">
          This recommendation already has an associated development project.
          Approving it again is not permitted; use Modify to revise the plan, or
          advance the project from the Projects page.
        </p>
      ) : null}
    </div>
  )
}
