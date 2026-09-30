/**
 * Officer decisions and projects.
 *
 * Endpoints (backend/projects_router.py, mounted from main.py):
 *   POST   /projects/recommendations/{id}/approve
 *   POST   /projects/recommendations/{id}/modify
 *   POST   /projects/recommendations/{id}/reject
 *   GET    /decisions/recommendation/{id}
 *   GET    /projects
 *   GET    /projects/{id}
 *   PATCH  /projects/{id}/status
 *   GET    /impact
 *   GET    /impact/summary
 *
 * Every one of them is officer-gated by the backend, so the role check the
 * dashboard already does is a convenience, not the security boundary. Failures
 * are surfaced with the server's own message, because the workflow returns a
 * meaningful reason for a conflict (409) rather than a generic error.
 */
import { apiRequest } from './client'

export interface OfficerRef {
  id: number
  name: string | null
  email: string | null
  role: string | null
}

export interface Decision {
  id: number
  recommendation_id: number | null
  project_id: number | null
  decision: string
  reason: string | null
  action_snapshot: string | null
  created_at: string | null
  officer: OfficerRef | null
}

export interface Project {
  id: number
  recommendation_id: number | null
  title: string | null
  description: string | null
  status: string
  created_at: string | null
  officer: OfficerRef | null
  action: string | null
  location: string | null
  priority_score: number | null
  priority_level: string | null
  related_complaints: number | null
  decisions: Decision[]
}

export interface DecisionResult {
  project: Project | null
  decision: Decision
}

export type ProjectStatus = 'Approved' | 'In Progress' | 'Completed'

/** The one legal order. Anything else is refused by the backend. */
export const STATUS_FLOW: ProjectStatus[] = ['Approved', 'In Progress', 'Completed']

/** The status a project may move to next, or null when it is finished. */
export function nextStatus(current: string): ProjectStatus | null {
  const index = STATUS_FLOW.indexOf(current as ProjectStatus)
  if (index < 0 || index === STATUS_FLOW.length - 1) return null
  return STATUS_FLOW[index + 1]
}

export function listProjects(token: string): Promise<Project[]> {
  return apiRequest<Project[]>('/projects', { token })
}

export function getProject(token: string, projectId: number): Promise<Project> {
  return apiRequest<Project>(`/projects/${projectId}`, { token })
}

export function listDecisions(token: string, recommendationId: number): Promise<Decision[]> {
  return apiRequest<Decision[]>(`/decisions/recommendation/${recommendationId}`, { token })
}

export function approveRecommendation(
  token: string,
  recommendationId: number,
  body: { title?: string; description?: string; reason?: string } = {},
): Promise<DecisionResult> {
  return apiRequest<DecisionResult>(
    `/projects/recommendations/${recommendationId}/approve`,
    { method: 'POST', token, body },
  )
}

export function modifyRecommendation(
  token: string,
  recommendationId: number,
  body: { title: string; description?: string; reason?: string },
): Promise<DecisionResult> {
  return apiRequest<DecisionResult>(
    `/projects/recommendations/${recommendationId}/modify`,
    { method: 'POST', token, body },
  )
}

export function rejectRecommendation(
  token: string,
  recommendationId: number,
  reason: string,
): Promise<Decision> {
  return apiRequest<Decision>(`/projects/recommendations/${recommendationId}/reject`, {
    method: 'POST',
    token,
    body: { reason },
  })
}

export function updateProjectStatus(
  token: string,
  projectId: number,
  status: ProjectStatus,
  reason?: string,
): Promise<DecisionResult> {
  return apiRequest<DecisionResult>(`/projects/${projectId}/status`, {
    method: 'PATCH',
    token,
    body: reason ? { status, reason } : { status },
  })
}

// --------------------------------------------------------------------------
// impact
// --------------------------------------------------------------------------

export interface ImpactObservedChange {
  complaint_change: number | null
  complaint_change_percent: number | null
  severity_change: number | null
  priority_change: number | null
}

export interface Impact {
  id: number
  project_id: number
  before_complaint_count: number | null
  after_complaint_count: number | null
  complaints_resolved: number | null
  before_avg_severity_score: number | null
  after_avg_severity_score: number | null
  before_avg_priority_score: number | null
  after_avg_priority_score: number | null
  measurement_period_start: string | null
  measurement_period_end: string | null
  officer_notes: string | null
  recorded_by_officer_id: number
  recorded_by: OfficerRef | null
  created_at: string | null
  updated_at: string | null
  observed_change: ImpactObservedChange
}

export interface ImpactRecordRequest {
  before_complaint_count?: number
  after_complaint_count?: number
  complaints_resolved?: number
  before_avg_severity_score?: number
  after_avg_severity_score?: number
  before_avg_priority_score?: number
  after_avg_priority_score?: number
  measurement_period_start?: string
  measurement_period_end?: string
  officer_notes?: string
  auto_calculate?: boolean
}

export interface ImpactSummary {
  total_completed_projects: number
  projects_with_measured_impact: number
  projects_awaiting_impact_measurement: number
  total_complaints_associated: number
  observed_complaint_reduction: number
  projects_showing_reduction: number
}

export function recordProjectImpact(
  token: string,
  projectId: number,
  body: ImpactRecordRequest,
): Promise<Impact> {
  return apiRequest<Impact>(`/projects/${projectId}/impact`, {
    method: 'POST',
    token,
    body,
  })
}

export function getProjectImpact(token: string, projectId: number): Promise<Impact> {
  return apiRequest<Impact>(`/projects/${projectId}/impact`, { token })
}

export function updateProjectImpact(
  token: string,
  projectId: number,
  body: ImpactRecordRequest,
): Promise<Impact> {
  return apiRequest<Impact>(`/projects/${projectId}/impact`, {
    method: 'PATCH',
    token,
    body,
  })
}

/**
 * Every recorded impact measurement, plus the project ids that have one.
 *
 * The Impact page needs this to tell a measured project from an unmeasured one.
 * Fetching `/projects/{id}/impact` per project would mean one request each and
 * an expected 404 for every project still awaiting measurement; here absence
 * is simply a missing entry in `measured_project_ids`.
 */
export interface ImpactList {
  impacts: Impact[]
  measured_project_ids: number[]
}

export function listImpacts(token: string): Promise<ImpactList> {
  return apiRequest<ImpactList>('/impact', { token })
}

export function getImpactSummary(token: string): Promise<ImpactSummary> {
  return apiRequest<ImpactSummary>('/impact/summary', { token })
}
