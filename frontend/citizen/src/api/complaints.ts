export const API_BASE = 'http://127.0.0.1:8000';

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