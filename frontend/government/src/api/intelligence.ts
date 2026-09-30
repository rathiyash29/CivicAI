/**
 * Read access to Member 2's existing intelligence endpoints.
 *
 * Everything under /intelligence is already gated by `require_officer` on the
 * backend, so the same JWT used for /auth/me is what these calls need. Nothing
 * here is mock data or a placeholder payload: if the endpoint fails, the caller
 * gets an error and shows it.
 */
import { apiRequest } from './client'

/**
 * Row counts returned by GET /intelligence/stats.
 *
 * The first eight are per-table counts. The rest are derived stage counts for
 * the parts of the pipeline that have no table of their own -- an AI analysis
 * is a column on the complaint row, a hotspot is a computed grouping, and an
 * impact measurement is a row on the project. They are real counts either way;
 * nothing here is a placeholder.
 */
export interface IntelligenceStats {
  locations: number
  complaints: number
  scored_complaints: number
  issue_clusters: number
  infrastructure: number
  demographics: number
  investments: number
  recommendations: number
  /** Complaints with an AI issue summary written at submission time. */
  analysed_complaints: number
  /** Groups meeting the default complaint threshold, same as the Hotspots page. */
  hotspots: number
  projects: number
  completed_projects: number
  measured_impact: number
}

export function fetchStats(token: string): Promise<IntelligenceStats> {
  return apiRequest<IntelligenceStats>('/intelligence/stats', { token })
}
