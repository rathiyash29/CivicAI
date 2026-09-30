/**
 * A single issue cluster, as the head of a case file.
 *
 * Endpoint: GET /intelligence/clusters/{cluster_id}  (backend/router.py,
 * /intelligence prefix, officer-only like every other intelligence route).
 *
 * This exists because a cluster's `category` and `ward` were reachable from
 * nowhere else. They are plain string columns with no foreign key: a hotspot
 * lists cluster *ids* but not their category, and a recommendation carries the
 * ward but not the category. Without this the case file would have had to infer
 * the category from the recommended action text, which is a guess.
 *
 * Everything else the case view needs — complaints, recommendation, hotspot,
 * decisions, project, impact, priority factors — is read from the endpoints that
 * already existed. This adds no business logic: it is a read of the cluster row
 * plus an ordered list of member ids.
 */
import { apiRequest } from './client'

export interface Cluster {
  cluster_id: number
  label: string | null
  category: string | null
  /** The literal "Unassigned" when the complaints never resolved to a ward. */
  ward: string | null
  /**
   * Counted from the complaint rows, not read from the `IssueCluster` cache
   * column, so it cannot disagree with the complaints listed in the case file.
   */
  complaint_count: number
  complaint_ids: number[]
  created_at: string | null
}

export function fetchCluster(token: string, clusterId: number): Promise<Cluster> {
  return apiRequest<Cluster>(`/intelligence/clusters/${clusterId}`, { token })
}
