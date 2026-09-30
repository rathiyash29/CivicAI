/**
 * Complaint API for the citizen frontend.
 *
 * `API_BASE` is resolved from `VITE_API_BASE_URL` (see `api/client.ts`), so the
 * backend origin is environment-configurable rather than hardcoded.
 */
import { API_BASE } from './client'

export interface Complaint {
  complaint_id: string;
  user_id: number;
  text: string;
  language: string;
  location: string;
  category?: string;
  severity?: string;
  priority_score?: number;
  priority_level?: string;
  status: string;
  created_at: string;
  /** The AI reading stored at submission time, projected by the service layer. */
  analysis_urgency?: string | null;
  analysis_affected_group?: string | null;
  analysis_issue_summary?: string | null;
  analysis_recommended_action?: string | null;
}

export interface MyComplaintsResponse {
  success: boolean;
  complaints: Complaint[];
  total: number;
}

export async function getMyComplaints(token: string): Promise<MyComplaintsResponse> {
  const response = await fetch(`${API_BASE}/complaints/my`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to fetch complaints');
  }

  return response.json();
}

/**
 * One of the caller's own complaints, by its public id (`CA-000072`).
 *
 * Resolved from the existing `/complaints/my` listing rather than a dedicated
 * endpoint: the listing is already scoped to the authenticated citizen, so it
 * carries the full stored record -- including the AI analysis fields -- and a
 * citizen cannot read anyone else's complaint by guessing an id.
 *
 * Returns `null` when the citizen has no complaint with that id, which is not
 * an error: a stale bookmark should say "not found", not crash.
 */
export async function getStoredComplaint(
  token: string,
  complaintId: string,
): Promise<Complaint | null> {
  const data = await getMyComplaints(token);
  const wanted = complaintId.trim().toUpperCase();
  const rows = data.complaints ?? [];
  return rows.find((row) => row.complaint_id?.toUpperCase() === wanted) ?? null;
}

export async function submitComplaint(
  data: { text: string; language: string; location: string },
  token?: string
): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/complaints`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to submit complaint');
  }

  return response.json();
}