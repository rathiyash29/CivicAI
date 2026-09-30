/**
 * Recommendations, from the existing CivicAI intelligence contract.
 *
 * Endpoint: GET /intelligence/recommendations  (backend/router.py, /intelligence
 * prefix). The backend generates a recommendation for every cluster that has at
 * least one real complaint, so every row returned here describes demand that
 * actually exists -- an empty cluster is not returned at all.
 *
 * Field names come from `recommendations.generate_recommendation` and must not
 * drift. `location` is the cluster's ward, which is the literal "Unassigned"
 * when the underlying complaints never resolved to a known ward; the page
 * renders that as an unresolved location rather than a place name.
 * `estimated_affected_population` is None when the ward has no demographics.
 */
import { ApiError, apiRequest } from './client'

/** The bucket a cluster falls into when its complaints have no known ward. */
export const UNRESOLVED_LOCATION = 'Unassigned'

export interface RecommendationEvidence {
  related_complaints: number
  high_severity_complaints: number
  infrastructure_gap: string
  population_impact: string
  investment_gap: string
}

/**
 * `recommendation_id` is the Recommendation row's own primary key and is what
 * the officer decision endpoints are called with
 * (`/projects/recommendations/{id}/approve`). It was missing from this response,
 * so the dashboard could read a recommendation's evidence and then have no id to
 * decide on. `cluster_id` is unchanged and is a different thing: the issue
 * cluster this recommendation was generated from, and the key the Hotspots page
 * already shows.
 */
export interface Recommendation {
  recommendation_id: number
  cluster_id: number
  location: string
  action: string
  reason: string
  evidence: RecommendationEvidence
  priority_score: number
  priority_level: string
  estimated_affected_population: number | null
}

export interface RecommendationsResponse {
  recommendations: Recommendation[]
}

/**
 * Reject a response whose recommendations are missing `recommendation_id`.
 *
 * This is not defensive padding. `recommendation_id` is the key the decision
 * endpoints are called with, and if it is absent then `undefined` becomes both
 * the React key for the expand/collapse state and the path segment of
 * `POST /projects/recommendations/{id}/approve`. Both failures are silent and
 * confusing at once: every card shares the same `undefined` key so clicking one
 * expands all of them, the card renders a bare "#", and the decision posts to
 * `/projects/recommendations/undefined/approve`, where the backend correctly
 * rejects it with 422 because the path parameter is an `int`.
 *
 * That exact combination is what a stale backend serving an older
 * `generate_recommendation` projection produces. The backend validation is
 * right and stays as it is; this turns the skew into one clear message naming
 * the missing field instead of three unrelated-looking symptoms.
 */
function assertUsable(
  payload: RecommendationsResponse,
  source: string,
): RecommendationsResponse {
  const rows = payload?.recommendations
  if (!Array.isArray(rows)) {
    throw new ApiError(
      `${source} returned no "recommendations" list. The platform and dashboard are out of step.`,
      0,
    )
  }
  const broken = rows.find(
    (row) =>
      row === null ||
      typeof row !== 'object' ||
      !Number.isInteger(row.recommendation_id) ||
      (row.recommendation_id as number) <= 0,
  )
  if (broken) {
    throw new ApiError(
      'The recommendations service could not be read because a record is missing a ' +
        'unique reference. No recommendation can be acted on. Please contact the ' +
        'system administrator.',
      0,
    )
  }
  return payload
}

export async function fetchRecommendations(
  token: string,
): Promise<RecommendationsResponse> {
  return assertUsable(
    await apiRequest<RecommendationsResponse>('/intelligence/recommendations', { token }),
    'The recommendations service',
  )
}

/**
 * The recommendation generated from one issue cluster.
 *
 * Same object as one entry of the list endpoint, so the case file and the
 * Recommendations page cannot disagree about a cluster's recommendation. The
 * backend 404s when the cluster has no complaints, since `generate_all` skips
 * those and returning one here would contradict the list it sits beside.
 */
export async function fetchRecommendationForCluster(
  token: string,
  clusterId: number,
): Promise<Recommendation> {
  return assertUsable(
    {
      recommendations: [
        await apiRequest<Recommendation>(
          `/intelligence/recommendations/${clusterId}`,
          { token },
        ),
      ],
    },
    'The recommendations service',
  ).recommendations[0]
}
