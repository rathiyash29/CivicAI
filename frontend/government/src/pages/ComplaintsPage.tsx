import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, getAuthToken } from '../api/client'
import { fetchComplaints, type Complaint } from '../api/complaints'
import { ComplaintDetailModal, formatDate } from '../components/ComplaintDetailModal'
import { EmptyState, ErrorState, LoadingState } from '../components/States'

const DASH = '—'

function value(raw: string | number | null | undefined): string {
  if (raw === null || raw === undefined) return DASH
  const text = String(raw).trim()
  return text === '' ? DASH : text
}

function matches(complaint: Complaint, query: string): boolean {
  if (!query) return true
  const needle = query.trim().toLowerCase()
  const haystack = [
    complaint.complaint_id,
    complaint.category,
    complaint.location,
    complaint.text,
  ]
    .filter((field): field is string => Boolean(field))
    .join(' ')
    .toLowerCase()
  return haystack.includes(needle)
}

export function ComplaintsPage() {
  const [complaints, setComplaints] = useState<Complaint[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const [query, setQuery] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selected, setSelected] = useState<Complaint | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = getAuthToken()
      if (!token) {
        throw new ApiError('No active session. Please sign in again.', 401)
      }
      const data = await fetchComplaints(token)
      setComplaints(data.complaints ?? [])
    } catch (caught) {
      setComplaints(null)
      setError(caught instanceof Error ? caught : new Error('Unexpected error'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Filter options come from the data that actually arrived, so the dropdowns
  // can never offer a value the API is not returning.
  const priorityOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const complaint of complaints ?? []) {
      if (complaint.priority_level) seen.add(complaint.priority_level)
    }
    return [...seen].sort()
  }, [complaints])

  const statusOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const complaint of complaints ?? []) {
      if (complaint.status) seen.add(complaint.status)
    }
    return [...seen].sort()
  }, [complaints])

  // Arrival filter from a recommendation ("show me the complaints behind
  // this"), which is the one direction of the pipeline link that lands here.
  const [searchParams, setSearchParams] = useSearchParams()
  const focusCluster = searchParams.get('cluster')

  const visible = useMemo(() => {
    if (!complaints) return []
    return complaints.filter((complaint) => {
      // An arrival filter wins over the officer's own filters: it is why they
      // are here, and quietly ignoring it would show a list without the thing
      // they clicked through for.
      if (focusCluster && complaint.cluster_id !== Number(focusCluster)) return false
      if (priorityFilter !== 'all' && complaint.priority_level !== priorityFilter) {
        return false
      }
      if (statusFilter !== 'all' && complaint.status !== statusFilter) return false
      return matches(complaint, query)
    })
  }, [complaints, query, priorityFilter, statusFilter, focusCluster])

  const filtersActive =
    query.trim() !== '' ||
    priorityFilter !== 'all' ||
    statusFilter !== 'all' ||
    Boolean(focusCluster)

  function resetFilters() {
    setQuery('')
    setPriorityFilter('all')
    setStatusFilter('all')
    setSearchParams({})
  }

  return (
    <div className="stack">
      <div className="hero-card">
        <div>
          <h2>Complaints</h2>
          <p className="muted">
            Review and investigate citizen-reported issues, their AI-generated
            understanding, locations, severity, and priority.
          </p>
        </div>
        <button type="button" className="btn ghost" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {loading ? <LoadingState label="Loading complaints…" /> : null}

      {!loading && error ? <ErrorState error={error} onRetry={load} /> : null}

      {!loading && !error && complaints && complaints.length === 0 ? (
        <EmptyState
          title="No complaints yet"
          hint="Complaints appear here as soon as citizens submit them through the CivicAI portal."
        />
      ) : null}

      {!loading && !error && complaints && complaints.length > 0 ? (
        <>
          {focusCluster ? (
            <div className="arrival-note" role="status">
              <span>Showing the complaints in issue cluster #{focusCluster}.</span>
              <button
                type="button"
                className="btn ghost"
                onClick={() => setSearchParams({})}
              >
                Show all complaints
              </button>
            </div>
          ) : null}

          <section className="card">
            <div className="filters">
              <div className="filter grow">
                <label htmlFor="complaint-search">Search</label>
                <input
                  id="complaint-search"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Complaint ID, issue, category or location"
                />
              </div>

              <div className="filter">
                <label htmlFor="priority-filter">Priority level</label>
                <select
                  id="priority-filter"
                  value={priorityFilter}
                  onChange={(event) => setPriorityFilter(event.target.value)}
                >
                  <option value="all">All levels</option>
                  {priorityOptions.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter">
                <label htmlFor="status-filter">Status</label>
                <select
                  id="status-filter"
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
                Showing {visible.length} of {complaints.length} complaint
                {complaints.length === 1 ? '' : 's'}
              </span>
              {filtersActive ? (
                <button type="button" className="btn ghost" onClick={resetFilters}>
                  Clear filters
                </button>
              ) : null}
            </div>
          </section>

          {visible.length === 0 ? (
            <EmptyState
              title="No complaints match these filters"
              hint="Try clearing the search box or choosing a different priority level and status."
            />
          ) : (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Complaint ID</th>
                      <th>Issue</th>
                      <th>Location</th>
                      <th>Severity</th>
                      <th className="num">Priority score</th>
                      <th>Priority level</th>
                      <th>Status</th>
                      <th>Submitted</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((complaint) => (
                      <tr key={complaint.complaint_id}>
                        <td data-label="Complaint ID" className="mono">
                          {value(complaint.complaint_id)}
                        </td>
                        <td data-label="Issue">{value(complaint.category)}</td>
                        <td data-label="Location">{value(complaint.location)}</td>
                        <td data-label="Severity">
                          <span className={`chip chip-${slug(complaint.severity)}`}>
                            {value(complaint.severity)}
                          </span>
                        </td>
                        <td data-label="Priority score" className="num">
                          {complaint.priority_score === null ||
                          complaint.priority_score === undefined
                            ? DASH
                            : complaint.priority_score.toFixed(1)}
                        </td>
                        <td data-label="Priority level">
                          <span className={`chip chip-${slug(complaint.priority_level)}`}>
                            {value(complaint.priority_level)}
                          </span>
                        </td>
                        <td data-label="Status">{value(complaint.status)}</td>
                        <td data-label="Submitted">{formatDate(complaint.created_at)}</td>
                        <td data-label="Actions">
                          <button
                            type="button"
                            className="btn"
                            onClick={() => setSelected(complaint)}
                          >
                            View Details
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Card layout for narrow screens; the table above stays for wide. */}
              <div className="cards">
                {visible.map((complaint) => (
                  <article key={complaint.complaint_id} className="card complaint-card">
                    <div className="complaint-card-head">
                      <strong className="mono">{value(complaint.complaint_id)}</strong>
                      <span className="chip chip-status">{value(complaint.status)}</span>
                    </div>
                    <p className="complaint-card-title">{value(complaint.category)}</p>
                    <p className="muted small">{value(complaint.location)}</p>
                    <dl className="mini-grid">
                      <div>
                        <dt>Severity</dt>
                        <dd>{value(complaint.severity)}</dd>
                      </div>
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
                      <div>
                        <dt>Submitted</dt>
                        <dd>{formatDate(complaint.created_at)}</dd>
                      </div>
                    </dl>
                    <button
                      type="button"
                      className="btn block"
                      onClick={() => setSelected(complaint)}
                    >
                      View Details
                    </button>
                  </article>
                ))}
              </div>
            </>
          )}
        </>
      ) : null}

      {selected ? (
        <ComplaintDetailModal complaint={selected} onClose={() => setSelected(null)} />
      ) : null}
    </div>
  )
}

/** Lowercase, punctuation-free token for chip styling. */
function slug(raw: string | null | undefined): string {
  if (!raw) return 'na'
  return raw.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
}
