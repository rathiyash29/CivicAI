/**
 * Hotspots, from the existing CivicAI intelligence contract.
 *
 * Endpoint: GET /intelligence/hotspots  (backend/router.py, /intelligence prefix)
 *
 * This is the existing endpoint that powers the page -- no new endpoint was
 * added. It is a router-level officer route, so the dashboard's existing JWT is
 * all that is needed, and a citizen token is rejected with 403 by the backend.
 *
 * The payload is produced by `db_hotspots.compute_hotspots`, which groups
 * stored complaints by ward and category and scores each group.
 *
 * The response has always carried four additive fields this file previously did
 * not declare, and which the map now consumes:
 *
 *  - `area`, `latitude`, `longitude` come straight off the `locations` row for
 *    the group, untouched. They are NULLABLE by design: a complaint whose free
 *    text never resolved to a ward lands in the "Unassigned" bucket and reports
 *    null. That is a real answer, not a gap to paper over, so the UI shows an
 *    explicit unresolved state instead of inventing a point.
 *  - `cluster_ids` is the set of clusters in this (ward, category) scope. It is
 *    a list because one scope can legitimately hold several clusters, so
 *    picking one would be a guess presented to an officer as fact.
 *
 * Coordinates are ward-level centroids from a static table
 * (`data/data_loader.py`, `WARD_CENTROIDS`) -- a label position for an
 * aggregate, not a claim about where an individual report happened.
 */
import { apiRequest } from './client'

export interface Hotspot {
  location: string
  category: string
  complaint_count: number
  high_severity_count: number
  medium_severity_count: number
  hotspot_score: number
  hotspot_level: string
  /** Locality administered by the ward, or null when unknown. */
  area: string | null
  /** Ward centroid. Null when the group has no resolvable location. */
  latitude: number | null
  longitude: number | null
  /** Ids of every issue cluster inside this (ward, category) scope. */
  cluster_ids: number[]
}

/**
 * The bucket `db_hotspots` uses for a complaint with no resolvable location.
 * Matches `db_hotspots.UNASSIGNED_WARD` on the backend.
 */
export const UNASSIGNED_WARD = 'Unassigned'

/**
 * A hotspot is plottable only when it has a real point. This is the single
 * definition of that test in the UI, so a marker is never drawn for a
 * fabricated coordinate.
 */
export function hasCoordinates(hotspot: Hotspot): hotspot is Hotspot & {
  latitude: number
  longitude: number
  area: string | null
} {
  return (
    typeof hotspot.latitude === 'number' &&
    Number.isFinite(hotspot.latitude) &&
    typeof hotspot.longitude === 'number' &&
    Number.isFinite(hotspot.longitude)
  )
}

export interface HotspotsResponse {
  hotspots: Hotspot[]
}

/** The backend's own default (`db_hotspots.DEFAULT_MIN_COMPLAINTS`). */
export const DEFAULT_MIN_COMPLAINTS = 3

export function fetchHotspots(
  token: string,
  minComplaints: number = DEFAULT_MIN_COMPLAINTS,
): Promise<HotspotsResponse> {
  const query = `?min_complaints=${encodeURIComponent(String(minComplaints))}`
  return apiRequest<HotspotsResponse>(`/intelligence/hotspots${query}`, { token })
}
