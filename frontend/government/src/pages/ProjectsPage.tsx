import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getAuthToken } from '../api/client'
import {
  listProjects,
  nextStatus,
  updateProjectStatus,
  recordProjectImpact,
  getProjectImpact,
  updateProjectImpact,
  type Project,
  type Impact,
  type ImpactRecordRequest,
} from '../api/projects'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { ImpactForm } from '../components/ImpactForm'

/**
 * Projects created from approved recommendations.
 *
 * Real rows from GET /projects. Status moves go through
 * PATCH /projects/{id}/status, which enforces the one-step-forward rule server
 * side; this page only ever offers the single next status, so an invalid
 * transition cannot be attempted from here. A refusal from the API is shown
 * verbatim rather than swallowed.
 */

const DASH = '—'

function slug(raw: string | null | undefined): string {
  if (!raw) return 'na'
  return raw.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
}

function formatDate(raw: string | null | undefined): string {
  if (!raw) return DASH
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const date = new Date(hasZone ? raw : `${raw}Z`)
  if (Number.isNaN(date.getTime())) return DASH
  return date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function officerName(project: Project): string {
  return project.officer?.name ?? project.officer?.email ?? DASH
}

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [pendingId, setPendingId] = useState<number | null>(null)
  const [rowError, setRowError] = useState<string | null>(null)

  // Impact modal state
  const [impactProject, setImpactProject] = useState<Project | null>(null)
  const [impactData, setImpactData] = useState<Impact | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)
  const [impactError, setImpactError] = useState<string | null>(null)
  const [impactSubmitting, setImpactSubmitting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = getAuthToken()
      if (!token) {
        throw new ApiError('No active session. Please sign in again.', 401)
      }
      setProjects(await listProjects(token))
    } catch (caught) {
      setProjects(null)
      setError(caught instanceof Error ? caught : new Error('Unexpected error'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const statusOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const project of projects ?? []) {
      if (project.status) seen.add(project.status)
    }
    return [...seen].sort()
  }, [projects])

  const visible = useMemo(() => {
    if (!projects) return []
    const needle = query.trim().toLowerCase()
    return projects.filter((project) => {
      if (statusFilter !== 'all' && project.status !== statusFilter) return false
      if (!needle) return true
      const haystack = [
        project.title,
        project.description,
        project.action,
        project.location,
        String(project.recommendation_id ?? ''),
        officerName(project),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(needle)
    })
  }, [projects, query, statusFilter])

  const totals = useMemo(() => {
    const source = visible
    return {
      shown: source.length,
      inProgress: source.filter((p) => p.status === 'In Progress').length,
      completed: source.filter((p) => p.status === 'Completed').length,
      approved: source.filter((p) => p.status === 'Approved').length,
    }
  }, [visible])

  const filtersActive = query.trim() !== '' || statusFilter !== 'all'

  async function advance(project: Project) {
    const next = nextStatus(project.status)
    if (!next) return
    setRowError(null)
    setPendingId(project.id)
    const token = getAuthToken()
    if (!token) {
      setRowError('No active session. Please sign in again.')
      setPendingId(null)
      return
    }
    try {
      await updateProjectStatus(token, project.id, next)
      await load()
    } catch (caught) {
      setRowError(caught instanceof Error ? caught.message : 'The update failed')
    } finally {
      setPendingId(null)
    }
  }

  async function openImpactModal(project: Project) {
    const token = getAuthToken()
    if (!token) {
      setRowError('No active session. Please sign in again.')
      return
    }
    setImpactProject(project)
    setImpactError(null)
    setImpactLoading(true)
    try {
      const impact = await getProjectImpact(token, project.id)
      setImpactData(impact)
    } catch (caught) {
      // No impact recorded yet - that's fine, we'll show empty form
      setImpactData(null)
    } finally {
      setImpactLoading(false)
    }
  }

  function closeImpactModal() {
    setImpactProject(null)
    setImpactData(null)
    setImpactError(null)
  }

  async function submitImpact(body: ImpactRecordRequest) {
    if (!impactProject) return
    const token = getAuthToken()
    if (!token) {
      setImpactError('No active session. Please sign in again.')
      return
    }
    setImpactSubmitting(true)
    setImpactError(null)
    try {
      if (impactData) {
        await updateProjectImpact(token, impactProject.id, body)
      } else {
        await recordProjectImpact(token, impactProject.id, body)
      }
      await load()
      closeImpactModal()
    } catch (caught) {
      setImpactError(caught instanceof Error ? caught.message : 'Failed to record impact')
    } finally {
      setImpactSubmitting(false)
    }
  }

  return (
    <div className="stack">
      <div className="hero-card">
        <div>
          <h2>Projects</h2>
          <p className="muted">
            Track development initiatives created from approved government
            decisions, from authorization through completion.
          </p>
        </div>
        <button type="button" className="btn ghost" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {loading ? <LoadingState label="Loading projects…" /> : null}

      {!loading && error ? <ErrorState error={error} onRetry={load} /> : null}

      {!loading && !error && projects && projects.length === 0 ? (
        <EmptyState
          title="No projects yet"
          hint="A project is created when an officer approves or modifies a recommendation on the Recommendations page."
        />
      ) : null}

      {!loading && !error && projects && projects.length > 0 ? (
        <>
          <div className="tiles">
            <section className="card">
              <span className="tile-label">Projects</span>
              <strong className="tile-value">{totals.shown}</strong>
              <span className="muted small">Shown after filtering</span>
            </section>
            <section className="card">
              <span className="tile-label">Approved</span>
              <strong className="tile-value">{totals.approved}</strong>
              <span className="muted small">Signed off, not yet started</span>
            </section>
            <section className="card">
              <span className="tile-label">In progress</span>
              <strong className="tile-value">{totals.inProgress}</strong>
              <span className="muted small">Work underway</span>
            </section>
            <section className="card">
              <span className="tile-label">Completed</span>
              <strong className="tile-value">{totals.completed}</strong>
              <span className="muted small">Finished work</span>
            </section>
          </div>

          <section className="card">
            <div className="filters">
              <div className="filter grow">
                <label htmlFor="project-search">Search</label>
                <input
                  id="project-search"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Title, action, ward, officer or recommendation"
                />
              </div>
              <div className="filter">
                <label htmlFor="project-status">Status</label>
                <select
                  id="project-status"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                >
                  <option value="all">All statuses</option>
                  {statusOptions.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="list-meta">
              <span className="muted small">
                Showing {visible.length} of {projects.length} project
                {projects.length === 1 ? '' : 's'}
              </span>
              {filtersActive ? (
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => {
                    setQuery('')
                    setStatusFilter('all')
                  }}
                >
                  Clear filters
                </button>
              ) : null}
            </div>
          </section>

          {rowError ? (
            <p className="form-error" role="alert">
              {rowError}
            </p>
          ) : null}

          {visible.length === 0 ? (
            <EmptyState
              title="No projects match these filters"
              hint="Try a different status, or clear the search box."
            />
          ) : (
            <div className="cards always">
              {visible.map((project) => {
                const next = nextStatus(project.status)
                const isOpen = expanded === project.id
                const unresolved = !project.location || project.location === 'Unassigned'

                return (
                  <article key={project.id} className="card project-card">
                    <div className="hotspot-head">
                      <div>
                        <span className="tile-label">Project</span>
                        <h3 className="recommendation-action">{project.title || DASH}</h3>
                        <p className={unresolved ? 'unresolved-place' : 'recommendation-place'}>
                          {unresolved ? 'Location unresolved' : project.location}
                        </p>
                      </div>
                      <span className={`chip chip-${slug(project.status)}`}>
                        {project.status}
                      </span>
                    </div>

                    <dl className="mini-grid">
                      <div>
                        <dt>Recommendation</dt>
                        <dd className="mono">
                          {project.recommendation_id ? (
                            // Back to the recommendation this project was
                            // created from, so an officer can re-read the
                            // evidence behind the work they are tracking.
                            <Link
                              className="link mono"
                              to={`/dashboard/recommendations?recommendation=${project.recommendation_id}`}
                            >
                              #{project.recommendation_id}
                            </Link>
                          ) : (
                            DASH
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>Officer</dt>
                        <dd>{officerName(project)}</dd>
                      </div>
                      <div>
                        <dt>Created</dt>
                        <dd>{formatDate(project.created_at)}</dd>
                      </div>
                      <div>
                        <dt>Related complaints</dt>
                        <dd>{project.related_complaints ?? DASH}</dd>
                      </div>
                    </dl>

                    {project.description ? (
                      <p className="recommendation-reason">{project.description}</p>
                    ) : null}

                    <div className="decision-row">
                      {next ? (
                        <button
                          type="button"
                          className="btn primary"
                          disabled={pendingId === project.id}
                          onClick={() => advance(project)}
                        >
                          {pendingId === project.id
                            ? 'Updating…'
                            : `Mark ${next}`}
                        </button>
                      ) : (
                        <>
                          <span className="muted small">This project is completed.</span>
                          <button
                            type="button"
                            className="btn secondary"
                            onClick={() => openImpactModal(project)}
                          >
                            {impactData ? 'View Impact' : 'Record Impact'}
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() => setExpanded(isOpen ? null : project.id)}
                        aria-expanded={isOpen}
                      >
                        {isOpen ? 'Hide decisions' : 'View decisions'}
                      </button>
                    </div>

                    {isOpen ? (
                      <div className="recommendation-detail">
                        <h4 className="detail-subhead">Decision history</h4>
                        {project.decisions.length === 0 ? (
                          <p className="muted small">No decisions recorded.</p>
                        ) : (
                          <div className="decision-history">
                            {project.decisions.map((entry) => (
                              <div key={entry.id} className="decision-entry">
                                <span
                                  className={`chip chip-${entry.decision
                                    .toLowerCase()
                                    .replace(' ', '-')}`}
                                >
                                  {entry.decision}
                                </span>
                                <span className="muted small">
                                  {entry.officer?.name ?? entry.officer?.email ?? 'Officer'}
                                  {entry.created_at
                                    ? ` · ${formatDate(entry.created_at)}`
                                    : ''}
                                </span>
                                {entry.reason ? (
                                  <p className="decision-reason">{entry.reason}</p>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : null}
                  </article>
                )
              })}
            </div>
          )}

          <p className="muted small source-note">
            Project status reflects the current stage of government
            implementation.
          </p>
        </>
      ) : null}

      {/* Impact Modal */}
      {impactProject && (
        <div className="modal-overlay" onClick={closeImpactModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{impactData ? 'View Impact' : 'Record Impact'} — {impactProject.title}</h3>
              <button type="button" className="btn ghost" onClick={closeImpactModal}>
                ×
              </button>
            </div>
            {impactLoading ? (
              <LoadingState label="Loading impact data…" />
            ) : (
              <>
                {impactError ? (
                  <p className="form-error" role="alert">{impactError}</p>
                ) : null}
                {impactData ? (
                  <div className="impact-view">
                    <dl className="mini-grid">
                      <div>
                        <dt>Before complaints</dt>
                        <dd>{impactData.before_complaint_count ?? DASH}</dd>
                      </div>
                      <div>
                        <dt>After complaints</dt>
                        <dd>{impactData.after_complaint_count ?? DASH}</dd>
                      </div>
                      <div>
                        <dt>Complaints resolved</dt>
                        <dd>{impactData.complaints_resolved ?? DASH}</dd>
                      </div>
                      <div>
                        <dt>Before avg severity</dt>
                        <dd>{impactData.before_avg_severity_score ?? DASH}</dd>
                      </div>
                      <div>
                        <dt>After avg severity</dt>
                        <dd>{impactData.after_avg_severity_score ?? DASH}</dd>
                      </div>
                      <div>
                        <dt>Before avg priority</dt>
                        <dd>{impactData.before_avg_priority_score ?? DASH}</dd>
                      </div>
                      <div>
                        <dt>After avg priority</dt>
                        <dd>{impactData.after_avg_priority_score ?? DASH}</dd>
                      </div>
                      <div>
                        <dt>Measurement period</dt>
                        <dd>
                          {impactData.measurement_period_start
                            ? `${formatDate(impactData.measurement_period_start)} — ${formatDate(
                                impactData.measurement_period_end
                              )}`
                            : DASH}
                        </dd>
                      </div>
                    </dl>
                    {impactData.officer_notes ? (
                      <p className="recommendation-reason">
                        <strong>Officer notes:</strong> {impactData.officer_notes}
                      </p>
                    ) : null}
                    <div className="observed-change">
                      <h4>Observed Changes</h4>
                      <p className="muted small">
                        These are observed measurements only — they do not imply the project caused
                        the change.
                      </p>
                      <dl className="mini-grid">
                        <div>
                          <dt>Complaint change</dt>
                          <dd>
                            {impactData.observed_change.complaint_change !== null
                              ? `${impactData.observed_change.complaint_change > 0 ? '+' : ''}${
                                  impactData.observed_change.complaint_change
                                }`
                              : DASH}
                          </dd>
                        </div>
                        <div>
                          <dt>Complaint change %</dt>
                          <dd>
                            {impactData.observed_change.complaint_change_percent !== null
                              ? `${impactData.observed_change.complaint_change_percent > 0 ? '+' : ''}${
                                  impactData.observed_change.complaint_change_percent
                                }%`
                              : DASH}
                          </dd>
                        </div>
                        <div>
                          <dt>Severity change</dt>
                          <dd>
                            {impactData.observed_change.severity_change !== null
                              ? `${impactData.observed_change.severity_change > 0 ? '+' : ''}${
                                  impactData.observed_change.severity_change
                                }`
                              : DASH}
                          </dd>
                        </div>
                        <div>
                          <dt>Priority change</dt>
                          <dd>
                            {impactData.observed_change.priority_change !== null
                              ? `${impactData.observed_change.priority_change > 0 ? '+' : ''}${
                                  impactData.observed_change.priority_change
                                }`
                              : DASH}
                          </dd>
                        </div>
                      </dl>
                    </div>
                    <div className="modal-actions">
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() => {
                          setImpactData(null)
                        }}
                      >
                        Record New Measurement
                      </button>
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={closeImpactModal}
                      >
                        Close
                      </button>
                    </div>
                  </div>
                ) : (
                  <ImpactForm
                    project={impactProject!}
                    initialData={impactData ?? undefined}
                    autoCalculate={true}
                    onSubmit={submitImpact}
                    onCancel={closeImpactModal}
                    submitting={impactSubmitting}
                  />
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
