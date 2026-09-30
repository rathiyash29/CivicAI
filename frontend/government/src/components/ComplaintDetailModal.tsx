/**
 * Detail view for a single complaint.
 *
 * Three things the officer cannot get anywhere else, all read from data the
 * backend already stores:
 *
 *   * the AI analysis written on the complaint row at submission time;
 *   * the five weighted factors behind the stored priority score, with the
 *     engine's own weights, fetched on demand and never recomputed here;
 *   * the issue cluster this complaint was grouped into, as a link to the
 *     recommendations built from that cluster.
 *
 * A value the backend sends as null is rendered as an em dash. Nothing is
 * filled in client-side, and a priority factor that is unavailable is reported
 * as unavailable rather than being back-computed from the score.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getAuthToken } from '../api/client'
import {
  fetchPriorityExplanation,
  type Complaint,
  type PriorityExplanation,
} from '../api/complaints'
import { FactorTable, scoreHasDrifted } from './PriorityFactors'

const DASH = '—'

/** Render a value that the backend may legitimately send as null. */
function value(raw: string | number | null | undefined): string {
  if (raw === null || raw === undefined) return DASH
  const text = String(raw).trim()
  return text === '' ? DASH : text
}

/**
 * Does this complaint carry an AI analysis?
 *
 * Checked on the presence of any of the four analysis fields rather than a
 * single one, because a partial analysis is still real: showing what was
 * written is better than hiding the whole block behind one missing field.
 */
function hasAnalysis(complaint: Complaint): boolean {
  return [
    complaint.analysis_issue_summary,
    complaint.analysis_affected_group,
    complaint.analysis_urgency,
    complaint.analysis_recommended_action,
  ].some((field) => typeof field === 'string' && field.trim() !== '')
}

/**
 * `created_at` is written by the backend with `datetime.utcnow()`, so it has no
 * timezone suffix. `new Date(...)` would read that as local time and shift the
 * displayed date, so it is normalised to UTC first.
 */
