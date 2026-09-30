import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, getAuthToken } from '../api/client'
import {
  fetchRecommendations,
  UNRESOLVED_LOCATION,
  type Recommendation,
} from '../api/recommendations'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { DecisionControls } from '../components/DecisionControls'

/**
 * Officer decision support over the CivicAI recommendation engine.
 *
 * Everything rendered here comes from GET /intelligence/recommendations. There
 * is no second source and no fallback data: if the endpoint is down the page
 * says so.
 *
 * Approve / Modify / Reject are real, persisted calls into the decision
 * workflow (`/projects/recommendations/...`). They are not optimistic: each one
 * re-reads the decision history from the API before reporting success, so a
 * refresh always agrees with the screen.
 *
 * This page is the hub of the pipeline. It is reachable from a complaint (by
 * cluster), from a hotspot (by cluster), and from a project (by
 * recommendation), which is why `?cluster=` and `?recommendation=` are read
 * from the URL rather than held only in component state: an officer who
 * follows a link from another page lands on the right card, and the address
 * bar stays shareable.
 */

const DASH = '—'

function slug(raw: string | null | undefined): string {
  if (!raw) return 'na'
  return raw.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
}

/** A cluster whose complaints never resolved to a ward is not a place. */
function isUnresolved(location: string | null | undefined): boolean {
  return !location || location.trim() === UNRESOLVED_LOCATION
}

function formatPopulation(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH
  return new Intl.NumberFormat('en-IN').format(value)
}

