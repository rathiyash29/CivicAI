import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getAuthToken } from '../api/client'
import { fetchStats, type IntelligenceStats } from '../api/intelligence'
import { ApiError } from '../api/client'
import { Card, EmptyState, ErrorState, LoadingState } from '../components/States'

interface StatTile {
  key: keyof IntelligenceStats
  label: string
  hint: string
}

const TILES: StatTile[] = [
  { key: 'complaints', label: 'Citizen complaints', hint: 'Rows in the complaints table' },
  { key: 'scored_complaints', label: 'Scored complaints', hint: 'Priority score computed' },
  { key: 'issue_clusters', label: 'Issue clusters', hint: 'Grouped complaint themes' },
  { key: 'recommendations', label: 'Recommendations', hint: 'Engine-generated proposals' },
  { key: 'locations', label: 'Locations', hint: 'Distinct civic locations' },
  { key: 'infrastructure', label: 'Infrastructure', hint: 'Infrastructure assets tracked' },
  { key: 'demographics', label: 'Demographics', hint: 'Population records linked' },
  { key: 'investments', label: 'Investments', hint: 'Investment records' },
]

/**
 * One stage of the pipeline, in the order the data actually flows.
 *
 * `value` is read from the stats endpoint rather than derived here, so each tile
 * is the same number the page it links to would show. `of` names the stage the
 * count is a subset of, which is what makes the funnel readable: 3 clusters out
 * of 15 complaints, 2 projects out of 9 recommendations.
 *
 * `caption` states what the count means, including when it is a derived count
 * rather than a table row -- an "AI analysed" number is a column on the
 * complaint row, not a separate table, and saying so is more useful than
 * implying a stage that does not exist.
 */
interface PipelineStage {
  key: string
  label: string
  value: number
  /** Stat key backing this number. */
  stat: keyof IntelligenceStats
  of?: { label: string; value: number }
  caption: string
  to: string
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('en-IN').format(value)
}

