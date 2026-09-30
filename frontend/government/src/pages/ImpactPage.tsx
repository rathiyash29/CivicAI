import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getAuthToken } from '../api/client'
import {
  listProjects,
  listImpacts,
  getImpactSummary,
  type Project,
  type Impact,
  type ImpactSummary,
} from '../api/projects'
import { EmptyState, ErrorState, LoadingState } from '../components/States'

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

/** A signed change, so a reduction reads as a reduction rather than a rise. */
function signed(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH
  return value > 0 ? `+${value}` : String(value)
}

/**
 * Impact Dashboard — aggregate view of measured project outcomes.
 *
 * Data from GET /impact/summary and GET /impact, the officer-wide listing of
 * impact records. The listing is what makes a per-project "has this been
 * measured?" answer possible: before it, this page held an empty map, fetched
 * every project's impact and threw the results away, and hardcoded
 * `hasImpact = false`, so every completed project claimed to be awaiting a
 * measurement regardless of the truth.
 *
 * "Awaiting measurement" is now shown only when no record exists for that
 * project. Where a record does exist, its observed changes are shown on the
 * card. No causal claims are made — only observed changes are displayed.
 */
export function ImpactPage() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [summary, setSummary] = useState<ImpactSummary | null>(null)
  const [impacts, setImpacts] = useState<Map<number, Impact> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'with-impact' | 'awaiting'>('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = getAuthToken()
      if (!token) {
        throw new ApiError('No active session. Please sign in again.', 401)
      }
      const [projectsData, summaryData, impactData] = await Promise.all([
        listProjects(token),
        getImpactSummary(token),
        listImpacts(token),
      ])
      setProjects(projectsData)
      setSummary(summaryData)
      // Keyed by project id, because that is what a card holds. `measured_project_ids`
      // is the same set as a list, used as the authoritative membership test.
      setImpacts(new Map(impactData.impacts.map((impact) => [impact.project_id, impact])))
    } catch (caught) {
      setProjects(null)
      setSummary(null)
      setImpacts(null)
      setError(caught instanceof Error ? caught : new Error('Unexpected error'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const completedProjects = useMemo(() => {
    return projects?.filter((p) => p.status === 'Completed') ?? []
  }, [projects])

  const measured = useMemo(() => impacts ?? new Map<number, Impact>(), [impacts])

  const visible = useMemo(() => {
    if (!completedProjects) return []
    const needle = query.trim().toLowerCase()
    return completedProjects.filter((project) => {
      if (statusFilter === 'with-impact' && !measured.has(project.id)) return false
      if (statusFilter === 'awaiting' && measured.has(project.id)) return false
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
  }, [completedProjects, query, statusFilter, measured])

  const filtersActive = query.trim() !== '' || statusFilter !== 'all'

  if (loading) {
    return <LoadingState label="Loading impact data…" />
  }

  if (error) {
    return <ErrorState error={error} onRetry={load} />
  }

  if (!summary) {
    return null
  }

  return (
    <div className="stack">
      <div className="hero-card">
        <div>
          <h2>Impact</h2>
          <p className="muted">
            Measure observed changes after project completion using recorded
            before-and-after indicators.
          </p>
        </div>
        <button type="button" className="btn ghost" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div className="tiles">
        <section className="card">
          <span className="tile-label">Completed Projects</span>
          <strong className="tile-value">{summary.total_completed_projects}</strong>
          <span className="muted small">Projects in Completed status</span>
        </section>
        <section className="card">
          <span className="tile-label">With Measured Impact</span>
          <strong className="tile-value">{summary.projects_with_measured_impact}</strong>
          <span className="muted small">Projects with recorded impact data</span>
        </section>
        <section className="card">
          <span className="tile-label">Awaiting Measurement</span>
          <strong className="tile-value">{summary.projects_awaiting_impact_measurement}</strong>
          <span className="muted small">Completed projects without impact record</span>
        </section>
        <section className="card">
          <span className="tile-label">Associated Complaints</span>
          <strong className="tile-value">{summary.total_complaints_associated}</strong>
          <span className="muted small">Complaints linked to completed projects</span>
        </section>
        <section className="card">
          <span className="tile-label">Observed Complaint Reduction</span>
          <strong className="tile-value">{summary.observed_complaint_reduction}</strong>
          <span className="muted small">Sum of negative complaint changes</span>
        </section>
        <section className="card">
          <span className="tile-label">Projects Showing Reduction</span>
          <strong className="tile-value">{summary.projects_showing_reduction}</strong>
          <span className="muted small">Projects with observed decrease</span>
        </section>
      </div>

      {completedProjects.length === 0 ? (
        <EmptyState
          title="No completed projects yet"
          hint="Projects reach Completed status through the Projects page workflow. Impact can be recorded once a project is Completed."
        />
      ) : (
        <>
          <section className="card">
            <div className="filters">
              <div className="filter grow">
                <label htmlFor="impact-search">Search</label>
                <input
                  id="impact-search"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Project title, action, ward, officer or recommendation"
                />
              </div>
              <div className="filter">
                <label htmlFor="impact-status">Impact Status</label>
                <select
                  id="impact-status"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value as 'all' | 'with-impact' | 'awaiting')}
                >
                  <option value="all">All completed</option>
                  <option value="with-impact">With impact record</option>
                  <option value="awaiting">Awaiting measurement</option>
                </select>
              </div>
            </div>

            <div className="list-meta">
              <span className="muted small">
                Showing {visible.length} of {completedProjects.length} completed project
                {completedProjects.length === 1 ? '' : 's'}
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

          {visible.length === 0 ? (
            <EmptyState
              title="No projects match these filters"
              hint="Try a different impact status, or clear the search box."
            />
          ) : (
            <div className="cards always">
              {visible.map((project) => {
                const unresolved = !project.location || project.location === 'Unassigned'
                // From the real impact listing. A project with no record here
                // genuinely has none, which is the only case that is allowed to
                // say it is awaiting measurement.
                const impact = measured.get(project.id) ?? null

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

                    <div className="impact-status">
                      {impact ? (
                        <>
                          <span className="chip chip-completed">Impact recorded</span>
                          <span className="muted small">
                            Measured {formatDate(impact.measurement_period_start)}
                            {impact.measurement_period_end
                              ? ` to ${formatDate(impact.measurement_period_end)}`
                              : ''}
                            . Recorded by {impact.recorded_by?.name ?? DASH}.
                          </span>
                          <dl className="mini-grid">
                            <div>
                              <dt>Complaints before</dt>
                              <dd>{impact.before_complaint_count ?? DASH}</dd>
                            </div>
                            <div>
                              <dt>Complaints after</dt>
                              <dd>{impact.after_complaint_count ?? DASH}</dd>
                            </div>
                            <div>
                              <dt>Observed change</dt>
                              <dd>
                                {signed(impact.observed_change?.complaint_change)}
                              </dd>
                            </div>
                            <div>
                              <dt>Priority change</dt>
                              <dd>
                                {signed(impact.observed_change?.priority_change)}
                              </dd>
                            </div>
                          </dl>
                          {impact.officer_notes ? (
                            <p className="recommendation-reason">{impact.officer_notes}</p>
                          ) : null}
                          <Link className="link" to="/dashboard/projects">
                            View or update this measurement
                          </Link>
                        </>
                      ) : (
                        <>
                          <span className="chip chip-status-changed">
                            Awaiting impact measurement
                          </span>
                          <span className="muted small">
                            No impact record exists for this project.
                          </span>
                          <Link className="link" to="/dashboard/projects">
                            Record impact on the Projects page
                          </Link>
                        </>
                      )}
                    </div>
                  </article>
                )
              })}
            </div>
          )}

          <p className="muted small source-note">
            Recorded measurements describe observed change and should be
            interpreted alongside other factors.
          </p>
        </>
      )}
    </div>
  )
}