import React, { useState, useEffect, useRef } from 'react';
import {
  BookOpen,
  UploadCloud,
  FileText,
  Search,
  Trash2,
  Eye,
  Plus,
  Sparkles,
  ExternalLink,
  Layers,
  CheckCircle2,
  X,
  FolderGit2,
} from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import {
  listKnowledgeDocuments,
  getKnowledgeDocument,
  deleteKnowledgeDocument,
  searchKnowledge,
  uploadKnowledgeDocument,
  ingestKnowledgeText,
} from '../../services/knowledgeApi';
import {
  Project,
  KnowledgeDocument,
  KnowledgeCitation,
} from '../../types';
import { Badge } from '../../components/common/Badge';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { Modal } from '../../components/common/Modal';
import { EmptyState } from '../../components/common/EmptyState';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

interface CustomMetaPair {
  key: string;
  value: string;
}

export const KnowledgePage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [isLoadingProjects, setIsLoadingProjects] = useState(true);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Modals
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [isTextModalOpen, setIsTextModalOpen] = useState(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

  // Document for detail / delete
  const [selectedDoc, setSelectedDoc] = useState<KnowledgeDocument | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [docToDelete, setDocToDelete] = useState<KnowledgeDocument | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Search State
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<KnowledgeCitation[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Upload Form State
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadSourceType, setUploadSourceType] = useState('paper');
  const [uploadDoi, setUploadDoi] = useState('');
  const [uploadAuthors, setUploadAuthors] = useState('');
  const [uploadYear, setUploadYear] = useState('');
  const [uploadJournal, setUploadJournal] = useState('');
  const [uploadSourceUrl, setUploadSourceUrl] = useState('');
  const [uploadTags, setUploadTags] = useState('');
  const [uploadCustomMeta, setUploadCustomMeta] = useState<CustomMetaPair[]>([]);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadFormError, setUploadFormError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Text Ingestion Form State
  const [textTitle, setTextTitle] = useState('');
  const [textContent, setTextContent] = useState('');
  const [textSourceType, setTextSourceType] = useState('abstract');
  const [textDoi, setTextDoi] = useState('');
  const [textAuthors, setTextAuthors] = useState('');
  const [textYear, setTextYear] = useState('');
  const [textJournal, setTextJournal] = useState('');
  const [textSourceUrl, setTextSourceUrl] = useState('');
  const [textTags, setTextTags] = useState('');
  const [textCustomMeta, setTextCustomMeta] = useState<CustomMetaPair[]>([]);
  const [isIngestingText, setIsIngestingText] = useState(false);
  const [textFormError, setTextFormError] = useState<string | null>(null);

  // Fetch accessible projects on mount
  useEffect(() => {
    fetchProjects();
  }, []);

  // Fetch documents when selected project changes
  useEffect(() => {
    if (selectedProjectId) {
      fetchDocuments(selectedProjectId);
      setSearchResults(null);
      setSearchQuery('');
    } else {
      setDocuments([]);
    }
  }, [selectedProjectId]);

  const fetchProjects = async () => {
    setIsLoadingProjects(true);
    setError(null);
    try {
      const res = await apiClient.get<Project[]>('/projects');
      setProjects(res.data);
      if (res.data.length > 0) {
        setSelectedProjectId(res.data[0].id);
      }
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const fetchDocuments = async (projId: string) => {
    setIsLoadingDocs(true);
    setError(null);
    try {
      const data = await listKnowledgeDocuments(projId, 100, 0);
      setDocuments(data);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoadingDocs(false);
    }
  };

  // Helper: Convert CustomMetaPair[] to JSON object
  const pairsToObject = (pairs: CustomMetaPair[]): Record<string, any> => {
    const obj: Record<string, any> = {};
    for (const p of pairs) {
      if (p.key.trim()) {
        obj[p.key.trim()] = p.value.trim();
      }
    }
    return obj;
  };

  // Dynamic Key-Value Helpers
  const addUploadMetaPair = () => {
    setUploadCustomMeta([...uploadCustomMeta, { key: '', value: '' }]);
  };

  const updateUploadMetaPair = (index: number, key: string, value: string) => {
    const updated = [...uploadCustomMeta];
    updated[index] = { key, value };
    setUploadCustomMeta(updated);
  };

  const removeUploadMetaPair = (index: number) => {
    setUploadCustomMeta(uploadCustomMeta.filter((_, i) => i !== index));
  };

  const addTextMetaPair = () => {
    setTextCustomMeta([...textCustomMeta, { key: '', value: '' }]);
  };

  const updateTextMetaPair = (index: number, key: string, value: string) => {
    const updated = [...textCustomMeta];
    updated[index] = { key, value };
    setTextCustomMeta(updated);
  };

  const removeTextMetaPair = (index: number) => {
    setTextCustomMeta(textCustomMeta.filter((_, i) => i !== index));
  };

  // Handle File Upload
  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      setUploadFormError('Please select a file to upload.');
      return;
    }
    if (!selectedProjectId) {
      setUploadFormError('Please select a research project first.');
      return;
    }

    setIsUploading(true);
    setUploadFormError(null);
    setUploadProgress(10);

    try {
      const customMetaObj = pairsToObject(uploadCustomMeta);
      const parsedYear = uploadYear.trim() ? parseInt(uploadYear.trim(), 10) : undefined;

      const newDoc = await uploadKnowledgeDocument(
        selectedProjectId,
        {
          file: uploadFile,
          title: uploadTitle.trim() || uploadFile.name,
          source_type: uploadSourceType,
          doi: uploadDoi.trim() || undefined,
          authors: uploadAuthors.trim() || undefined,
          publication_year: isNaN(parsedYear as number) ? undefined : parsedYear,
          journal: uploadJournal.trim() || undefined,
          source_url: uploadSourceUrl.trim() || undefined,
          tags: uploadTags.trim() || undefined,
          custom_metadata: Object.keys(customMetaObj).length > 0 ? customMetaObj : undefined,
        },
        (progressEvent) => {
          if (progressEvent.total) {
            const percent = Math.round((progressEvent.loaded * 90) / progressEvent.total);
            setUploadProgress(Math.max(15, percent));
          }
        }
      );

      setUploadProgress(100);
      setDocuments((prev) => [newDoc, ...prev]);
      setSuccessMessage(`Document "${newDoc.title}" ingested successfully (${newDoc.chunk_count} chunks indexed).`);
      setTimeout(() => setSuccessMessage(null), 5000);

      // Reset form
      setUploadFile(null);
      setUploadTitle('');
      setUploadDoi('');
      setUploadAuthors('');
      setUploadYear('');
      setUploadJournal('');
      setUploadSourceUrl('');
      setUploadTags('');
      setUploadCustomMeta([]);
      setUploadProgress(null);
      setIsUploadModalOpen(false);
    } catch (err) {
      setUploadFormError(formatErrorMessage(err));
    } finally {
      setIsUploading(false);
    }
  };

  // Handle Manual Text Ingestion
  const handleTextSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!textTitle.trim()) {
      setTextFormError('Please provide a document or abstract title.');
      return;
    }
    if (!textContent.trim() || textContent.trim().length < 10) {
      setTextFormError('Content must contain at least 10 characters.');
      return;
    }
    if (!selectedProjectId) {
      setTextFormError('Please select a research project first.');
      return;
    }

    setIsIngestingText(true);
    setTextFormError(null);

    try {
      const customMetaObj = pairsToObject(textCustomMeta);
      const parsedYear = textYear.trim() ? parseInt(textYear.trim(), 10) : undefined;

      const newDoc = await ingestKnowledgeText(selectedProjectId, {
        title: textTitle.trim(),
        content: textContent.trim(),
        source_type: textSourceType,
        doi: textDoi.trim() || undefined,
        authors: textAuthors.trim() || undefined,
        publication_year: isNaN(parsedYear as number) ? undefined : parsedYear,
        journal: textJournal.trim() || undefined,
        source_url: textSourceUrl.trim() || undefined,
        tags: textTags.trim() || undefined,
        custom_metadata: Object.keys(customMetaObj).length > 0 ? customMetaObj : undefined,
      });

      setDocuments((prev) => [newDoc, ...prev]);
      setSuccessMessage(`Scientific text "${newDoc.title}" ingested successfully (${newDoc.chunk_count} chunks indexed).`);
      setTimeout(() => setSuccessMessage(null), 5000);

      // Reset form
      setTextTitle('');
      setTextContent('');
      setTextDoi('');
      setTextAuthors('');
      setTextYear('');
      setTextJournal('');
      setTextSourceUrl('');
      setTextTags('');
      setTextCustomMeta([]);
      setIsTextModalOpen(false);
    } catch (err) {
      setTextFormError(formatErrorMessage(err));
    } finally {
      setIsIngestingText(false);
    }
  };

  // Open Document Detail
  const handleViewDetail = async (doc: KnowledgeDocument) => {
    setSelectedDoc(doc);
    setIsDetailModalOpen(true);
    setIsDetailLoading(true);
    try {
      const detailed = await getKnowledgeDocument(doc.project_id, doc.id);
      setSelectedDoc(detailed);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsDetailLoading(false);
    }
  };

  // Open Delete Confirmation
  const confirmDelete = (doc: KnowledgeDocument) => {
    setDocToDelete(doc);
    setIsDeleteModalOpen(true);
  };

  // Execute Deletion
  const handleDelete = async () => {
    if (!docToDelete) return;
    setIsDeleting(true);
    try {
      await deleteKnowledgeDocument(docToDelete.project_id, docToDelete.id);
      setDocuments((prev) => prev.filter((d) => d.id !== docToDelete.id));
      setSuccessMessage(`Document "${docToDelete.title}" and its vectors removed.`);
      setTimeout(() => setSuccessMessage(null), 4000);
      setIsDeleteModalOpen(false);
      setDocToDelete(null);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsDeleting(false);
    }
  };

  // Semantic Search
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim() || !selectedProjectId) return;

    setIsSearching(true);
    setSearchError(null);
    try {
      const res = await searchKnowledge(selectedProjectId, searchQuery.trim(), 5, 0.0);
      setSearchResults(res.citations);
    } catch (err) {
      setSearchError(formatErrorMessage(err));
    } finally {
      setIsSearching(false);
    }
  };

  const clearSearch = () => {
    setSearchQuery('');
    setSearchResults(null);
    setSearchError(null);
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
  };

  const currentProject = projects.find((p) => p.id === selectedProjectId);

  if (isLoadingProjects) {
    return <LoadingSkeleton rows={4} />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-cyan-400" />
            Scientific Knowledge Base (RAG)
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Index peer-reviewed papers, clinical trial protocols, and pathway annotations into Qdrant for autonomous agent retrieval.
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setTextFormError(null);
              setIsTextModalOpen(true);
            }}
            icon={<Plus className="w-4 h-4" />}
            disabled={!selectedProjectId}
          >
            Add Abstract / Text
          </Button>

          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setUploadFormError(null);
              setIsUploadModalOpen(true);
            }}
            icon={<UploadCloud className="w-4 h-4" />}
            disabled={!selectedProjectId}
          >
            Upload Literature
          </Button>
        </div>
      </div>

      {/* Global Alerts */}
      {error && (
        <div className="p-3.5 rounded-xl bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-rose-400 hover:text-rose-200">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {successMessage && (
        <div className="p-3.5 rounded-xl bg-emerald-950/40 border border-emerald-800/60 text-xs text-emerald-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Project Selector Bar */}
      <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <FolderGit2 className="w-4 h-4 text-cyan-400 shrink-0" />
          <div className="flex flex-col sm:flex-row sm:items-center gap-2">
            <label className="text-xs font-semibold text-slate-300">Target Project:</label>
            {projects.length > 0 ? (
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-cyan-500"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title} ({p.domain})
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-xs text-amber-400">No research projects found. Create a project first.</span>
            )}
          </div>
        </div>

        {currentProject && (
          <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
            <span className="px-2.5 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-cyan-400">
              Domain: {currentProject.domain}
            </span>
            <span className="text-slate-500">•</span>
            <span>{documents.length} literature {documents.length === 1 ? 'doc' : 'docs'} indexed</span>
          </div>
        )}
      </div>

      {/* Semantic Search Box */}
      {selectedProjectId && (
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-3">
          <form onSubmit={handleSearch} className="flex gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search literature semantically (e.g. 'KRAS switch II pocket inhibitors in NSCLC')..."
                className="w-full bg-slate-950 border border-slate-700 text-xs rounded-lg pl-9 pr-3 py-2 text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={isSearching}
              disabled={!searchQuery.trim()}
              icon={<Sparkles className="w-3.5 h-3.5" />}
            >
              Semantic Search
            </Button>
            {searchResults && (
              <Button type="button" variant="secondary" size="sm" onClick={clearSearch}>
                Clear
              </Button>
            )}
          </form>

          {searchError && (
            <p className="text-xs text-rose-400">{searchError}</p>
          )}

          {/* Search Results Display */}
          {searchResults && (
            <div className="mt-4 space-y-3 pt-3 border-t border-slate-800">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span className="font-semibold text-cyan-300">
                  Retrieved {searchResults.length} Relevant {searchResults.length === 1 ? 'Excerpt' : 'Excerpts'} (Cosine Similarity via Qdrant)
                </span>
                <span className="text-[11px] font-mono">Strict Project Filter: Active</span>
              </div>

              {searchResults.length === 0 ? (
                <div className="p-4 text-center text-xs text-slate-500 bg-slate-950/40 rounded-lg">
                  No matching literature chunks found above similarity threshold.
                </div>
              ) : (
                <div className="space-y-2.5">
                  {searchResults.map((citation, idx) => (
                    <div
                      key={idx}
                      className="p-3.5 rounded-xl bg-slate-950 border border-slate-800/80 space-y-2 text-xs hover:border-slate-700 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-0.5">
                          <span className="font-semibold text-slate-100 flex items-center gap-1.5">
                            <BookOpen className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                            {citation.document_title}
                          </span>
                          <span className="text-[10px] font-mono text-slate-500">
                            Source: {citation.source_filename} • Chunk index #{citation.chunk_index}
                          </span>
                        </div>
                        <Badge variant="cyan" size="sm">
                          Score: {(citation.relevance_score * 100).toFixed(1)}%
                        </Badge>
                      </div>

                      {/* Excerpt */}
                      <p className="text-slate-300 text-xs leading-relaxed bg-slate-900/60 p-2.5 rounded-lg border border-slate-800">
                        "{citation.chunk_text}"
                      </p>

                      {/* Metadata row */}
                      {citation.metadata && (
                        <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-slate-400">
                          {citation.metadata.doi && (
                            <span className="font-mono text-cyan-400">
                              DOI: {citation.metadata.doi}
                            </span>
                          )}
                          {citation.metadata.authors && (
                            <span>• {citation.metadata.authors}</span>
                          )}
                          {citation.metadata.publication_year && (
                            <span>({citation.metadata.publication_year})</span>
                          )}
                          {citation.metadata.journal && (
                            <span className="italic">• {citation.metadata.journal}</span>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Document Library List */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-mono">
            Project Literature Inventory
          </h3>
          <span className="text-xs text-slate-400">
            {documents.length} {documents.length === 1 ? 'document' : 'documents'}
          </span>
        </div>

        {isLoadingDocs ? (
          <LoadingSkeleton rows={3} />
        ) : documents.length === 0 ? (
          <EmptyState
            icon={<BookOpen className="w-6 h-6 text-cyan-400" />}
            title="No scientific literature uploaded yet"
            description="Upload research papers (PDF), abstracts, or pathway descriptions so the autonomous agent can retrieve peer-reviewed domain context during experiment planning."
            actionLabel="Upload Literature PDF"
            onAction={() => {
              setUploadFormError(null);
              setIsUploadModalOpen(true);
            }}
          />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-mono bg-slate-900/50">
                  <th className="py-3 px-4">Title &amp; Source</th>
                  <th className="py-3 px-3">Format</th>
                  <th className="py-3 px-3">Metadata (DOI / Journal)</th>
                  <th className="py-3 px-3">Chunks</th>
                  <th className="py-3 px-3">Size</th>
                  <th className="py-3 px-3">Date</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-slate-900/40 transition-colors">
                    {/* Title */}
                    <td className="py-3 px-4">
                      <div className="font-semibold text-slate-100 flex items-center gap-1.5">
                        <FileText className="w-4 h-4 text-cyan-400 shrink-0" />
                        <span className="truncate max-w-xs">{doc.title}</span>
                      </div>
                      <div className="text-[11px] font-mono text-slate-500 truncate max-w-xs">
                        {doc.filename}
                      </div>
                    </td>

                    {/* Format */}
                    <td className="py-3 px-3">
                      <Badge variant="slate" size="sm">
                        {doc.file_format}
                      </Badge>
                    </td>

                    {/* Metadata */}
                    <td className="py-3 px-3 text-[11px] text-slate-400">
                      {doc.doi ? (
                        <div className="font-mono text-cyan-400 truncate max-w-[180px]">
                          {doc.doi}
                        </div>
                      ) : doc.journal ? (
                        <div className="italic truncate max-w-[180px]">{doc.journal}</div>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                      {doc.publication_year && (
                        <span className="text-slate-500"> ({doc.publication_year})</span>
                      )}
                    </td>

                    {/* Chunks */}
                    <td className="py-3 px-3 font-mono text-slate-300">
                      <div className="flex items-center gap-1">
                        <Layers className="w-3.5 h-3.5 text-purple-400" />
                        <span>{doc.chunk_count}</span>
                      </div>
                    </td>

                    {/* Size */}
                    <td className="py-3 px-3 font-mono text-slate-400">
                      {formatBytes(doc.file_size_bytes)}
                    </td>

                    {/* Date */}
                    <td className="py-3 px-3 text-slate-400 text-[11px]">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </td>

                    {/* Actions */}
                    <td className="py-3 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleViewDetail(doc)}
                          icon={<Eye className="w-3.5 h-3.5" />}
                        >
                          View
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => confirmDelete(doc)}
                          icon={<Trash2 className="w-3.5 h-3.5" />}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Upload Literature Modal */}
      <Modal
        isOpen={isUploadModalOpen}
        onClose={() => !isUploading && setIsUploadModalOpen(false)}
        title="Upload Scientific Literature Document"
        description="Upload research papers (PDF), notes (TXT/MD), or annotations (JSON). Extracted text will be chunked and indexed into Qdrant."
      >
        <form onSubmit={handleUploadSubmit} className="space-y-4 text-xs">
          {uploadFormError && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-rose-300">
              {uploadFormError}
            </div>
          )}

          {/* File input */}
          <div className="space-y-1.5">
            <label className="font-semibold text-slate-300 block">Select Document *</label>
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-slate-700 hover:border-cyan-500/80 rounded-xl p-5 text-center cursor-pointer transition-colors bg-slate-950/60"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.txt,.md,.json"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    setUploadFile(e.target.files[0]);
                    if (!uploadTitle) {
                      setUploadTitle(e.target.files[0].name.replace(/\.[^/.]+$/, ''));
                    }
                  }
                }}
                className="hidden"
              />
              <UploadCloud className="w-7 h-7 text-cyan-400 mx-auto mb-2" />
              {uploadFile ? (
                <div>
                  <p className="font-semibold text-slate-200">{uploadFile.name}</p>
                  <p className="text-[11px] text-slate-500">{formatBytes(uploadFile.size)}</p>
                </div>
              ) : (
                <div>
                  <p className="text-slate-300">Click to choose PDF, TXT, MD or JSON</p>
                  <p className="text-[11px] text-slate-500 mt-1">Maximum file size: 25 MiB</p>
                </div>
              )}
            </div>
          </div>

          {/* Document Title & Source Type */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="sm:col-span-2">
              <label className="font-semibold text-slate-300 block mb-1">Document Title</label>
              <Input
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                placeholder="e.g. KRAS G12C Inhibitors in Non-Small Cell Lung Cancer"
              />
            </div>
            <div>
              <label className="font-semibold text-slate-300 block mb-1">Source Type</label>
              <select
                value={uploadSourceType}
                onChange={(e) => setUploadSourceType(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 text-xs rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-cyan-500"
              >
                <option value="paper">Peer-Reviewed Paper</option>
                <option value="upload">General Upload</option>
                <option value="abstract">Abstract</option>
                <option value="trial">Clinical Trial Protocol</option>
                <option value="pathway">Pathway Reference</option>
              </select>
            </div>
          </div>

          {/* Scientific Metadata Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1 border-t border-slate-800">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">DOI (Digital Object Identifier)</label>
              <Input
                value={uploadDoi}
                onChange={(e) => setUploadDoi(e.target.value)}
                placeholder="e.g. 10.1056/NEJMoa1914710"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Publication Year</label>
              <Input
                type="number"
                value={uploadYear}
                onChange={(e) => setUploadYear(e.target.value)}
                placeholder="e.g. 2021"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Journal / Conference</label>
              <Input
                value={uploadJournal}
                onChange={(e) => setUploadJournal(e.target.value)}
                placeholder="e.g. Nature Medicine"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Authors</label>
              <Input
                value={uploadAuthors}
                onChange={(e) => setUploadAuthors(e.target.value)}
                placeholder="e.g. Canon J, Rex K, et al."
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Source URL</label>
              <Input
                value={uploadSourceUrl}
                onChange={(e) => setUploadSourceUrl(e.target.value)}
                placeholder="https://doi.org/..."
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Tags (Comma-separated)</label>
              <Input
                value={uploadTags}
                onChange={(e) => setUploadTags(e.target.value)}
                placeholder="kras, oncology, clinical-trial"
              />
            </div>
          </div>

          {/* Dynamic Key-Value Custom Metadata */}
          <div className="pt-2 border-t border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-[11px] font-semibold text-slate-300">
                Custom Key-Value Metadata (Optional)
              </label>
              <button
                type="button"
                onClick={addUploadMetaPair}
                className="text-[11px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" /> Add Field
              </button>
            </div>

            {uploadCustomMeta.map((pair, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="Key (e.g. cohort)"
                  value={pair.key}
                  onChange={(e) => updateUploadMetaPair(idx, e.target.value, pair.value)}
                  className="w-1/2 bg-slate-950 border border-slate-700 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500"
                />
                <input
                  type="text"
                  placeholder="Value (e.g. NSCLC Phase II)"
                  value={pair.value}
                  onChange={(e) => updateUploadMetaPair(idx, pair.key, e.target.value)}
                  className="w-1/2 bg-slate-950 border border-slate-700 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500"
                />
                <button
                  type="button"
                  onClick={() => removeUploadMetaPair(idx)}
                  className="p-1.5 text-slate-500 hover:text-rose-400"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          {/* Upload Progress Bar */}
          {uploadProgress !== null && (
            <div className="space-y-1">
              <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-cyan-500 transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="text-[10px] text-slate-400 text-right font-mono">
                {uploadProgress < 100 ? `Uploading & Embedding... ${uploadProgress}%` : 'Indexing into Qdrant...'}
              </p>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-800">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setIsUploadModalOpen(false)}
              disabled={isUploading}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={isUploading}
              disabled={!uploadFile}
            >
              Upload &amp; Index
            </Button>
          </div>
        </form>
      </Modal>

      {/* Manual Abstract / Text Ingestion Modal */}
      <Modal
        isOpen={isTextModalOpen}
        onClose={() => !isIngestingText && setIsTextModalOpen(false)}
        title="Add Scientific Abstract or Pathway Notes"
        description="Paste scientific abstracts, gene annotation notes, or biochemical mechanism descriptions for RAG retrieval."
      >
        <form onSubmit={handleTextSubmit} className="space-y-4 text-xs">
          {textFormError && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-rose-300">
              {textFormError}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="sm:col-span-2">
              <label className="font-semibold text-slate-300 block mb-1">Title *</label>
              <Input
                value={textTitle}
                onChange={(e) => setTextTitle(e.target.value)}
                placeholder="e.g. TP53 Signaling and Genomic Stability"
                required
              />
            </div>
            <div>
              <label className="font-semibold text-slate-300 block mb-1">Source Type</label>
              <select
                value={textSourceType}
                onChange={(e) => setTextSourceType(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 text-xs rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-cyan-500"
              >
                <option value="abstract">Abstract</option>
                <option value="paper">Literature Excerpt</option>
                <option value="pathway">Pathway Mechanism</option>
                <option value="annotation">Gene Annotation</option>
              </select>
            </div>
          </div>

          <div>
            <label className="font-semibold text-slate-300 block mb-1">Content / Scientific Text *</label>
            <textarea
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
              rows={6}
              placeholder="Paste scientific paper abstract, pathway mechanism, or biological summary here..."
              className="w-full bg-slate-950 border border-slate-700 text-xs rounded-xl p-3 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500 leading-relaxed font-sans"
              required
            />
          </div>

          {/* Scientific Metadata Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1 border-t border-slate-800">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">DOI</label>
              <Input
                value={textDoi}
                onChange={(e) => setTextDoi(e.target.value)}
                placeholder="e.g. 10.1038/s41568-019-0123-x"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Publication Year</label>
              <Input
                type="number"
                value={textYear}
                onChange={(e) => setTextYear(e.target.value)}
                placeholder="e.g. 2019"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Journal</label>
              <Input
                value={textJournal}
                onChange={(e) => setTextJournal(e.target.value)}
                placeholder="e.g. Cell"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Authors</label>
              <Input
                value={textAuthors}
                onChange={(e) => setTextAuthors(e.target.value)}
                placeholder="e.g. Kastenhuber ER, Lowe SW"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Source URL</label>
              <Input
                value={textSourceUrl}
                onChange={(e) => setTextSourceUrl(e.target.value)}
                placeholder="https://..."
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Tags</label>
              <Input
                value={textTags}
                onChange={(e) => setTextTags(e.target.value)}
                placeholder="tp53, cell-cycle, apoptosis"
              />
            </div>
          </div>

          {/* Dynamic Key-Value Custom Metadata */}
          <div className="pt-2 border-t border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-[11px] font-semibold text-slate-300">
                Custom Key-Value Metadata (Optional)
              </label>
              <button
                type="button"
                onClick={addTextMetaPair}
                className="text-[11px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" /> Add Field
              </button>
            </div>

            {textCustomMeta.map((pair, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="Key"
                  value={pair.key}
                  onChange={(e) => updateTextMetaPair(idx, e.target.value, pair.value)}
                  className="w-1/2 bg-slate-950 border border-slate-700 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500"
                />
                <input
                  type="text"
                  placeholder="Value"
                  value={pair.value}
                  onChange={(e) => updateTextMetaPair(idx, pair.key, e.target.value)}
                  className="w-1/2 bg-slate-950 border border-slate-700 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500"
                />
                <button
                  type="button"
                  onClick={() => removeTextMetaPair(idx)}
                  className="p-1.5 text-slate-500 hover:text-rose-400"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-800">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setIsTextModalOpen(false)}
              disabled={isIngestingText}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={isIngestingText}
              disabled={!textTitle.trim() || !textContent.trim()}
            >
              Ingest &amp; Index
            </Button>
          </div>
        </form>
      </Modal>

      {/* Document Detail & Extracted Chunks Modal */}
      {selectedDoc && (
        <Modal
          isOpen={isDetailModalOpen}
          onClose={() => setIsDetailModalOpen(false)}
          title={selectedDoc.title}
          description={`Format: ${selectedDoc.file_format} • Size: ${formatBytes(selectedDoc.file_size_bytes)} • Created: ${new Date(selectedDoc.created_at).toLocaleString()}`}
        >
          <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1 text-xs">
            {/* Metadata Summary */}
            <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
              <span className="font-semibold text-cyan-400 block uppercase tracking-wider text-[11px]">
                Document Metadata &amp; Citations
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-slate-300">
                {selectedDoc.doi && (
                  <div>
                    <span className="text-slate-500 block text-[10px]">DOI:</span>
                    <span className="font-mono text-cyan-300">{selectedDoc.doi}</span>
                  </div>
                )}
                {selectedDoc.journal && (
                  <div>
                    <span className="text-slate-500 block text-[10px]">Journal:</span>
                    <span>{selectedDoc.journal}</span>
                  </div>
                )}
                {selectedDoc.authors && (
                  <div className="sm:col-span-2">
                    <span className="text-slate-500 block text-[10px]">Authors:</span>
                    <span>{selectedDoc.authors}</span>
                  </div>
                )}
                {selectedDoc.source_url && (
                  <div className="sm:col-span-2">
                    <span className="text-slate-500 block text-[10px]">Source URL:</span>
                    <a
                      href={selectedDoc.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyan-400 hover:underline flex items-center gap-1"
                    >
                      {selectedDoc.source_url} <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>
                )}
                {selectedDoc.tags && (
                  <div className="sm:col-span-2 flex items-center gap-1.5 flex-wrap pt-1">
                    <span className="text-slate-500 text-[10px]">Tags:</span>
                    {selectedDoc.tags.split(',').map((t, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-[10px] text-slate-300"
                      >
                        {t.trim()}
                      </span>
                    ))}
                  </div>
                )}
                {selectedDoc.custom_metadata && (
                  <div className="sm:col-span-2 pt-1 border-t border-slate-800/60">
                    <span className="text-slate-500 block text-[10px] mb-1">Custom Key-Value Attributes:</span>
                    <pre className="p-2 rounded bg-slate-900 text-slate-300 font-mono text-[10px] overflow-x-auto">
                      {selectedDoc.custom_metadata}
                    </pre>
                  </div>
                )}
              </div>
            </div>

            {/* Extracted Chunks */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-300 uppercase tracking-wider text-[11px] font-mono">
                  Extracted Chunks in Qdrant ({selectedDoc.chunks?.length || selectedDoc.chunk_count})
                </span>
                <span className="text-[10px] font-mono text-purple-400">Sliding Window Sentence Chunker</span>
              </div>

              {isDetailLoading ? (
                <LoadingSkeleton rows={2} />
              ) : selectedDoc.chunks && selectedDoc.chunks.length > 0 ? (
                <div className="space-y-2">
                  {selectedDoc.chunks.map((chunk) => (
                    <div
                      key={chunk.id}
                      className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5"
                    >
                      <div className="flex items-center justify-between text-[10px] font-mono text-slate-500">
                        <span>Chunk #{chunk.chunk_index}</span>
                        <span>{chunk.token_count} tokens</span>
                      </div>
                      <p className="text-slate-300 leading-relaxed text-xs">
                        {chunk.chunk_text}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-4 text-center text-xs text-slate-500 bg-slate-950 rounded-xl">
                  {selectedDoc.chunk_count} chunks indexed in Qdrant vector collection.
                </div>
              )}
            </div>

            <div className="flex justify-end pt-3 border-t border-slate-800">
              <Button variant="primary" size="sm" onClick={() => setIsDetailModalOpen(false)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Delete Confirmation Modal */}
      {docToDelete && (
        <Modal
          isOpen={isDeleteModalOpen}
          onClose={() => !isDeleting && setIsDeleteModalOpen(false)}
          title="Delete Knowledge Document"
          description="Are you sure you want to delete this document? All associated chunk vectors will be purged from Qdrant and PostgreSQL immediately."
        >
          <div className="space-y-4 text-xs">
            <div className="p-3 rounded-xl bg-rose-950/30 border border-rose-800/40 text-rose-300 space-y-1">
              <p className="font-semibold">{docToDelete.title}</p>
              <p className="text-[11px] text-rose-400 font-mono">
                {docToDelete.chunk_count} chunk vectors will be removed. This action cannot be undone.
              </p>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setIsDeleteModalOpen(false)}
                disabled={isDeleting}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={handleDelete}
                isLoading={isDeleting}
              >
                Confirm Delete
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