export function formatDate(raw: string | null | undefined): string {
  if (!raw) return DASH
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const date = new Date(hasZone ? raw : `${raw}Z`)
  if (Number.isNaN(date.getTime())) return DASH
  return date.toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function ComplaintDetailModal({
  complaint,
  onClose,
}: {
  complaint: Complaint
  onClose: () => void
}) {
  const [explanation, setExplanation] = useState<PriorityExplanation | null>(null)
  const [explanationError, setExplanationError] = useState(false)
  const [loadingExplanation, setLoadingExplanation] = useState(false)

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [onClose])

  /**
   * Factors are fetched on demand, not eagerly on mount, because they are only
   * worth a request once the officer opens "Why this score?". The complaint's
   * own score renders immediately either way, so a slow or failing explanation
   * never blocks the detail view.
   */
  const loadExplanation = useCallback(async () => {
    const token = getAuthToken()
    if (!token || explanation || loadingExplanation) return
    setLoadingExplanation(true)
    setExplanationError(false)
    try {
      setExplanation(await fetchPriorityExplanation(token, complaint.complaint_id))
    } catch {
      // A missing explanation is reported in place. The score itself came from
      // the complaint row and stays valid regardless.
      setExplanationError(true)
    } finally {
      setLoadingExplanation(false)
    }
  }, [complaint.complaint_id, explanation, loadingExplanation])

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="complaint-detail-title"
      >
        <header className="modal-header">
          <div>
            <h2 id="complaint-detail-title">Complaint {complaint.complaint_id}</h2>
            <p className="muted small">Submitted {formatDate(complaint.created_at)}</p>
          </div>
          <button
            type="button"
            className="btn ghost"
            onClick={onClose}
            aria-label="Close details"
          >
            Close
          </button>
        </header>

        <div className="modal-body">
          <section className="detail-block">
            <h3>Complaint</h3>
            <dl className="detail-grid">
              <div>
                <dt>Complaint ID</dt>
                <dd className="mono">{value(complaint.complaint_id)}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{value(complaint.status)}</dd>
              </div>
              <div>
                <dt>Category</dt>
                <dd>{value(complaint.category)}</dd>
              </div>
              <div>
                <dt>Location</dt>
                <dd>{value(complaint.location)}</dd>
              </div>
              <div>
                <dt>Severity</dt>
                <dd>{value(complaint.severity)}</dd>
              </div>
              <div>
                <dt>Language</dt>
                <dd>{value(complaint.language)}</dd>
              </div>
              <div>
                <dt>Issue cluster</dt>
                <dd>
                  {complaint.cluster_id ? (
                    // The cluster is what the hotspot and the recommendation
                    // were built from. The case file is the whole chain for it;
                    // the recommendations link is the narrower view.
                    <span className="cluster-links">
                      <Link
                        className="link mono"
                        to={`/dashboard/case/${complaint.cluster_id}`}
                      >
                        Cluster #{complaint.cluster_id}
                      </Link>
                      <Link
                        className="link"
                        to={`/dashboard/recommendations?cluster=${complaint.cluster_id}`}
                      >
                        See its recommendation
                      </Link>
                    </span>
                  ) : (
                    <span className="muted small">
                      {DASH} — not yet clustered
                    </span>
                  )}
                </dd>
              </div>
            </dl>

            <h4 className="detail-subhead">Original complaint text</h4>
            <p className="complaint-text">{value(complaint.text)}</p>
          </section>

          <section className="detail-block">
            <h3>Priority</h3>
            <dl className="detail-grid">
              <div>
                <dt>Priority score</dt>
                <dd>
                  {complaint.priority_score === null ||
                  complaint.priority_score === undefined
                    ? DASH
                    : complaint.priority_score.toFixed(1)}
                </dd>
              </div>
              <div>
                <dt>Priority level</dt>
                <dd>{value(complaint.priority_level)}</dd>
              </div>
            </dl>

            <h4 className="detail-subhead">Why this score?</h4>
            {explanation ? (
              <>
                <FactorTable explanation={explanation} />
                {explanation.stored_score === null ||
                explanation.stored_score === undefined ? (
                  <p className="muted small">
                    This complaint has no stored score yet, so the factors below
                    are what the engine would produce now. Nothing is shown as a
                    stored value.
                  </p>
                ) : null}
                {scoreHasDrifted(explanation) ? (
                  <p className="muted small">
                    These factors now add up to {explanation.current_score.toFixed(1)},
                    but the score shown above is the {explanation.stored_score?.toFixed(1)}
                    {' '}stored when this complaint was last scored. The underlying
                    ward data has changed since. Re-scoring is a separate,
                    deliberate action and is not triggered by viewing.
                  </p>
                ) : null}
              </>
            ) : explanationError ? (
              <p className="muted small">
                The factor breakdown could not be loaded. The score above is the
                value stored on the complaint and is unaffected.
              </p>
            ) : (
              <button
                type="button"
                className="btn"
                onClick={loadExplanation}
                disabled={loadingExplanation}
              >
                {loadingExplanation ? 'Loading factors…' : 'Why this score?'}
              </button>
            )}
          </section>

          <section className="detail-block">
            <h3>AI understanding</h3>
            {hasAnalysis(complaint) ? (
              <>
                <p className="muted small">
                  Recorded on this complaint when it was submitted, by whichever
                  AI provider answered. This is the system's reading of the
                  citizen's text, not a field the officer entered.
                </p>
                <dl className="detail-grid">
                  <div>
                    <dt>Urgency</dt>
                    <dd>
                      {complaint.analysis_urgency ? (
                        <span
                          className={`chip chip-${slug(complaint.analysis_urgency)}`}
                        >
                          {value(complaint.analysis_urgency)}
                        </span>
                      ) : (
                        DASH
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Affected group</dt>
                    <dd>{value(complaint.analysis_affected_group)}</dd>
                  </div>
                </dl>
                <div>
                  <span className="tile-label">Issue summary</span>
                  <p className="complaint-text">
                    {value(complaint.analysis_issue_summary)}
                  </p>
                </div>
                <div>
                  <span className="tile-label">Recommended action</span>
                  <p className="complaint-text">
                    {value(complaint.analysis_recommended_action)}
                  </p>
                </div>
              </>
            ) : (
              <p className="muted small">
                No AI analysis was recorded for this complaint. Nothing is shown
                here rather than a generated placeholder.
              </p>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

/** Lowercase, punctuation-free token for chip styling. */
function slug(raw: string | null | undefined): string {
  if (!raw) return 'na'
  return raw.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
}
