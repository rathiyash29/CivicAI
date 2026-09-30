import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, getAuthToken } from '../api/client'
import { fetchCluster, type Cluster } from '../api/cluster'
import { fetchComplaints, fetchPriorityExplanation, type Complaint, type PriorityExplanation } from '../api/complaints'
import { fetchHotspots, hasCoordinates, UNASSIGNED_WARD, type Hotspot } from '../api/hotspots'
import { fetchRecommendationForCluster, type Recommendation } from '../api/recommendations'
import {
  getProjectImpact,
  listDecisions,
  listProjects,
  type Decision,
  type Impact,
  type Project,
} from '../api/projects'
import { DecisionControls } from '../components/DecisionControls'
import { HotspotsMap } from '../components/HotspotsMap'
import { FactorTable, scoreHasDrifted } from '../components/PriorityFactors'
import { ErrorState, LoadingState } from '../components/States'

const DASH = '—'

function slug(raw: string | null | undefined): string {
  if (!raw) return 'na'
  return raw.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
}

function value(raw: string | number | null | undefined): string {
  if (raw === null || raw === undefined) return DASH
  const text = String(raw).trim()
  return text === '' ? DASH : text
}

/**
 * `created_at` columns are written with `datetime.utcnow()` and carry no zone
 * suffix, which `new Date` would read as local time and shift the displayed
 * date. Normalised to UTC first.
 */
