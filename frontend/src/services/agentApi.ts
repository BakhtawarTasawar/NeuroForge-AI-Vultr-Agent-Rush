import { apiClient } from './api';
import { ResearchSession, ResearchEvent, ResearchSessionCreate } from '../types';

export async function createResearchSession(
  projectId: string,
  payload: ResearchSessionCreate
): Promise<ResearchSession> {
  const response = await apiClient.post<ResearchSession>(
    `/projects/${projectId}/research-sessions`,
    payload
  );
  return response.data;
}

export async function listResearchSessions(
  projectId: string
): Promise<ResearchSession[]> {
  const response = await apiClient.get<ResearchSession[]>(
    `/projects/${projectId}/research-sessions`
  );
  return response.data;
}

export async function getResearchSession(
  sessionId: string
): Promise<ResearchSession> {
  const response = await apiClient.get<ResearchSession>(
    `/research-sessions/${sessionId}`
  );
  return response.data;
}

export async function approveResearchPlan(
  sessionId: string,
  notes?: string,
  planHash?: string
): Promise<ResearchSession> {
  const response = await apiClient.post<ResearchSession>(
    `/research-sessions/${sessionId}/approve`,
    { decision: 'approve', notes, plan_hash: planHash }
  );
  return response.data;
}

export async function rejectResearchPlan(
  sessionId: string,
  notes: string
): Promise<ResearchSession> {
  const response = await apiClient.post<ResearchSession>(
    `/research-sessions/${sessionId}/reject`,
    { decision: 'reject', notes }
  );
  return response.data;
}

export async function continueResearchSession(
  sessionId: string
): Promise<ResearchSession> {
  const response = await apiClient.post<ResearchSession>(
    `/research-sessions/${sessionId}/continue`
  );
  return response.data;
}

export async function getSessionEvents(
  sessionId: string
): Promise<ResearchEvent[]> {
  const response = await apiClient.get<ResearchEvent[]>(
    `/research-sessions/${sessionId}/events`
  );
  return response.data;
}

export async function getSessionEvidence(
  sessionId: string
): Promise<{ session_id: string; evidence_items: any[] }> {
  const response = await apiClient.get<{ session_id: string; evidence_items: any[] }>(
    `/research-sessions/${sessionId}/evidence`
  );
  return response.data;
}

export async function getSessionSummary(
  sessionId: string
): Promise<{ session_id: string; status: string; final_summary: any }> {
  const response = await apiClient.get<{ session_id: string; status: string; final_summary: any }>(
    `/research-sessions/${sessionId}/summary`
  );
  return response.data;
}

