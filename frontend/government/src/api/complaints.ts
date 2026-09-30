/**
 * Complaints, from the existing CivicAI contract.
 *
 * Endpoint: GET /complaints  (backend/main.py)
 *
 * Officer-only listing of every citizen complaint. It is guarded by
 * `require_officer`, so it answers 401 without a token and 403 for a citizen --
 * which is why the dashboard uses this rather than the citizen-scoped
 * `/complaints/my`, which only ever returns the caller's own rows.
 *
 * Field names and optionality come from `complaint_to_contract`
 * (backend/complaint_service.py). `category`, `severity`, `priority_score` and
 * `priority_level` are genuinely nullable in the database, so they are typed
 * optional and rendered as an em dash when absent.
 *
 * The `analysis_*` fields are what the AI layer wrote on the complaint row at
 * submission time. They were always stored and simply never returned, which is
 * why the detail modal used to say "not exposed by the current API". They are
 * nullable for the same reason the other columns are: a complaint created
 * before these were written, or through a path that skipped analysis, has none.
 *
 * `cluster_id` is the issue cluster this complaint was grouped into. It is what
 * links a complaint to the hotspot and recommendation built from it.
 */
import { apiRequest } from './client'

export interface Complaint {
  complaint_id: string
  user_id: number | null
  text: string
  language: string | null
  location: string | null
  category?: string | null
  severity?: string | null
  priority_score?: number | null
  priority_level?: string | null
  status: string
  created_at: string
  /** Issue cluster this complaint belongs to; null when it was never clustered. */
  cluster_id?: number | null
  analysis_urgency?: string | null
  analysis_affected_group?: string | null
  analysis_issue_summary?: string | null
  analysis_recommended_action?: string | null
}

/** The five factors the priority engine weights, each normalised 0-100. */
export type PriorityFactorName =
  | 'citizen_demand'
  | 'infrastructure_gap'
  | 'population_impact'
  | 'urgency'
  | 'investment_gap'

export type PriorityFactors = Record<PriorityFactorName, number>

/**
 * Where each factor's number came from, and the inputs behind citizen demand.
 *
 * `*_source` is "database" when the value was read from a real ward row and
 * "default" when no location resolved, so the engine fell back to a neutral
 * constant. A "default" is honest but weaker evidence, and the UI says so
 * rather than presenting it as measured.
 */
export interface PriorityEvidence {
  citizen_demand_basis: string
  complaints_in_demand_group: number
  infrastructure_gap_source: 'database' | 'default'
  investment_gap_source: 'database' | 'default'
  population_impact_source: 'database' | 'default'
}

export interface PriorityExplanation {
  complaint_id: number
  /** The score on the complaint row, which is the one the dashboard displays. */
  stored_score: number | null
  stored_level: string | null
  /** What the same factors would produce now. Shown only when it differs. */
  current_score: number
  factors: PriorityFactors
  weights: Record<PriorityFactorName, number>
  evidence: PriorityEvidence
}

export interface ComplaintsResponse {
  success: boolean
  complaints: Complaint[]
  total: number
}

/** Officer-wide listing: every citizen complaint. Requires the officer role. */
export function fetchComplaints(token: string): Promise<ComplaintsResponse> {
  return apiRequest<ComplaintsResponse>('/complaints', { token })
}

/**
 * The five weighted factors behind a complaint's stored priority score.
 *
 * Takes the public `CA-000042` form, because that is the only id the
 * complaint listing exposes. The backend resolves it to the integer primary
 * key; there is no `CA-MEM-` equivalent, since an in-memory complaint has no
 * database row to explain.
 */
export function fetchPriorityExplanation(
  token: string,
  complaintId: string,
): Promise<PriorityExplanation> {
  return apiRequest<PriorityExplanation>(
    `/intelligence/priority/${encodeURIComponent(complaintId)}/explanation`,
    { token },
  )
}