function formatDate(raw: string | null | undefined): string {
  if (!raw) return DASH
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const date = new Date(hasZone ? raw : `${raw}Z`)
  if (Number.isNaN(date.getTime())) return DASH
  return date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatCount(raw: number | null | undefined): string {
  if (raw === null || raw === undefined) return DASH
  return new Intl.NumberFormat('en-IN').format(raw)
}

function signed(raw: number | null | undefined): string {
  if (raw === null || raw === undefined) return DASH
  return raw > 0 ? `+${raw}` : String(raw)
}

/** A cluster whose complaints never resolved to a ward is not a place. */
function isUnresolved(ward: string | null | undefined): boolean {
  return !ward || ward.trim() === UNASSIGNED_WARD
}

/** Does any complaint in the cluster carry an AI analysis? */
function hasAnyAnalysis(complaints: Complaint[]): boolean {
  return complaints.some((complaint) =>
    [
      complaint.analysis_issue_summary,
      complaint.analysis_affected_group,
      complaint.analysis_urgency,
      complaint.analysis_recommended_action,
    ].some((field) => typeof field === 'string' && field.trim() !== ''),
  )
}

type StageState = 'done' | 'pending' | 'partial'

interface Stage {
  key: string
  title: string
  state: StageState
  /** Why this stage is in the state it is, in one sentence. */
  status: string
}

/**
 * Case file for one issue cluster.
 *
 * The point of this page is that an officer can read a single civic issue from
 * the citizen's words to the measured outcome without changing pages. Every
 * number is read from an endpoint that already existed; only the cluster's own
 * category and ward needed a new read, and that is a plain row read.
 *
 * Stages are marked done, partial or pending purely from whether data came back.
 * A stage is never optimistically marked complete, and nothing on this page is
 * invented: an unresolved location, an absent analysis and an unmeasured project
 * each render as the honest "not yet" state rather than as a blank or a guess.
 *
 * AI provider provenance is the one thing that cannot be shown, because the
 * `provider_used` / `fallback_reason` written at submission are not persisted on
 * the complaint row. The AI stage says so explicitly instead of implying a
 * provider that the stored data cannot name.
 */
export function CaseThreadPage() {
  const { cluster_id: rawClusterId } = useParams()
  const navigate = useNavigate()

  const clusterId = Number(rawClusterId)

  const [cluster, setCluster] = useState<Cluster | null>(null)
  const [complaints, setComplaints] = useState<Complaint[]>([])
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null)
  const [hotspot, setHotspot] = useState<Hotspot | null>(null)
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [impact, setImpact] = useState<Impact | null>(null)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | Error | null>(null)
  /**
   * Per-stage load failures. A section that could not be read is shown as
   * unavailable with the reason, rather than silently rendering as "nothing
   * here" — those are different claims and only one of them is usually true.
   */
  const [stageErrors, setStageErrors] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    if (!Number.isInteger(clusterId) || clusterId <= 0) {
      setError(new ApiError(`"${rawClusterId}" is not a valid issue cluster id.`, 404))
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)
    setStageErrors({})

    const token = getAuthToken()
    if (!token) {
      setError(new ApiError('No active session. Please sign in again.', 401))
      setLoading(false)
      return
    }

    try {
      const loaded = await fetchCluster(token, clusterId)
      setCluster(loaded)
    } catch (caught) {
      setCluster(null)
      setError(caught instanceof Error ? caught : new Error('Unexpected error'))
      setLoading(false)
      return
    }

    // Second wave: everything that is keyed on the cluster alone. Settled
    // individually so one failing endpoint cannot blank the whole case file.
    const [complaintsResult, recommendationResult, hotspotsResult] =
      await Promise.allSettled([
        fetchComplaints(token),
        fetchRecommendationForCluster(token, clusterId),
        fetchHotspots(token, 1),
      ])

    const failures: Record<string, string> = {}

    if (complaintsResult.status === 'fulfilled') {
      // Filtered by the cluster endpoint's own member list, so this cannot
      // drift from the count printed in the header.
      setComplaints(
        (complaintsResult.value.complaints ?? []).filter(
          (complaint) => complaint.cluster_id === clusterId,
        ),
      )
    } else {
      setComplaints([])
      failures.complaints = messageOf(complaintsResult.reason)
    }

    if (recommendationResult.status === 'fulfilled') {
      setRecommendation(recommendationResult.value)
    } else {
      setRecommendation(null)
      // 404 here is meaningful, not an error: the engine declines to produce a
      // recommendation for a cluster with no complaints behind it.
      failures.recommendation = messageOf(recommendationResult.reason)
    }

    if (hotspotsResult.status === 'fulfilled') {
      setHotspot(
        (hotspotsResult.value.hotspots ?? []).find((item) =>
          item.cluster_ids.includes(clusterId),
        ) ?? null,
      )
    } else {
      setHotspot(null)
      failures.hotspot = messageOf(hotspotsResult.reason)
    }

    // Third wave: the decision chain, which only exists once there is a
    // recommendation to decide on.
    const recommendationId = recommendationResult.status === 'fulfilled'
      ? recommendationResult.value.recommendation_id
      : null

    if (recommendationId === null) {
      setDecisions([])
      setProject(null)
      setImpact(null)
    } else {
      const [decisionsResult, projectsResult] = await Promise.allSettled([
        listDecisions(token, recommendationId),
        listProjects(token),
      ])

      if (decisionsResult.status === 'fulfilled') {
        setDecisions(decisionsResult.value ?? [])
      } else {
        setDecisions([])
        failures.decisions = messageOf(decisionsResult.reason)
      }

      let matched: Project | null = null
      if (projectsResult.status === 'fulfilled') {
        matched =
          (projectsResult.value ?? []).find(
            (item) => item.recommendation_id === recommendationId,
          ) ?? null
      } else {
        failures.projects = messageOf(projectsResult.reason)
      }
      setProject(matched)

      if (matched) {
        // A 404 from the impact route means "no record", which is the single
        // most important distinction on this page. It is caught, not thrown.
        try {
          setImpact(await getProjectImpact(token, matched.id))
        } catch (caught) {
          setImpact(null)
          if (caught instanceof ApiError && caught.status !== 404) {
            failures.impact = caught.message
          }
        }
      } else {
        setImpact(null)
      }
    }

    setStageErrors(failures)
    setLoading(false)
  }, [clusterId, rawClusterId])

  useEffect(() => {
    load()
  }, [load])

  /** Re-read the chain after a decision, without tearing down the page. */
  const refreshChain = useCallback(async () => {
    const token = getAuthToken()
    if (!token || !recommendation) return
    try {
      setDecisions((await listDecisions(token, recommendation.recommendation_id)) ?? [])
      const projects = await listProjects(token)
      const matched =
        projects.find((item) => item.recommendation_id === recommendation.recommendation_id) ??
        null
      setProject(matched)
      if (matched) {
        try {
          setImpact(await getProjectImpact(token, matched.id))
        } catch {
          setImpact(null)
        }
      } else {
        setImpact(null)
      }
    } catch {
      // A failed refresh leaves the last known chain on screen rather than
      // blanking it; the officer can re-request the case file.
    }
  }, [recommendation])

  const analysed = useMemo(() => hasAnyAnalysis(complaints), [complaints])
  const scoredComplaints = useMemo(
    () => complaints.filter((c) => typeof c.priority_score === 'number').length,
    [complaints],
  )
  const latestDecision = decisions.length ? decisions[decisions.length - 1] : null
  const rejected = latestDecision?.decision === 'Rejected'

  const stages: Stage[] = cluster
    ? [
        {
          key: 'complaints',
          title: 'Citizen complaints',
          state: complaints.length ? (stageErrors.complaints ? 'partial' : 'done') : 'pending',
          status: stageErrors.complaints
            ? 'Could not be loaded'
            : `${complaints.length} complaint${complaints.length === 1 ? '' : 's'} grouped into this cluster`,
        },
        {
          key: 'ai',
          title: 'AI understanding',
          state: analysed ? 'done' : 'pending',
          status: analysed
            ? 'Analysis recorded on submission'
            : 'No AI analysis recorded for these complaints',
        },
        {
          key: 'cluster',
          title: 'Issue cluster',
          state: 'done',
          status: `Cluster #${cluster.cluster_id}`,
        },
        {
          key: 'geo',
          title: 'Hotspot and location',
          state: hotspot ? 'done' : isUnresolved(cluster.ward) ? 'pending' : 'partial',
          status: isUnresolved(cluster.ward)
            ? 'No ward resolved for these complaints'
            : hotspot
              ? 'Inside a detected hotspot'
              : 'Ward known, below the hotspot threshold',
        },
        {
          key: 'priority',
          title: 'Priority and evidence',
          state: scoredComplaints ? 'done' : 'pending',
          status: scoredComplaints
            ? `${scoredComplaints} of ${complaints.length} scored`
            : 'Not scored',
        },
        {
          key: 'recommendation',
          title: 'Government recommendation',
          state: recommendation ? 'done' : 'pending',
          status: recommendation
            ? `Recommendation #${recommendation.recommendation_id}`
            : 'No recommendation generated',
        },
        {
          key: 'decision',
          title: 'Officer decision',
          state: latestDecision ? 'done' : 'pending',
          status: latestDecision
            ? `${latestDecision.decision} · ${formatDate(latestDecision.created_at)}`
            : 'Awaiting an officer decision',
        },
        {
          key: 'project',
          title: 'Project',
          state: project ? 'done' : latestDecision ? 'pending' : 'pending',
          status: project
            ? `Project #${project.id} · ${project.status}`
            : rejected
              ? 'No project — recommendation rejected'
              : 'No project created yet',
        },
        {
          key: 'impact',
          title: 'Impact',
          state: impact ? 'done' : 'pending',
          status: impact
            ? 'Outcome measured'
            : project
              ? 'Impact not yet measured'
              : 'Not applicable until a project is completed',
        },
      ]
    : []

  const stageState = (key: string): StageState =>
    stages.find((stage) => stage.key === key)?.state ?? 'pending'

  if (loading) {
    return <LoadingState label="Loading case file…" />
  }

  if (error || !cluster) {
    return (
      <div className="stack">
        <ErrorState error={error} onRetry={load} />
        <Link className="btn ghost" to="/dashboard/recommendations">
          Back to Recommendations
        </Link>
      </div>
    )
  }

  return (
    <div className="stack">
      {/* ---- header ---------------------------------------------------- */}
      <div className="hero-card">
        <div>
          <span className="tile-label">Case file</span>
          <h2>
            {isUnresolved(cluster.ward) ? 'Location unresolved' : cluster.ward}
            {cluster.category ? ` · ${cluster.category}` : ''}
          </h2>
          <p className="muted">
            Issue cluster <span className="mono">#{cluster.cluster_id}</span>
            {cluster.label ? ` — ${cluster.label}` : ''} ·{' '}
            {formatCount(cluster.complaint_count)} citizen complaint
            {cluster.complaint_count === 1 ? '' : 's'} · opened{' '}
            {formatDate(cluster.created_at)}
          </p>
        </div>
        <div className="decision-row">
          <button
            type="button"
            className="btn ghost"
            onClick={() => navigate('/dashboard')}
          >
            Back to Dashboard
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => navigate('/dashboard/recommendations')}
          >
            Back to Recommendations
          </button>
        </div>
      </div>

      {/* ---- stage rail ------------------------------------------------ */}
      <section className="card">
        <h2 className="card-title">Decision chain</h2>
        <ol className="thread-rail">
          {stages.map((stage, index) => (
            <li
              key={stage.key}
              className={`thread-step thread-step-${stage.state}`}
            >
              <span className="thread-marker" aria-hidden="true">
                {stage.state === 'done' ? '✓' : index + 1}
              </span>
              <span className="thread-step-body">
                <span className="thread-step-title">{stage.title}</span>
                <span className="muted small">{stage.status}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="muted small">
          A tick means the stage has real records behind it. An unticked stage
          has none yet, which is a different thing from a stage that failed to
          load.
        </p>
      </section>

      <div className="thread-body">
        {/* ---- 1 & 2. citizen evidence --------------------------------- */}
        <ThreadSection
          title="Citizen complaints"
          state={stageState('complaints')}
        >
          {stageErrors.complaints ? (
            <p className="muted small">Could not load complaints: {stageErrors.complaints}</p>
          ) : complaints.length === 0 ? (
            <p className="muted small">
              No complaints are currently grouped into this cluster. The cluster
              row survives, but there is no citizen evidence behind it.
            </p>
          ) : (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Complaint</th>
                      <th>Location</th>
                      <th>Severity</th>
                      <th className="num">Priority</th>
                      <th>Status</th>
                      <th>AI summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {complaints.map((complaint) => (
                      <tr key={complaint.complaint_id}>
                        <td className="mono">
                          <Link
                            className="link mono"
                            to={`/dashboard/complaints?cluster=${cluster.cluster_id}`}
                          >
                            {complaint.complaint_id}
                          </Link>
                        </td>
                        <td>{value(complaint.location)}</td>
                        <td>
                          <span className={`chip chip-${slug(complaint.severity)}`}>
                            {value(complaint.severity)}
                          </span>
                        </td>
                        <td className="num">
                          {typeof complaint.priority_score === 'number'
                            ? complaint.priority_score.toFixed(1)
                            : DASH}
                        </td>
                        <td>{value(complaint.status)}</td>
                        <td>
                          {complaint.analysis_issue_summary ? (
                            <span className="muted small">
                              {complaint.analysis_issue_summary}
                            </span>
                          ) : (
                            <span className="muted small">{DASH}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                {analysed
                  ? 'AI summaries were recorded on these complaints at submission.'
                  : 'No AI analysis is recorded on these complaints. Nothing is shown in the AI stage below rather than a generated summary.'}
              </p>
            </>
          )}
        </ThreadSection>

        {/* ---- AI understanding ---------------------------------------- */}
        <ThreadSection title="AI understanding" state={stageState('ai')}>
          {analysed ? (
            <>
              <p className="muted small">
                Recorded on each complaint when it was submitted — the system's
                reading of the citizen's text, not an officer's entry.
              </p>
              <dl className="detail-grid">
                <div>
                  <dt>Most common urgency</dt>
                  <dd>
                    {modeOf(complaints.map((c) => c.analysis_urgency)) ?? DASH}
                  </dd>
                </div>
                <div>
                  <dt>Affected groups</dt>
                  <dd>
                    {uniqueOrDash(complaints.map((c) => c.analysis_affected_group))}
                  </dd>
                </div>
              </dl>
              <h4 className="detail-subhead">Issue summaries</h4>
              <ul className="thread-list">
                {complaints
                  .filter((c) => c.analysis_issue_summary)
                  .map((c) => (
                    <li key={c.complaint_id}>
                      <span className="mono">{c.complaint_id}</span> —{' '}
                      {c.analysis_issue_summary}
                    </li>
                  ))}
              </ul>
              <h4 className="detail-subhead">Recommended actions</h4>
              <ul className="thread-list">
                {complaints
                  .filter((c) => c.analysis_recommended_action)
                  .map((c) => (
                    <li key={c.complaint_id}>
                      <span className="mono">{c.complaint_id}</span> —{' '}
                      {c.analysis_recommended_action}
                    </li>
                  ))}
              </ul>
              <p className="muted small">
                Which provider answered — Gemini or the offline fallback — is not
                stored on the complaint, so it cannot be reported here. It is
                recorded only in the response to the citizen who submitted, not
                persisted.
              </p>
            </>
          ) : (
            <p className="muted small">
              No AI analysis was recorded for the complaints in this cluster.
            </p>
          )}
        </ThreadSection>

        {/* ---- 3. cluster ------------------------------------------------ */}
        <ThreadSection title="Issue cluster" state={stageState('cluster')}>
          <dl className="detail-grid">
            <div>
              <dt>Cluster id</dt>
              <dd className="mono">#{cluster.cluster_id}</dd>
            </div>
            <div>
              <dt>Label</dt>
              <dd>{value(cluster.label)}</dd>
            </div>
            <div>
              <dt>Category</dt>
              <dd>{value(cluster.category)}</dd>
            </div>
            <div>
              <dt>Ward</dt>
              <dd>
                {isUnresolved(cluster.ward) ? (
                  <span className="unresolved-place">Location unresolved</span>
                ) : (
                  cluster.ward
                )}
              </dd>
            </div>
            <div>
              <dt>Complaints</dt>
              <dd>{formatCount(cluster.complaint_count)}</dd>
            </div>
            <div>
              <dt>Opened</dt>
              <dd>{formatDate(cluster.created_at)}</dd>
            </div>
          </dl>
        </ThreadSection>

        {/* ---- 4. geography --------------------------------------------- */}
        <ThreadSection title="Hotspot and location" state={stageState('geo')}>
          {isUnresolved(cluster.ward) ? (
            <p className="muted small">
              These complaints carry no ward that resolved to a known location.
              No point is plotted, because there is no recorded position to plot
              one at.
            </p>
          ) : !hotspot ? (
            <p className="muted small">
              This cluster sits in a known ward but did not meet the hotspot
              threshold at the default complaint count, so no hotspot is
              reported for it. Lower the threshold on the{' '}
              <Link className="link" to="/dashboard/hotspots">
                Hotspots page
              </Link>{' '}
              to see smaller groups.
            </p>
          ) : (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Hotspot score</dt>
                  <dd>{hotspot.hotspot_score.toFixed(1)}</dd>
                </div>
                <div>
                  <dt>Level</dt>
                  <dd>
                    <span className={`chip chip-${slug(hotspot.hotspot_level)}`}>
                      {hotspot.hotspot_level}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Complaints in scope</dt>
                  <dd>{formatCount(hotspot.complaint_count)}</dd>
                </div>
                <div>
                  <dt>High severity</dt>
                  <dd>{formatCount(hotspot.high_severity_count)}</dd>
                </div>
                <div>
                  <dt>Area</dt>
                  <dd>{value(hotspot.area)}</dd>
                </div>
                <div>
                  <dt>Coordinates</dt>
                  <dd className="mono">
                    {hasCoordinates(hotspot)
                      ? `${hotspot.latitude.toFixed(4)}, ${hotspot.longitude.toFixed(4)}`
                      : DASH}
                  </dd>
                </div>
              </dl>
              <HotspotsMap
                hotspots={[hotspot]}
                focusedKey={`${hotspot.location}|${hotspot.category}`}
                onSelect={() => undefined}
              />
              <p className="muted small">
                The pin is the ward centroid from the{' '}
                <code>locations</code> row — a label position for the aggregate,
                not a claim about where an individual report happened.
              </p>
            </>
          )}
        </ThreadSection>

        {/* ---- 5. priority ---------------------------------------------- */}
        <ThreadSection title="Priority and evidence" state={stageState('priority')}>
          {recommendation ? (
            <dl className="detail-grid">
              <div>
                <dt>Cluster priority score</dt>
                <dd>{recommendation.priority_score.toFixed(1)}</dd>
              </div>
              <div>
                <dt>Level</dt>
                <dd>
                  <span className={`chip chip-${slug(recommendation.priority_level)}`}>
                    {recommendation.priority_level}
                  </span>
                </dd>
              </div>
            </dl>
          ) : null}
          <p className="muted small">
            The priority engine scores each complaint individually; the score
            above is the mean across this cluster's complaints, which is what the
            recommendation engine uses. Open any complaint to see its own five
            weighted factors.
          </p>
          {complaints.length ? (
            <ul className="thread-list">
              {complaints.map((complaint) => (
                <ComplaintFactors
                  key={complaint.complaint_id}
                  complaint={complaint}
                />
              ))}
            </ul>
          ) : (
            <p className="muted small">No complaints to explain.</p>
          )}
        </ThreadSection>

        {/* ---- 6. recommendation ----------------------------------------- */}
        <ThreadSection title="Government recommendation" state={stageState('recommendation')}>
          {stageErrors.recommendation && recommendation === null ? (
            <p className="muted small">
              No recommendation: {stageErrors.recommendation}
            </p>
          ) : !recommendation ? (
            <p className="muted small">
              The engine produced no recommendation for this cluster. One is only
              generated for a cluster with real complaints behind it.
            </p>
          ) : (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Recommendation</dt>
                  <dd className="mono">#{recommendation.recommendation_id}</dd>
                </div>
                <div>
                  <dt>Cluster</dt>
                  <dd className="mono">
                    <Link
                      className="link mono"
                      to={`/dashboard/recommendations?cluster=${recommendation.cluster_id}`}
                    >
                      #{recommendation.cluster_id}
                    </Link>
                  </dd>
                </div>
                <div>
                  <dt>Estimated affected population</dt>
                  <dd>{formatCount(recommendation.estimated_affected_population)}</dd>
                </div>
              </dl>
              <h4 className="detail-subhead">Recommended action</h4>
              <p className="recommendation-action">{recommendation.action}</p>
              <h4 className="detail-subhead">Reason</h4>
              <p className="recommendation-reason">{recommendation.reason}</p>
              <h4 className="detail-subhead">Evidence</h4>
              <dl className="detail-grid">
                <div>
                  <dt>Related complaints</dt>
                  <dd>{recommendation.evidence.related_complaints}</dd>
                </div>
                <div>
                  <dt>High-severity complaints</dt>
                  <dd>{recommendation.evidence.high_severity_complaints}</dd>
                </div>
                <div>
                  <dt>Infrastructure gap</dt>
                  <dd>
                    <span
                      className={`chip chip-${slug(recommendation.evidence.infrastructure_gap)}`}
                    >
                      {recommendation.evidence.infrastructure_gap}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Population impact</dt>
                  <dd>
                    <span
                      className={`chip chip-${slug(recommendation.evidence.population_impact)}`}
                    >
                      {recommendation.evidence.population_impact}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Investment gap</dt>
                  <dd>
                    <span className={`chip chip-${slug(recommendation.evidence.investment_gap)}`}>
                      {recommendation.evidence.investment_gap}
                    </span>
                  </dd>
                </div>
              </dl>
              <p className="muted small">
                These are the engine's own band labels. The raw factor numbers
                behind them are per complaint, in the priority stage above.
              </p>
            </>
          )}
        </ThreadSection>

        {/* ---- 7. decision ---------------------------------------------- */}
        <ThreadSection title="Officer decision" state={stageState('decision')}>
          {!recommendation ? (
            <p className="muted small">
              There is nothing to decide on until a recommendation exists.
            </p>
          ) : latestDecision ? (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Decision</dt>
                  <dd>
                    <span className={`chip chip-${slug(latestDecision.decision)}`}>
                      {latestDecision.decision}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Officer</dt>
                  <dd>
                    {latestDecision.officer?.name ?? latestDecision.officer?.email ?? DASH}
                  </dd>
                </div>
                <div>
                  <dt>Recorded</dt>
                  <dd>{formatDate(latestDecision.created_at)}</dd>
                </div>
                <div>
                  <dt>Project</dt>
                  <dd className="mono">
                    {latestDecision.project_id ? `#${latestDecision.project_id}` : DASH}
                  </dd>
                </div>
              </dl>
              {latestDecision.reason ? (
                <p className="recommendation-reason">{latestDecision.reason}</p>
              ) : null}
              <h4 className="detail-subhead">Decision history</h4>
              <ul className="decision-history">
                {decisions.map((decision) => (
                  <li key={decision.id} className="decision-entry">
                    <span className={`chip chip-${slug(decision.decision)}`}>
                      {decision.decision}
                    </span>
                    <span className="muted small">
                      {decision.officer?.name ?? decision.officer?.email ?? 'Unknown officer'}{' '}
                      · {formatDate(decision.created_at)}
                    </span>
                    {decision.reason ? (
                      <span className="decision-reason">{decision.reason}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
              {stageErrors.decisions ? (
                <p className="muted small">
                  Decision history could not be read: {stageErrors.decisions}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <p className="muted small">
                No decision has been recorded on this recommendation yet.
              </p>
              <DecisionControls
                recommendationId={recommendation.recommendation_id}
                onDecided={refreshChain}
              />
            </>
          )}
        </ThreadSection>

        {/* ---- 8. project ------------------------------------------------ */}
        <ThreadSection title="Project" state={stageState('project')}>
          {stageErrors.projects ? (
            <p className="muted small">Project could not be read: {stageErrors.projects}</p>
          ) : !project ? (
            <p className="muted small">
              {rejected
                ? 'No project created. The recommendation was rejected, which is a recorded outcome rather than a missing step.'
                : 'No project created yet. A project appears when an officer approves or modifies this recommendation.'}
            </p>
          ) : (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Project</dt>
                  <dd className="mono">#{project.id}</dd>
                </div>
                <div>
                  <dt>Title</dt>
                  <dd>{value(project.title)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>
                    <span className={`chip chip-${slug(project.status)}`}>
                      {project.status}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Department</dt>
                  <dd>
                    <span className="muted small">{DASH} not tracked</span>
                  </dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{formatDate(project.created_at)}</dd>
                </div>
                <div>
                  <dt>Officer</dt>
                  <dd>{project.officer?.name ?? project.officer?.email ?? DASH}</dd>
                </div>
              </dl>
              {project.description ? (
                <p className="recommendation-reason">{project.description}</p>
              ) : null}
              <p className="muted small">
                Related complaints: {formatCount(project.related_complaints)} ·{' '}
                <Link className="link" to="/dashboard/projects">
                  Open the Projects page
                </Link>
              </p>
            </>
          )}
        </ThreadSection>

        {/* ---- 9. impact ------------------------------------------------- */}
        <ThreadSection title="Impact" state={stageState('impact')}>
          {stageErrors.impact ? (
            <p className="muted small">Impact could not be read: {stageErrors.impact}</p>
          ) : !impact ? (
            <p className="muted small">
              {project
                ? 'Impact not yet measured. A measurement can only be recorded once the project reaches Completed.'
                : 'Impact not applicable yet. There is no completed project on this recommendation.'}
            </p>
          ) : (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Period</dt>
                  <dd>
                    {formatDate(impact.measurement_period_start)}
                    {impact.measurement_period_end
                      ? ` – ${formatDate(impact.measurement_period_end)}`
                      : ''}
                  </dd>
                </div>
                <div>
                  <dt>Recorded by</dt>
                  <dd>{impact.recorded_by?.name ?? impact.recorded_by?.email ?? DASH}</dd>
                </div>
                <div>
                  <dt>Complaints before</dt>
                  <dd>{formatCount(impact.before_complaint_count)}</dd>
                </div>
                <div>
                  <dt>Complaints after</dt>
                  <dd>{formatCount(impact.after_complaint_count)}</dd>
                </div>
                <div>
                  <dt>Complaints resolved</dt>
                  <dd>{formatCount(impact.complaints_resolved)}</dd>
                </div>
                <div>
                  <dt>Avg severity before</dt>
                  <dd>{formatCount(impact.before_avg_severity_score)}</dd>
                </div>
                <div>
                  <dt>Avg severity after</dt>
                  <dd>{formatCount(impact.after_avg_severity_score)}</dd>
                </div>
                <div>
                  <dt>Avg priority before</dt>
                  <dd>{formatCount(impact.before_avg_priority_score)}</dd>
                </div>
                <div>
                  <dt>Avg priority after</dt>
                  <dd>{formatCount(impact.after_avg_priority_score)}</dd>
                </div>
              </dl>
              <h4 className="detail-subhead">Observed change</h4>
              <dl className="detail-grid">
                <div>
                  <dt>Complaint change</dt>
                  <dd>{signed(impact.observed_change.complaint_change)}</dd>
                </div>
                <div>
                  <dt>Change %</dt>
                  <dd>{formatCount(impact.observed_change.complaint_change_percent)}</dd>
                </div>
                <div>
                  <dt>Severity change</dt>
                  <dd>{formatCount(impact.observed_change.severity_change)}</dd>
                </div>
                <div>
                  <dt>Priority change</dt>
                  <dd>{formatCount(impact.observed_change.priority_change)}</dd>
                </div>
              </dl>
              {impact.officer_notes ? (
                <p className="recommendation-reason">{impact.officer_notes}</p>
              ) : null}
              <p className="muted small">
                Observed changes only. They do not imply the project caused them.
              </p>
            </>
          )}
        </ThreadSection>
      </div>
    </div>
  )
}

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : 'Unexpected error'
}

/** Most common non-empty value, or null when there is nothing to report. */
function modeOf(values: Array<string | null | undefined>): string | null {
  const counts = new Map<string, number>()
  for (const item of values) {
    const text = (item ?? '').trim()
    if (!text) continue
    counts.set(text, (counts.get(text) ?? 0) + 1)
  }
  let best: string | null = null
  let bestCount = 0
  for (const [text, count] of counts) {
    if (count > bestCount) {
      best = text
      bestCount = count
    }
  }
  return best
}

function uniqueOrDash(values: Array<string | null | undefined>): string {
  const seen = [
    ...new Set(
      values.map((item) => (item ?? '').trim()).filter((text) => text !== ''),
    ),
  ]
  return seen.length ? seen.join(', ') : DASH
}

function ThreadSection({
  title,
  state,
  children,
}: {
  title: string
  state: StageState
  children: React.ReactNode
}) {
  return (
    <section className={`card thread-section thread-section-${state}`}>
      <div className="thread-section-head">
        <h2 className="card-title">{title}</h2>
        <span className={`chip chip-${state === 'done' ? 'completed' : 'status-changed'}`}>
          {state === 'done' ? 'Recorded' : state === 'partial' ? 'Partial' : 'Pending'}
        </span>
      </div>
      {children}
    </section>
  )
}

/**
 * One complaint's five factors, fetched the first time it is opened.
 *
 * The factors are per complaint, so loading them for a 12-complaint cluster up
 * front would be 12 requests nobody asked for. The complaint's own score is
 * already on the row, so the collapsed line is never empty.
 */
function ComplaintFactors({ complaint }: { complaint: Complaint }) {
  const [open, setOpen] = useState(false)
  const [explanation, setExplanation] = useState<PriorityExplanation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const toggle = useCallback(async () => {
    const next = !open
    setOpen(next)
    if (!next || explanation || loading) return

    const token = getAuthToken()
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      setExplanation(await fetchPriorityExplanation(token, complaint.complaint_id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load factors')
    } finally {
      setLoading(false)
    }
  }, [complaint.complaint_id, explanation, loading, open])

  return (
    <li className="thread-factor">
      <div className="factor-label">
        <button type="button" className="btn ghost" onClick={toggle}>
          {open ? 'Hide factors' : 'Why this score?'}
        </button>
        <span className="mono">{complaint.complaint_id}</span>
        <span className="muted small">
          {typeof complaint.priority_score === 'number'
            ? `${complaint.priority_score.toFixed(1)} · ${complaint.priority_level ?? 'unscored'}`
            : 'Not scored'}
        </span>
      </div>
      {open ? (
        loading ? (
          <p className="muted small">Loading factors…</p>
        ) : error ? (
          <p className="muted small">
            Factors unavailable: {error}. The score above is the stored value and
            is unaffected.
          </p>
        ) : explanation ? (
          <>
            {explanation.stored_score === null ? (
              <p className="muted small">
                No score is stored for this complaint. The factors below are what
                the engine would produce now; nothing is shown as a stored value.
              </p>
            ) : scoreHasDrifted(explanation) ? (
              <p className="muted small">
                These factors now add up to {explanation.current_score.toFixed(1)},
                but the stored score is {explanation.stored_score?.toFixed(1)}. The
                ward data has changed since this complaint was last scored.
              </p>
            ) : null}
            <FactorTable explanation={explanation} />
          </>
        ) : null
      ) : null}
    </li>
  )
}