export function OverviewPage() {
  const { user } = useAuth()
  const [stats, setStats] = useState<IntelligenceStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = getAuthToken()
      if (!token) {
        throw new ApiError('No active session. Please sign in again.', 401)
      }
      setStats(await fetchStats(token))
    } catch (caught) {
      setStats(null)
      setError(caught instanceof Error ? caught : new Error('Unexpected error'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const totalRecords = stats
    ? TILES.reduce((sum, tile) => sum + (stats[tile.key] ?? 0), 0)
    : 0
  const isEmpty = stats !== null && totalRecords === 0

  /**
   * The pipeline, in data-flow order. Assembled only once stats have arrived so
   * every number is a real response value rather than a placeholder zero.
   */
  const stages: PipelineStage[] = stats
    ? [
        {
          key: 'complaints',
          label: 'Citizen complaints',
          value: stats.complaints,
          stat: 'complaints',
          caption: 'Submitted by citizens and stored.',
          to: '/dashboard/complaints',
        },
        {
          key: 'analysis',
          label: 'AI understanding',
          value: stats.analysed_complaints,
          stat: 'analysed_complaints',
          of: { label: 'complaints', value: stats.complaints },
          caption: 'Complaints with an AI issue summary written at submission.',
          to: '/dashboard/complaints',
        },
        {
          key: 'clusters',
          label: 'Issue clusters',
          value: stats.issue_clusters,
          stat: 'issue_clusters',
          of: { label: 'complaints', value: stats.complaints },
          caption: 'Similar complaints grouped by ward and category.',
          to: '/dashboard/hotspots',
        },
        {
          key: 'hotspots',
          label: 'Hotspots',
          value: stats.hotspots,
          stat: 'hotspots',
          of: { label: 'clusters', value: stats.issue_clusters },
          caption: 'Ward and category groups past the complaint threshold.',
          to: '/dashboard/hotspots',
        },
        {
          key: 'recommendations',
          label: 'Recommendations',
          value: stats.recommendations,
          stat: 'recommendations',
          of: { label: 'clusters', value: stats.issue_clusters },
          caption: 'Proposed actions the engine generated per cluster.',
          to: '/dashboard/recommendations',
        },
        {
          key: 'projects',
          label: 'Projects',
          value: stats.projects,
          stat: 'projects',
          of: { label: 'recommendations', value: stats.recommendations },
          caption: 'Created by an officer approving or modifying a recommendation.',
          to: '/dashboard/projects',
        },
        {
          key: 'impact',
          label: 'Measured impact',
          value: stats.measured_impact,
          stat: 'measured_impact',
          of: { label: 'completed projects', value: stats.completed_projects },
          caption: 'Completed projects with a recorded before/after measurement.',
          to: '/dashboard/impact',
        },
      ]
    : []

  return (
    <div className="stack">
      <div className="hero-card">
        <div>
          <h2>
            Welcome, {user?.full_name?.split(' ')[0] ?? 'Officer'}
          </h2>
          <p className="muted">
            Monitor citizen needs, AI-generated insights, development priorities,
            and project outcomes across the CivicAI decision-support pipeline.
          </p>
        </div>
        <button type="button" className="btn ghost" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {loading ? <LoadingState label="Loading pipeline statistics…" /> : null}

      {!loading && error ? <ErrorState error={error} onRetry={load} /> : null}

      {!loading && !error && isEmpty ? (
        <EmptyState
          title="No data in the engine yet"
          hint="No records are currently available. Overview figures appear as citizen complaints are submitted and reviewed."
        />
      ) : null}

      {!loading && !error && stats && !isEmpty ? (
        <>
          <Card title="The pipeline, end to end">
            <p className="muted small">
              Track how citizen feedback moves from reported needs to
              evidence-based priorities, government decisions, project execution,
              and impact measurement.
            </p>
            <ol className="pipeline">
              {stages.map((stage, index) => (
                <li key={stage.key} className="pipeline-stage">
                  <span className="pipeline-index" aria-hidden="true">
                    {index + 1}
                  </span>
                  <Link to={stage.to} className="pipeline-body">
                    <span className="pipeline-label">{stage.label}</span>
                    <strong className="pipeline-value">{formatCount(stage.value)}</strong>
                    <span className="muted small">
                      {stage.of
                        ? `of ${formatCount(stage.of.value)} ${stage.of.label} · `
                        : ''}
                      {stage.caption}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </Card>

          <div className="tiles">
            {TILES.map((tile) => (
              <Card key={tile.key}>
                <span className="tile-label">{tile.label}</span>
                <strong className="tile-value">{formatCount(stats[tile.key] ?? 0)}</strong>
                <span className="muted small">{tile.hint}</span>
              </Card>
            ))}
          </div>

          <Card title="Pipeline coverage">
            <p className="muted">
              {formatCount(stats.scored_complaints ?? 0)} of{' '}
              {formatCount(stats.complaints ?? 0)} complaints have a priority
              score
              {stats.complaints
                ? ` (${Math.round(((stats.scored_complaints ?? 0) / stats.complaints) * 100)}%).`
                : '.'}
            </p>
            <div className="meter" role="img" aria-label="Share of scored complaints">
              <div
                className="meter-fill"
                style={{
                  width: `${
                    stats.complaints
                      ? Math.min(100, ((stats.scored_complaints ?? 0) / stats.complaints) * 100)
                      : 0
                  }%`,
                }}
              />
            </div>
            <p className="muted small">
              {formatCount(stats.projects)} project
              {stats.projects === 1 ? '' : 's'} exist, of which{' '}
              {formatCount(stats.completed_projects)} have completed and{' '}
              {formatCount(stats.measured_impact)} have a recorded impact
              measurement.
            </p>
          </Card>
        </>
      ) : null}

      <p className="muted small source-note">
        Data is powered by the CivicAI intelligence engine.
      </p>
    </div>
  )
}