export function RecommendationsPage() {
  const [recommendations, setRecommendations] = useState<Recommendation[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const [query, setQuery] = useState('')
  const [levelFilter, setLevelFilter] = useState('all')
  const [locationFilter, setLocationFilter] = useState('all')
  const [actionFilter, setActionFilter] = useState('all')
  const [expanded, setExpanded] = useState<number | null>(null)

  // Cross-page arrival. `cluster` comes from a complaint or a hotspot, and
  // `recommendation` from a project. Both filter the list down to the thing the
  // officer was sent to see rather than leaving them to hunt for it.
  const [searchParams, setSearchParams] = useSearchParams()
  const focusCluster = searchParams.get('cluster')
  const focusRecommendation = searchParams.get('recommendation')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = getAuthToken()
      if (!token) {
        throw new ApiError('No active session. Please sign in again.', 401)
      }
      const data = await fetchRecommendations(token)
      setRecommendations(data.recommendations ?? [])
    } catch (caught) {
      setRecommendations(null)
      setError(caught instanceof Error ? caught : new Error('Unexpected error'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Options are derived from what the engine actually returned, so a filter can
  // never offer a value the API is not returning.
  const levelOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const item of recommendations ?? []) {
      if (item.priority_level) seen.add(item.priority_level)
    }
    const order = ['High', 'Medium', 'Low']
    return [...seen].sort((a, b) => order.indexOf(a) - order.indexOf(b))
  }, [recommendations])

  const locationOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const item of recommendations ?? []) {
      seen.add(item.location ?? UNRESOLVED_LOCATION)
    }
    return [...seen].sort((a, b) => a.localeCompare(b))
  }, [recommendations])

  const actionOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const item of recommendations ?? []) {
      if (item.action) seen.add(item.action)
    }
    return [...seen].sort((a, b) => a.localeCompare(b))
  }, [recommendations])

  const visible = useMemo(() => {
    if (!recommendations) return []
    const needle = query.trim().toLowerCase()
    const focusClusterId = focusCluster ? Number(focusCluster) : null
    const focusRecommendationId = focusRecommendation ? Number(focusRecommendation) : null
    return recommendations.filter((item) => {
      // Arrival filters take precedence over the officer's own filters: they
      // describe why they are here, and silently ignoring them would show a
      // list that does not contain the thing they clicked through for.
      if (focusClusterId !== null && item.cluster_id !== focusClusterId) return false
      if (focusRecommendationId !== null && item.recommendation_id !== focusRecommendationId) {
        return false
      }
      if (levelFilter !== 'all' && item.priority_level !== levelFilter) return false
      if (actionFilter !== 'all' && item.action !== actionFilter) return false

      const location = item.location ?? UNRESOLVED_LOCATION
      if (locationFilter === 'unresolved') {
        if (!isUnresolved(location)) return false
      } else if (locationFilter !== 'all' && location !== locationFilter) {
        return false
      }

      if (!needle) return true
      const haystack = [
        item.action,
        item.location,
        item.reason,
        String(item.cluster_id),
        String(item.recommendation_id),
        item.evidence?.infrastructure_gap,
        item.evidence?.investment_gap,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(needle)
    })
  }, [recommendations, query, levelFilter, locationFilter, actionFilter, focusCluster, focusRecommendation])

  /**
   * The card the officer arrived for is opened automatically, so the evidence
   * and decision controls are already on screen rather than one click away.
   * Depends on the ids rather than the object, so a background refresh that
   * returns new objects does not collapse it again.
   */
  useEffect(() => {
    if (!recommendations?.length) return
    if (expanded !== null) return
    if (focusRecommendation) {
      const target = Number(focusRecommendation)
      if (recommendations.some((item) => item.recommendation_id === target)) {
        setExpanded(target)
      }
      return
    }
    if (focusCluster) {
      const target = Number(focusCluster)
      const match = recommendations.find((item) => item.cluster_id === target)
      if (match) setExpanded(match.recommendation_id)
    }
  }, [recommendations, focusCluster, focusRecommendation, expanded])

  /** Drop the arrival filter and show the full list again. */
  function clearArrivalFilter() {
    setSearchParams({})
  }

  const totals = useMemo(() => {
    const source = visible
    return {
      shown: source.length,
      complaints: source.reduce(
        (sum, item) => sum + (item.evidence?.related_complaints ?? 0),
        0,
      ),
      highPriority: source.filter(
        (item) => (item.priority_level ?? '').toLowerCase() === 'high',
      ).length,
      unresolved: source.filter((item) => isUnresolved(item.location)).length,
    }
  }, [visible])

  const filtersActive =
    query.trim() !== '' ||
    levelFilter !== 'all' ||
    locationFilter !== 'all' ||
    actionFilter !== 'all'

  function resetFilters() {
    setQuery('')
    setLevelFilter('all')
    setLocationFilter('all')
    setActionFilter('all')
  }

  return (
    <div className="stack">
      <div className="hero-card">
        <div>
          <h2>Recommendations</h2>
          <p className="muted">
            AI-assisted development recommendations based on citizen demand,
            infrastructure gaps, population impact, urgency, and investment
            context.
          </p>
        </div>
        <button type="button" className="btn ghost" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {loading ? <LoadingState label="Loading recommendations…" /> : null}

      {!loading && error ? <ErrorState error={error} onRetry={load} /> : null}

      {!loading && !error && recommendations && recommendations.length === 0 ? (
        <EmptyState
          title="No recommendations yet"
          hint="The engine returned nothing. A recommendation is produced once complaints form a cluster with a known issue category."
        />
      ) : null}

      {!loading && !error && recommendations && recommendations.length > 0 ? (
        <>
          {focusCluster || focusRecommendation ? (
            <div className="arrival-note" role="status">
              <span>
                {focusRecommendation
                  ? `Showing recommendation #${focusRecommendation}, which this project came from.`
                  : `Showing issue cluster #${focusCluster}.`}
              </span>
              <button type="button" className="btn ghost" onClick={clearArrivalFilter}>
                Show all recommendations
              </button>
            </div>
          ) : null}

          <div className="tiles">
            <section className="card">
              <span className="tile-label">Recommendations</span>
              <strong className="tile-value">{totals.shown}</strong>
              <span className="muted small">Shown after filtering</span>
            </section>
            <section className="card">
              <span className="tile-label">Complaints behind them</span>
              <strong className="tile-value">{totals.complaints}</strong>
              <span className="muted small">Related complaints, as reported</span>
            </section>
            <section className="card">
              <span className="tile-label">High priority</span>
              <strong className="tile-value">{totals.highPriority}</strong>
              <span className="muted small">Scored in the High band</span>
            </section>
            <section className="card">
              <span className="tile-label">Location unresolved</span>
              <strong className="tile-value">{totals.unresolved}</strong>
              <span className="muted small">Complaints with no known ward</span>
            </section>
          </div>

          <section className="card">
            <div className="filters">
              <div className="filter grow">
                <label htmlFor="rec-search">Search</label>
                <input
                  id="rec-search"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Action, reason, ward or cluster ID"
                />
              </div>

              <div className="filter">
                <label htmlFor="rec-level">Priority level</label>
                <select
                  id="rec-level"
                  value={levelFilter}
                  onChange={(event) => setLevelFilter(event.target.value)}
                >
                  <option value="all">All levels</option>
                  {levelOptions.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter">
                <label htmlFor="rec-location">Location</label>
                <select
                  id="rec-location"
                  value={locationFilter}
                  onChange={(event) => setLocationFilter(event.target.value)}
                >
                  <option value="all">All locations</option>
                  {locationOptions.map((location) => (
                    <option key={location} value={location}>
                      {isUnresolved(location) ? 'Location unresolved' : location}
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter">
                <label htmlFor="rec-action">Action</label>
                <select
                  id="rec-action"
                  value={actionFilter}
                  onChange={(event) => setActionFilter(event.target.value)}
                >
                  <option value="all">All actions</option>
                  {actionOptions.map((action) => (
                    <option key={action} value={action}>
                      {action}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="list-meta">
              <span className="muted small">
                Showing {visible.length} of {recommendations.length} recommendation
                {recommendations.length === 1 ? '' : 's'}
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
              title="No recommendations match these filters"
              hint="Try a different priority level, location or action, or clear the search box."
            />
          ) : (
            <div className="cards always">
              {visible.map((item) => {
                const isOpen = expanded === item.recommendation_id
                const evidence = item.evidence
                const unresolved = isUnresolved(item.location)

                return (
                  <article key={item.recommendation_id} className="card recommendation-card">
                    <div className="hotspot-head">
                      <div>
                        <span className="tile-label">Recommended action</span>
                        <h3 className="recommendation-action">{item.action || DASH}</h3>
                        <p className={unresolved ? 'unresolved-place' : 'recommendation-place'}>
                          {unresolved ? 'Location unresolved' : item.location}
                          {unresolved ? (
                            <span className="muted small"> — complaints carry no known ward</span>
                          ) : null}
                        </p>
                      </div>
                      <span className={`chip chip-${slug(item.priority_level)}`}>
                        {item.priority_level}
                      </span>
                    </div>

                    <div className="recommendation-metrics">
                      <div className="recommendation-score">
                        <strong>{item.priority_score?.toFixed?.(1) ?? DASH}</strong>
                        <span className="muted small">priority score</span>
                      </div>
                      <div className="recommendation-stat">
                        <span className="muted small">Related complaints</span>
                        <strong>{evidence?.related_complaints ?? DASH}</strong>
                      </div>
                      <div className="recommendation-stat">
                        <span className="muted small">Cluster</span>
                        <strong className="mono">
                          {/* The case file is the whole chain for this cluster;
                              the id is the way into it from anywhere. */}
                          <Link
                            className="link mono"
                            to={`/dashboard/case/${item.cluster_id}`}
                          >
                            #{item.cluster_id}
                          </Link>
                        </strong>
                      </div>
                      <div className="recommendation-stat">
                        <span className="muted small">Recommendation</span>
                        <strong className="mono">#{item.recommendation_id}</strong>
                      </div>
                    </div>

                    <p className="muted small">
                      <Link
                        className="link"
                        to={`/dashboard/case/${item.cluster_id}`}
                      >
                        Open the full case file
                      </Link>
                      {' · '}
                      <Link
                        className="link"
                        to={`/dashboard/complaints?cluster=${item.cluster_id}`}
                      >
                        the {evidence?.related_complaints ?? DASH} complaint
                        {evidence?.related_complaints === 1 ? '' : 's'} behind this
                      </Link>
                    </p>

                    <p className="recommendation-reason">{item.reason || DASH}</p>

                    <button
                      type="button"
                      className="btn ghost block"
                      onClick={() => setExpanded(isOpen ? null : item.recommendation_id)}
                      aria-expanded={isOpen}
                    >
                      {isOpen ? 'Hide evidence and decisions' : 'View evidence and decisions'}
                    </button>

                    {isOpen ? (
                      <div className="recommendation-detail">
                        <h4 className="detail-subhead">Evidence</h4>
                        <dl className="detail-grid">
                          <div>
                            <dt>Related complaints</dt>
                            <dd>{evidence?.related_complaints ?? DASH}</dd>
                          </div>
                          <div>
                            <dt>High-severity complaints</dt>
                            <dd>{evidence?.high_severity_complaints ?? DASH}</dd>
                          </div>
                          <div>
                            <dt>Infrastructure gap</dt>
                            <dd>
                              <span
                                className={`chip chip-${slug(evidence?.infrastructure_gap)}`}
                              >
                                {evidence?.infrastructure_gap || DASH}
                              </span>
                            </dd>
                          </div>
                          <div>
                            <dt>Population impact</dt>
                            <dd>
                              <span
                                className={`chip chip-${slug(evidence?.population_impact)}`}
                              >
                                {evidence?.population_impact || DASH}
                              </span>
                            </dd>
                          </div>
                          <div>
                            <dt>Investment gap</dt>
                            <dd>
                              <span className={`chip chip-${slug(evidence?.investment_gap)}`}>
                                {evidence?.investment_gap || DASH}
                              </span>
                            </dd>
                          </div>
                          <div>
                            <dt>Estimated affected population</dt>
                            <dd>
                              {item.estimated_affected_population
                                ? formatPopulation(item.estimated_affected_population)
                                : DASH}
                            </dd>
                          </div>
                        </dl>

                        <h4 className="detail-subhead">Officer decision</h4>
                        <DecisionControls
                          recommendationId={item.recommendation_id}
                          onDecided={load}
                        />
                      </div>
                    ) : null}
                  </article>
                )
              })}
            </div>
          )}

          <p className="muted small source-note">
            Recommendations support government decision-making. Final decisions
            remain with authorized government officers.
          </p>
        </>
      ) : null}
    </div>
  )
}
