import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getAuthToken } from '../api/client'
import { DEFAULT_MIN_COMPLAINTS, fetchHotspots, hasCoordinates, type Hotspot } from '../api/hotspots'
import { HotspotsMap, hotspotKey } from '../components/HotspotsMap'
import { EmptyState, ErrorState, LoadingState } from '../components/States'

const THRESHOLDS = [1, 2, 3, 5, 10]

function matches(hotspot: Hotspot, query: string): boolean {
  if (!query) return true
  const needle = query.trim().toLowerCase()
  return `${hotspot.location} ${hotspot.category}`.toLowerCase().includes(needle)
}

/** Severity counts the API did not break out, so it is never guessed at. */
function otherSeverityCount(hotspot: Hotspot): number {
  return Math.max(
    0,
    hotspot.complaint_count - hotspot.high_severity_count - hotspot.medium_severity_count,
  )
}

function slug(raw: string | null | undefined): string {
  if (!raw) return 'na'
  return raw.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
}

export function HotspotsPage() {
  const [hotspots, setHotspots] = useState<Hotspot[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const [minComplaints, setMinComplaints] = useState(DEFAULT_MIN_COMPLAINTS)
  const [query, setQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [levelFilter, setLevelFilter] = useState('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  // Ward+category of the hotspot whose marker the map should focus. Set by
  // clicking a card, and by clicking a marker, so the two views stay in step.
  const [focused, setFocused] = useState<string | null>(null)

  const load = useCallback(async (threshold: number) => {
    setLoading(true)
    setError(null)
    try {
      const token = getAuthToken()
      if (!token) {
        throw new ApiError('No active session. Please sign in again.', 401)
      }
      const data = await fetchHotspots(token, threshold)
      setHotspots(data.hotspots ?? [])
    } catch (caught) {
      setHotspots(null)
      setError(caught instanceof Error ? caught : new Error('Unexpected error'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(minComplaints)
  }, [load, minComplaints])

  // Options come from what actually came back, so a filter can never offer a
  // value the engine did not report.
  const categoryOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const hotspot of hotspots ?? []) {
      if (hotspot.category) seen.add(hotspot.category)
    }
    return [...seen].sort()
  }, [hotspots])

  const levelOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const hotspot of hotspots ?? []) {
      if (hotspot.hotspot_level) seen.add(hotspot.hotspot_level)
    }
    const order = ['High', 'Medium', 'Low']
    return [...seen].sort((a, b) => order.indexOf(a) - order.indexOf(b))
  }, [hotspots])

  const visible = useMemo(() => {
    if (!hotspots) return []
    return hotspots.filter((hotspot) => {
      if (categoryFilter !== 'all' && hotspot.category !== categoryFilter) return false
      if (levelFilter !== 'all' && hotspot.hotspot_level !== levelFilter) return false
      return matches(hotspot, query)
    })
  }, [hotspots, query, categoryFilter, levelFilter])

  const totals = useMemo(() => {
    const source = visible
    return {
      hotspots: source.length,
      complaints: source.reduce((sum, hotspot) => sum + hotspot.complaint_count, 0),
      highSeverity: source.reduce((sum, hotspot) => sum + hotspot.high_severity_count, 0),
      highPriority: source.filter(
        (hotspot) => hotspot.hotspot_level.toLowerCase() === 'high',
      ).length,
      // Only counted from the API's own coordinates. Never inferred.
      mapped: source.filter((hotspot) => hasCoordinates(hotspot)).length,
    }
  }, [visible])

  const filtersActive =
    query.trim() !== '' || categoryFilter !== 'all' || levelFilter !== 'all'

  function resetFilters() {
    setQuery('')
    setCategoryFilter('all')
    setLevelFilter('all')
  }

  const barTotal = (hotspot: Hotspot) => Math.max(1, hotspot.complaint_count)
  const pct = (part: number, hotspot: Hotspot) => (part / barTotal(hotspot)) * 100

  return (
    <div className="stack">
      <div className="hero-card">
        <div>
          <h2>Hotspots</h2>
          <p className="muted">
            Identify areas where repeated citizen concerns indicate concentrated
            infrastructure or service needs.
          </p>
          <p className="muted small">
            Map locations represent the recorded centre of each affected area.
            Locations without sufficient geographic information are shown as
            unresolved rather than being approximated.
          </p>
        </div>
        <button
          type="button"
          className="btn ghost"
          onClick={() => load(minComplaints)}
          disabled={loading}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {loading ? <LoadingState label="Loading hotspots…" /> : null}

      {!loading && error ? <ErrorState error={error} onRetry={() => load(minComplaints)} /> : null}

      {!loading && !error && hotspots && hotspots.length === 0 ? (
        <EmptyState
          title="No hotspots at this threshold"
          hint={`The engine found no ward-and-category group with ${minComplaints} or more complaints. Lower the minimum to see smaller groups.`}
        />
      ) : null}

      {!loading && !error && hotspots && hotspots.length > 0 ? (
        <>
          <div className="tiles">
            <section className="card">
              <span className="tile-label">Hotspots detected</span>
              <strong className="tile-value">{totals.hotspots}</strong>
              <span className="muted small">Groups shown after filtering</span>
            </section>
            <section className="card">
              <span className="tile-label">Complaints represented</span>
              <strong className="tile-value">{totals.complaints}</strong>
              <span className="muted small">Across the shown hotspots</span>
            </section>
            <section className="card">
              <span className="tile-label">High-severity complaints</span>
              <strong className="tile-value">{totals.highSeverity}</strong>
              <span className="muted small">Reported as High severity</span>
            </section>
            <section className="card">
              <span className="tile-label">High-priority hotspots</span>
              <strong className="tile-value">{totals.highPriority}</strong>
              <span className="muted small">Scored in the High band</span>
            </section>
            <section className="card">
              <span className="tile-label">Shown on the map</span>
              <strong className="tile-value">{totals.mapped}</strong>
              <span className="muted small">
                Of {totals.hotspots} with recorded coordinates
              </span>
            </section>
          </div>

          <HotspotsMap
            hotspots={visible}
            focusedKey={focused}
            onSelect={setFocused}
          />

          <section className="card">
            <div className="filters">
              <div className="filter grow">
                <label htmlFor="hotspot-search">Search</label>
                <input
                  id="hotspot-search"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Ward or issue category"
                />
              </div>

              <div className="filter">
                <label htmlFor="hotspot-category">Issue category</label>
                <select
                  id="hotspot-category"
                  value={categoryFilter}
                  onChange={(event) => setCategoryFilter(event.target.value)}
                >
                  <option value="all">All categories</option>
                  {categoryOptions.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter">
                <label htmlFor="hotspot-level">Priority level</label>
                <select
                  id="hotspot-level"
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
                <label htmlFor="hotspot-threshold">Minimum complaints</label>
                <select
                  id="hotspot-threshold"
                  value={String(minComplaints)}
                  onChange={(event) => setMinComplaints(Number(event.target.value))}
                >
                  {THRESHOLDS.map((threshold) => (
                    <option key={threshold} value={String(threshold)}>
                      {threshold}+
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="list-meta">
              <span className="muted small">
                Showing {visible.length} of {hotspots.length} hotspot
                {hotspots.length === 1 ? '' : 's'} (minimum {minComplaints} complaint
                {minComplaints === 1 ? '' : 's'})
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
              title="No hotspots match these filters"
              hint="Try a different ward, issue category, or priority level."
            />
          ) : (
            <div className="cards always">
              {visible.map((hotspot) => {
                const key = hotspotKey(hotspot)
                const isOpen = expanded === key
                const other = otherSeverityCount(hotspot)
                const mappable = hasCoordinates(hotspot)
                const isFocused = focused === key

                return (
                  <article
                    key={key}
                    className={`card hotspot-card${isFocused ? ' hotspot-card-focused' : ''}`}
                  >
                    <div className="hotspot-head">
                      <div>
                        <span className="tile-label">Ward / location</span>
                        <h3 className="hotspot-ward">{hotspot.location}</h3>
                        <p className="hotspot-category">{hotspot.category}</p>
                      </div>
                      <span className={`chip chip-${slug(hotspot.hotspot_level)}`}>
                        {hotspot.hotspot_level}
                      </span>
                    </div>

                    <div className="hotspot-score">
                      <strong>{hotspot.hotspot_score.toFixed(1)}</strong>
                      <span className="muted small">hotspot score</span>
                    </div>

                    <div className="hotspot-stat">
                      <span className="muted small">Complaints in this group</span>
                      <strong>{hotspot.complaint_count}</strong>
                    </div>

                    {mappable ? (
                      <button
                        type="button"
                        className="btn ghost block"
                        onClick={() => setFocused(isFocused ? null : key)}
                      >
                        {isFocused ? 'Hide on map' : 'Show on map'}
                      </button>
                    ) : (
                      <p className="unresolved-place">
                        Location unresolved &mdash; not plotted
                      </p>
                    )}

                    <div
                      className="severity-bar"
                      role="img"
                      aria-label={`${hotspot.high_severity_count} high severity, ${hotspot.medium_severity_count} medium severity, ${other} other, out of ${hotspot.complaint_count} complaints`}
                    >
                      <span
                        className="sev sev-high"
                        style={{ width: `${pct(hotspot.high_severity_count, hotspot)}%` }}
                      />
                      <span
                        className="sev sev-medium"
                        style={{ width: `${pct(hotspot.medium_severity_count, hotspot)}%` }}
                      />
                      <span className="sev sev-other" style={{ width: `${pct(other, hotspot)}%` }} />
                    </div>

                    <button
                      type="button"
                      className="btn ghost block"
                      onClick={() => setExpanded(isOpen ? null : key)}
                      aria-expanded={isOpen}
                    >
                      {isOpen ? 'Hide severity breakdown' : 'View severity breakdown'}
                    </button>

                    {isOpen ? (
                      <dl className="mini-grid">
                        <div>
                          <dt>High severity</dt>
                          <dd>{hotspot.high_severity_count}</dd>
                        </div>
                        <div>
                          <dt>Medium severity</dt>
                          <dd>{hotspot.medium_severity_count}</dd>
                        </div>
                        <div>
                          <dt>Other severity</dt>
                          <dd>{other}</dd>
                        </div>
                        <div>
                          <dt>Total complaints</dt>
                          <dd>{hotspot.complaint_count}</dd>
                        </div>
                        <div>
                          <dt>Hotspot score</dt>
                          <dd>{hotspot.hotspot_score.toFixed(1)}</dd>
                        </div>
                        <div>
                          <dt>Priority level</dt>
                          <dd>{hotspot.hotspot_level}</dd>
                        </div>
                        <div>
                          <dt>Area</dt>
                          <dd>{hotspot.area ?? 'Unknown'}</dd>
                        </div>
                        <div>
                          <dt>Issue clusters</dt>
                          <dd className="cluster-links">
                            {hotspot.cluster_ids.length
                              ? hotspot.cluster_ids.map((clusterId) => (
                                  <Link
                                    key={clusterId}
                                    className="link mono"
                                    to={`/dashboard/case/${clusterId}`}
                                  >
                                    #{clusterId}
                                  </Link>
                                ))
                              : 'None'}
                          </dd>
                        </div>
                      </dl>
                    ) : null}

                    {hotspot.cluster_ids.length ? (
                      <p className="muted small">
                        Each cluster is a group of complaints in this ward and
                        category. Opening one shows the whole decision chain for
                        that issue, from the citizen's words to the outcome.
                      </p>
                    ) : null}
                  </article>
                )
              })}
            </div>
          )}

          <p className="muted small source-note">
            Hotspots are identified from aggregated citizen complaints, severity,
            and location patterns.
          </p>
        </>
      ) : null}
    </div>
  )
}
