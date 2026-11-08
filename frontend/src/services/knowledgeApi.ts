import { apiClient } from './api';
import {
  KnowledgeDocument,
  KnowledgeSearchResponse,
} from '../types';

export interface KnowledgeUploadPayload {
  file: File;
  title?: string;
  source_type?: string;
  doi?: string;
  authors?: string;
  publication_year?: number;
  journal?: string;
  source_url?: string;
  tags?: string;
  custom_metadata?: Record<string, any>;
}

export interface KnowledgeTextPayload {
  title: string;
  content: string;
  source_type?: string;
  doi?: string;
  authors?: string;
  publication_year?: number;
  journal?: string;
  source_url?: string;
  tags?: string;
  custom_metadata?: Record<string, any>;
}

export async function uploadKnowledgeDocument(
  projectId: string,
  payload: KnowledgeUploadPayload,
  onUploadProgress?: (progressEvent: any) => void
): Promise<KnowledgeDocument> {
  const formData = new FormData();
  formData.append('file', payload.file);

  if (payload.title?.trim()) {
    formData.append('title', payload.title.trim());
  }
  if (payload.source_type?.trim()) {
    formData.append('source_type', payload.source_type.trim());
  }
  if (payload.doi?.trim()) {
    formData.append('doi', payload.doi.trim());
  }
  if (payload.authors?.trim()) {
    formData.append('authors', payload.authors.trim());
  }
  if (payload.publication_year !== undefined && payload.publication_year !== null) {
    formData.append('publication_year', payload.publication_year.toString());
  }
  if (payload.journal?.trim()) {
    formData.append('journal', payload.journal.trim());
  }
  if (payload.source_url?.trim()) {
    formData.append('source_url', payload.source_url.trim());
  }
  if (payload.tags?.trim()) {
    formData.append('tags', payload.tags.trim());
  }
  if (payload.custom_metadata && Object.keys(payload.custom_metadata).length > 0) {
    formData.append('custom_metadata', JSON.stringify(payload.custom_metadata));
  }

  const response = await apiClient.post<KnowledgeDocument>(
    `/projects/${projectId}/knowledge/upload`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress,
    }
  );
  return response.data;
}

export async function ingestKnowledgeText(
  projectId: string,
  payload: KnowledgeTextPayload
): Promise<KnowledgeDocument> {
  const response = await apiClient.post<KnowledgeDocument>(
    `/projects/${projectId}/knowledge/text`,
    payload
  );
  return response.data;
}

export async function listKnowledgeDocuments(
  projectId: string,
  limit: number = 50,
  offset: number = 0
): Promise<KnowledgeDocument[]> {
  const response = await apiClient.get<KnowledgeDocument[]>(
    `/projects/${projectId}/knowledge`,
    {
      params: { limit, offset },
    }
  );
  return response.data;
}

export async function getKnowledgeDocument(
  projectId: string,
  documentId: string
): Promise<KnowledgeDocument> {
  const response = await apiClient.get<KnowledgeDocument>(
    `/projects/${projectId}/knowledge/${documentId}`
  );
  return response.data;
}

export async function deleteKnowledgeDocument(
  projectId: string,
  documentId: string
): Promise<{ detail: string }> {
  const response = await apiClient.delete<{ detail: string }>(
    `/projects/${projectId}/knowledge/${documentId}`
  );
  return response.data;
}

export async function searchKnowledge(
  projectId: string,
  query: string,
  topK: number = 5,
  scoreThreshold: number = 0.0
): Promise<KnowledgeSearchResponse> {
  const response = await apiClient.post<KnowledgeSearchResponse>(
    `/projects/${projectId}/knowledge/search`,
    {
      query,
      top_k: topK,
      score_threshold: scoreThreshold,
    }
  );
  return response.data;
}
