import React, { useState, useEffect, useRef } from 'react';
import {
  Database,
  UploadCloud,
  FileSpreadsheet,
  CheckCircle2,
  Trash2,
  AlertCircle,
  Eye,
  Activity,
  Layers,
  ChevronLeft,
  ChevronRight,
  Check,
  X,
  Sliders,
} from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import {
  Dataset,
  DatasetInspection,
  DatasetPreview,
  QualityAssessmentResult,
} from '../../types';
import { useAuth } from '../../context/AuthContext';
import { Badge } from '../../components/common/Badge';
import { EmptyState } from '../../components/common/EmptyState';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

type ActiveTab = 'overview' | 'preview' | 'quality' | 'groups';

export const DatasetsPage: React.FC = () => {
  const { user } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Detail Modal / Drawer state
  const [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [inspectionData, setInspectionData] = useState<DatasetInspection | null>(null);
  const [previewData, setPreviewData] = useState<DatasetPreview | null>(null);
  const [qualityData, setQualityData] = useState<QualityAssessmentResult | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Preview Pagination
  const [rowPage, setRowPage] = useState(1);
  const [colPage, setColPage] = useState(1);

  // Group Mapping State
  const [groupMappings, setGroupMappings] = useState<Record<string, string>>({});
  const [controlGroup, setControlGroup] = useState('Control');
  const [treatmentGroup, setTreatmentGroup] = useState('Treatment');
  const [isSavingGroups, setIsSavingGroups] = useState(false);
  const [groupSaveMessage, setGroupSaveMessage] = useState<string | null>(null);

  // Provenance Form State
  const [metaTitle, setMetaTitle] = useState('');
  const [metaOrganism, setMetaOrganism] = useState('');
  const [metaTissue, setMetaTissue] = useState('');
  const [metaCondition, setMetaCondition] = useState('');
  const [metaMeasurementType, setMetaMeasurementType] = useState('');
  const [isSavingMeta, setIsSavingMeta] = useState(false);
  const [metaSaveMessage, setMetaSaveMessage] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchDatasets = async () => {
    try {
      setIsLoading(true);
      const res = await apiClient.get<Dataset[]>('/datasets');
      setDatasets(res.data);
    } catch (err) {
      setUploadError(formatErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDatasets();
  }, []);

  const handleFileUpload = async (file: File) => {
    setUploadError(null);
    setUploadSuccess(null);

    const allowed = ['.csv', '.tsv', '.txt', '.gct'];
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (!allowed.includes(ext)) {
      setUploadError(
        `Unsupported format (${ext}). Supported formats: ${allowed.join(', ')}.`
      );
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    setIsUploading(true);
    try {
      const res = await apiClient.post<Dataset>('/datasets/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setDatasets([res.data, ...datasets]);
      setUploadSuccess(
        `Dataset "${file.name}" uploaded and parsed (${res.data.feature_count ?? 0} features × ${res.data.sample_count ?? 0} samples).`
      );
    } catch (err) {
      setUploadError(formatErrorMessage(err));
    } finally {
      setIsUploading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFileUpload(file);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      handleFileUpload(file);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('Are you sure you want to delete this dataset? This action cannot be undone.')) {
      return;
    }
    try {
      await apiClient.delete(`/datasets/${id}`);
      setDatasets(datasets.filter((d) => d.id !== id));
      if (selectedDataset?.id === id) {
        setSelectedDataset(null);
      }
    } catch (err) {
      setUploadError(formatErrorMessage(err));
    }
  };

  const openDatasetModal = async (dataset: Dataset, initialTab: ActiveTab = 'overview') => {
    setSelectedDataset(dataset);
    setActiveTab(initialTab);
    setDetailError(null);
    setGroupSaveMessage(null);
    setMetaSaveMessage(null);
    setRowPage(1);
    setColPage(1);

    // Initialize metadata form
    setMetaTitle(dataset.title || dataset.original_name);
    setMetaOrganism(dataset.organism || 'Homo sapiens');
    setMetaTissue(dataset.tissue || '');
    setMetaCondition(dataset.experimental_condition || '');
    setMetaMeasurementType(dataset.measurement_type || 'RNA-Seq Expression');

    loadDatasetDetails(dataset.id, 1, 1);
  };

  const loadDatasetDetails = async (id: string, rPage: number, cPage: number) => {
    setIsDetailLoading(true);
    try {
      const [inspRes, prevRes, qualRes] = await Promise.all([
        apiClient.get<DatasetInspection>(`/datasets/${id}/inspection`),
        apiClient.get<DatasetPreview>(`/datasets/${id}/preview?row_page=${rPage}&row_limit=30&col_page=${cPage}&col_limit=15`),
        apiClient.get<QualityAssessmentResult>(`/datasets/${id}/quality`),
      ]);
      setInspectionData(inspRes.data);
      setPreviewData(prevRes.data);
      setQualityData(qualRes.data);

      // Pre-fill group mappings if existing
      if (qualRes.data.group_validation?.groups) {
        const existing: Record<string, string> = {};
        if (qualRes.data.pca?.coordinates) {
          qualRes.data.pca.coordinates.forEach((c) => {
            if (c.group) existing[c.sample_id] = c.group;
          });
        }
        setGroupMappings(existing);
      }
    } catch (err) {
      setDetailError(formatErrorMessage(err));
    } finally {
      setIsDetailLoading(false);
    }
  };

  const handlePageChange = async (newRowPage: number, newColPage: number) => {
    if (!selectedDataset) return;
    setRowPage(newRowPage);
    setColPage(newColPage);
    try {
      const res = await apiClient.get<DatasetPreview>(
        `/datasets/${selectedDataset.id}/preview?row_page=${newRowPage}&row_limit=30&col_page=${newColPage}&col_limit=15`
      );
      setPreviewData(res.data);
    } catch (err) {
      setDetailError(formatErrorMessage(err));
    }
  };

  const handleOrientationConfirm = async (newOrientation: 'features_as_rows' | 'samples_as_rows') => {
    if (!selectedDataset) return;
    try {
      setIsDetailLoading(true);
      const res = await apiClient.patch<Dataset>(`/datasets/${selectedDataset.id}/orientation`, {
        orientation: newOrientation,
      });
      setSelectedDataset(res.data);
      setDatasets(datasets.map((d) => (d.id === res.data.id ? res.data : d)));
      await loadDatasetDetails(res.data.id, 1, 1);
    } catch (err) {
      setDetailError(formatErrorMessage(err));
      setIsDetailLoading(false);
    }
  };

  const handleSaveMetadata = async () => {
    if (!selectedDataset) return;
    setIsSavingMeta(true);
    setMetaSaveMessage(null);
    try {
      const res = await apiClient.patch<Dataset>(`/datasets/${selectedDataset.id}/metadata`, {
        title: metaTitle,
        organism: metaOrganism,
        tissue: metaTissue,
        experimental_condition: metaCondition,
        measurement_type: metaMeasurementType,
      });
      setSelectedDataset(res.data);
      setDatasets(datasets.map((d) => (d.id === res.data.id ? res.data : d)));
      setMetaSaveMessage('Provenance metadata updated successfully.');
    } catch (err) {
      setDetailError(formatErrorMessage(err));
    } finally {
      setIsSavingMeta(false);
    }
  };

  const handleSaveGroupMappings = async () => {
    if (!selectedDataset) return;
    setIsSavingGroups(true);
    setGroupSaveMessage(null);
    try {
      await apiClient.post(`/datasets/${selectedDataset.id}/groups`, {
        group_mappings: groupMappings,
        control_group: controlGroup,
        treatment_group: treatmentGroup,
      });
      setGroupSaveMessage('Group assignments updated and statistical readiness verified.');
      // Refresh quality view
      const qualRes = await apiClient.get<QualityAssessmentResult>(`/datasets/${selectedDataset.id}/quality`);
      setQualityData(qualRes.data);
    } catch (err) {
      setDetailError(formatErrorMessage(err));
    } finally {
      setIsSavingGroups(false);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const canUpload = user?.role === 'ADMIN' || user?.role === 'RESEARCHER';

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h2 className="text-xl font-bold tracking-tight text-white">
          Scientific Dataset Library & Intelligence Engine
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Catalog, inspect matrix orientation, evaluate quality distributions, and validate sample readiness for statistical experiments.
        </p>
      </div>

      {/* Upload Zone (Researchers & Admins) */}
      {canUpload && (
        <section className="space-y-3">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            className={`rounded-2xl border-2 border-dashed p-8 text-center transition-all ${
              isDragging
                ? 'border-cyan-400 bg-cyan-950/20'
                : 'border-slate-800 bg-slate-900/40 hover:border-slate-700/80'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.txt,.gct"
              onChange={handleFileChange}
              className="hidden"
            />
            <div className="flex flex-col items-center justify-center space-y-3">
              <div className="h-12 w-12 rounded-xl bg-slate-800/80 border border-slate-700/60 flex items-center justify-center text-cyan-400 shadow-inner">
                <UploadCloud className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-semibold text-white">
                  Drag and drop your gene-expression file, or{' '}
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="text-cyan-400 hover:text-cyan-300 underline font-medium"
                  >
                    browse files
                  </button>
                </p>
                <p className="text-xs text-slate-400">
                  Accepted scientific formats: <strong>.csv</strong>, <strong>.tsv</strong>, <strong>.txt</strong>, <strong>.gct (1.2/1.3)</strong> (up to 25 MB)
                </p>
              </div>

              {isUploading && (
                <div className="flex items-center gap-2 text-xs text-cyan-400 font-medium pt-2">
                  <div className="h-4 w-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                  <span>Parsing scientific matrix, evaluating orientation & quality...</span>
                </div>
              )}
            </div>
          </div>

          {/* Validation Notice */}
          <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-start gap-3 text-xs text-slate-400">
            <AlertCircle className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <span className="font-semibold text-slate-300 block">
                Deterministic Inspection & Statistical Integrity:
              </span>
              <p className="text-[11px] leading-relaxed">
                Files are strictly inspected without hallucination or simulated values. We detect matrix dimensions, calculate SHA-256 integrity hashes, identify scale distribution (log2 vs raw counts), and verify sample group sizes (minimum 3 samples per group for Welch's t-test).
              </p>
            </div>
          </div>

          {uploadError && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
              {uploadError}
            </div>
          )}

          {uploadSuccess && (
            <div className="p-3 rounded-lg bg-emerald-950/40 border border-emerald-800/60 text-xs text-emerald-300 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{uploadSuccess}</span>
            </div>
          )}
        </section>
      )}

      {/* Dataset List */}
      <section className="space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Cataloged Datasets ({datasets.length})
        </h3>

        {isLoading ? (
          <LoadingSkeleton rows={3} />
        ) : datasets.length === 0 ? (
          <EmptyState
            icon={<Database className="w-6 h-6" />}
            title="No datasets cataloged yet"
            description="Upload transcriptomic profile files to inspect orientation, evaluate distributions, and prepare for ML experiments."
            actionLabel={canUpload ? 'Upload First Dataset' : undefined}
            onAction={canUpload ? () => fileInputRef.current?.click() : undefined}
            actionIcon={<UploadCloud className="w-4 h-4" />}
          />
        ) : (
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden shadow-lg">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900/80 border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Dataset Name & Provenance</th>
                    <th className="py-3 px-4">Format</th>
                    <th className="py-3 px-4">Size</th>
                    <th className="py-3 px-4">Dimensions</th>
                    <th className="py-3 px-4">Orientation</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-200">
                  {datasets.map((d) => (
                    <tr key={d.id} className="hover:bg-slate-800/30 transition-colors">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <FileSpreadsheet className="w-4 h-4 text-cyan-400 shrink-0" />
                          <div>
                            <div className="flex items-center gap-1.5">
                              <button
                                onClick={() => openDatasetModal(d, 'overview')}
                                className="font-medium text-white hover:text-cyan-300 transition-colors text-left font-sans truncate max-w-xs block"
                              >
                                {d.title || d.original_name}
                              </button>
                              {d.is_synthetic && (
                                <Badge variant="amber" size="sm">
                                  Benchmark
                                </Badge>
                              )}
                            </div>
                            <span className="text-[10px] text-slate-400 font-mono">
                              {d.organism || 'Homo sapiens'} {d.tissue ? `• ${d.tissue}` : ''}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-4 font-mono text-cyan-300">
                        {d.file_format}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-400">
                        {formatFileSize(d.file_size_bytes)}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-300">
                        {d.feature_count !== null && d.sample_count !== null
                          ? `${d.feature_count} features × ${d.sample_count} samples`
                          : 'Unparsed'}
                      </td>
                      <td className="py-3 px-4">
                        <span className="font-mono text-[11px] text-slate-300 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700/50">
                          {d.matrix_orientation === 'samples_as_rows'
                            ? 'Samples × Features'
                            : 'Features × Samples'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <Badge
                          variant={
                            d.status === 'Validated'
                              ? 'emerald'
                              : d.status.includes('Needs')
                              ? 'amber'
                              : 'slate'
                          }
                          size="sm"
                        >
                          {d.status}
                        </Badge>
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => openDatasetModal(d, 'overview')}
                            className="p-1 rounded text-slate-400 hover:text-cyan-300 hover:bg-slate-800 transition-colors"
                            title="Inspect & Quality Assessment"
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => openDatasetModal(d, 'groups')}
                            className="p-1 rounded text-slate-400 hover:text-purple-300 hover:bg-slate-800 transition-colors"
                            title="Experimental Groups"
                          >
                            <Layers className="w-4 h-4" />
                          </button>
                          {(user?.role === 'ADMIN' || d.owner_id === user?.id) && (
                            <button
                              onClick={() => handleDelete(d.id)}
                              className="p-1 rounded text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                              title="Delete dataset"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* Dataset Inspection & Intelligence Modal */}
      {selectedDataset && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-cyan-950/60 border border-cyan-800/60 flex items-center justify-center text-cyan-400">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-white flex items-center gap-2">
                    {selectedDataset.title || selectedDataset.original_name}
                    <Badge variant="cyan" size="sm">
                      {selectedDataset.file_format}
                    </Badge>
                    {selectedDataset.is_synthetic && (
                      <Badge variant="amber" size="sm">
                        Synthetic Benchmark
                      </Badge>
                    )}
                  </h3>
                  <p className="text-xs text-slate-400 font-mono">
                    SHA-256: {selectedDataset.content_hash ? `${selectedDataset.content_hash.substring(0, 16)}...` : 'N/A'} • {selectedDataset.feature_count} features × {selectedDataset.sample_count} samples
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSelectedDataset(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Navigation Tabs */}
            <div className="flex border-b border-slate-800 px-6 bg-slate-950/40">
              <button
                onClick={() => setActiveTab('overview')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${
                  activeTab === 'overview'
                    ? 'border-cyan-400 text-cyan-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Sliders className="w-4 h-4" />
                Orientation & Provenance
              </button>
              <button
                onClick={() => setActiveTab('preview')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${
                  activeTab === 'preview'
                    ? 'border-cyan-400 text-cyan-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Eye className="w-4 h-4" />
                Data Preview
              </button>
              <button
                onClick={() => setActiveTab('quality')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${
                  activeTab === 'quality'
                    ? 'border-cyan-400 text-cyan-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Activity className="w-4 h-4" />
                Quality & Distributions
              </button>
              <button
                onClick={() => setActiveTab('groups')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${
                  activeTab === 'groups'
                    ? 'border-cyan-400 text-cyan-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Layers className="w-4 h-4" />
                Experimental Groups
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto flex-1 space-y-6">
              {detailError && (
                <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
                  {detailError}
                </div>
              )}

              {isDetailLoading ? (
                <div className="py-12 flex flex-col items-center justify-center space-y-3">
                  <div className="h-8 w-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                  <p className="text-xs text-slate-400">Loading dataset intelligence...</p>
                </div>
              ) : (
                <>
                  {/* TAB 1: OVERVIEW & PROVENANCE */}
                  {activeTab === 'overview' && (
                    <div className="space-y-6">
                      {/* Cohort Classification Banner */}
                      <div
                        className={`rounded-xl border p-4 flex items-start gap-3 ${
                          selectedDataset.is_synthetic
                            ? 'border-amber-500/30 bg-amber-950/20 text-amber-200'
                            : 'border-emerald-500/30 bg-emerald-950/20 text-emerald-200'
                        }`}
                      >
                        <div className="p-2 rounded-lg bg-slate-900/60 shrink-0">
                          <Activity
                            className={`w-4 h-4 ${
                              selectedDataset.is_synthetic ? 'text-amber-400' : 'text-emerald-400'
                            }`}
                          />
                        </div>
                        <div className="text-xs">
                          <p className="font-semibold">
                            Cohort Type:{' '}
                            {selectedDataset.is_synthetic
                              ? 'Synthetic Benchmark / Simulated In-Silico Cohort'
                              : 'Empirical Observational / Clinical Cohort'}
                          </p>
                          <p className="text-slate-300 mt-1 leading-relaxed">
                            {selectedDataset.is_synthetic
                              ? 'This dataset contains synthetically generated or calibrated benchmark matrices for algorithm validation and pipeline testing. Results must be treated as computational benchmarks rather than clinical discoveries.'
                              : 'This dataset is classified as an empirical research cohort. Statistical findings represent observational genomic correlations and require orthogonal wet-lab/in-vitro experimental validation.'}
                          </p>
                        </div>
                      </div>

                      {/* Matrix Orientation Card */}
                      <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-5 space-y-4">
                        <div className="flex items-start justify-between">
                          <div>
                            <h4 className="text-sm font-semibold text-white flex items-center gap-2">
                              Matrix Orientation Assessment
                              <span className="text-[11px] font-normal text-slate-400">
                                (Confidence: {inspectionData?.orientation_confidence ? `${Math.round(inspectionData.orientation_confidence * 100)}%` : 'N/A'})
                              </span>
                            </h4>
                            <p className="text-xs text-slate-400 mt-1">
                              {inspectionData?.orientation_reasoning || 'Orientation inferred from identifier regexes and dimension ratios.'}
                            </p>
                          </div>
                          <Badge
                            variant={
                              selectedDataset.matrix_orientation === 'features_as_rows'
                                ? 'cyan'
                                : 'purple'
                            }
                          >
                            Current: {selectedDataset.matrix_orientation === 'features_as_rows' ? 'Genes as Rows' : 'Samples as Rows'}
                          </Badge>
                        </div>

                        {canUpload && (
                          <div className="pt-2 border-t border-slate-800/60 flex items-center gap-3">
                            <span className="text-xs text-slate-300 font-medium">Override Orientation:</span>
                            <button
                              onClick={() => handleOrientationConfirm('features_as_rows')}
                              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                                selectedDataset.matrix_orientation === 'features_as_rows'
                                  ? 'bg-cyan-500 text-slate-950 font-semibold'
                                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                              }`}
                            >
                              Features as Rows (Genes × Samples)
                            </button>
                            <button
                              onClick={() => handleOrientationConfirm('samples_as_rows')}
                              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                                selectedDataset.matrix_orientation === 'samples_as_rows'
                                  ? 'bg-cyan-500 text-slate-950 font-semibold'
                                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                              }`}
                            >
                              Samples as Rows (Samples × Features)
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Scientific Provenance Form */}
                      <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-5 space-y-4">
                        <h4 className="text-sm font-semibold text-white">
                          Scientific Provenance & Biological Context
                        </h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                          <div className="space-y-1">
                            <label className="text-slate-400 font-medium">Dataset Title</label>
                            <input
                              type="text"
                              value={metaTitle}
                              onChange={(e) => setMetaTitle(e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-cyan-400"
                              placeholder="e.g. TCGA-BRCA Breast Invasive Carcinoma"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="text-slate-400 font-medium">Organism</label>
                            <input
                              type="text"
                              value={metaOrganism}
                              onChange={(e) => setMetaOrganism(e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-cyan-400"
                              placeholder="e.g. Homo sapiens"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="text-slate-400 font-medium">Tissue / Cell Type</label>
                            <input
                              type="text"
                              value={metaTissue}
                              onChange={(e) => setMetaTissue(e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-cyan-400"
                              placeholder="e.g. Mammary epithelial tissue"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="text-slate-400 font-medium">Measurement Type</label>
                            <input
                              type="text"
                              value={metaMeasurementType}
                              onChange={(e) => setMetaMeasurementType(e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-cyan-400"
                              placeholder="e.g. RNA-Seq log2(TPM+1)"
                            />
                          </div>
                          <div className="space-y-1 md:col-span-2">
                            <label className="text-slate-400 font-medium">Experimental Condition</label>
                            <input
                              type="text"
                              value={metaCondition}
                              onChange={(e) => setMetaCondition(e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-cyan-400"
                              placeholder="e.g. Primary Solid Tumor vs Solid Tissue Normal"
                            />
                          </div>
                        </div>

                        {canUpload && (
                          <div className="flex items-center justify-between pt-2">
                            {metaSaveMessage ? (
                              <span className="text-xs text-emerald-400 flex items-center gap-1">
                                <Check className="w-3.5 h-3.5" />
                                {metaSaveMessage}
                              </span>
                            ) : <div />}
                            <button
                              onClick={handleSaveMetadata}
                              disabled={isSavingMeta}
                              className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs transition-colors disabled:opacity-50"
                            >
                              {isSavingMeta ? 'Saving...' : 'Save Provenance'}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* TAB 2: DATA PREVIEW */}
                  {activeTab === 'preview' && (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between text-xs text-slate-400">
                        <span>
                          Showing rows {((rowPage - 1) * (previewData?.row_page_size || 30)) + 1} to{' '}
                          {Math.min(rowPage * (previewData?.row_page_size || 30), previewData?.total_rows || 0)} of{' '}
                          {previewData?.total_rows} • Columns {((colPage - 1) * (previewData?.col_page_size || 15)) + 1} to{' '}
                          {Math.min(colPage * (previewData?.col_page_size || 15), previewData?.total_cols || 0)} of{' '}
                          {previewData?.total_cols}
                        </span>

                        {/* Pagination buttons */}
                        <div className="flex items-center gap-3">
                          <div className="flex items-center gap-1">
                            <span className="text-[11px] text-slate-500 mr-1">Rows:</span>
                            <button
                              onClick={() => handlePageChange(Math.max(1, rowPage - 1), colPage)}
                              disabled={rowPage <= 1}
                              className="p-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-white"
                            >
                              <ChevronLeft className="w-3.5 h-3.5" />
                            </button>
                            <span className="text-slate-300 font-mono px-1">p.{rowPage}</span>
                            <button
                              onClick={() => handlePageChange(rowPage + 1, colPage)}
                              disabled={(rowPage * (previewData?.row_page_size || 30)) >= (previewData?.total_rows || 0)}
                              className="p-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-white"
                            >
                              <ChevronRight className="w-3.5 h-3.5" />
                            </button>
                          </div>

                          <div className="flex items-center gap-1">
                            <span className="text-[11px] text-slate-500 mr-1">Cols:</span>
                            <button
                              onClick={() => handlePageChange(rowPage, Math.max(1, colPage - 1))}
                              disabled={colPage <= 1}
                              className="p-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-white"
                            >
                              <ChevronLeft className="w-3.5 h-3.5" />
                            </button>
                            <span className="text-slate-300 font-mono px-1">p.{colPage}</span>
                            <button
                              onClick={() => handlePageChange(rowPage, colPage + 1)}
                              disabled={(colPage * (previewData?.col_page_size || 15)) >= (previewData?.total_cols || 0)}
                              className="p-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-white"
                            >
                              <ChevronRight className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>

                      {/* Paginated Matrix Table */}
                      <div className="rounded-xl border border-slate-800 bg-slate-950/60 overflow-hidden">
                        <div className="overflow-x-auto max-h-[500px]">
                          <table className="w-full text-left text-[11px] font-mono">
                            <thead className="bg-slate-900 border-b border-slate-800 text-slate-400 sticky top-0 z-10">
                              <tr>
                                {previewData?.columns.map((col, idx) => (
                                  <th key={idx} className="py-2.5 px-3 whitespace-nowrap">
                                    {col === '_row_id' ? 'Identifier' : col}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/40 text-slate-200">
                              {previewData?.rows.map((row, rIdx) => (
                                <tr key={rIdx} className="hover:bg-slate-800/20">
                                  {previewData.columns.map((col, cIdx) => (
                                    <td
                                      key={cIdx}
                                      className={`py-2 px-3 whitespace-nowrap ${
                                        col === '_row_id'
                                          ? 'font-semibold text-cyan-300 bg-slate-900/40'
                                          : 'text-slate-300'
                                      }`}
                                    >
                                      {row[col] !== null && row[col] !== undefined
                                        ? typeof row[col] === 'number'
                                          ? row[col].toFixed(3)
                                          : String(row[col])
                                        : <span className="text-slate-600">NaN</span>}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* TAB 3: QUALITY ASSESSMENT & DISTRIBUTIONS */}
                  {activeTab === 'quality' && qualityData && (
                    <div className="space-y-6">
                      {/* Health Status & Scale Overview */}
                      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                          <span className="text-[11px] text-slate-400 uppercase font-semibold">Health Status</span>
                          <div className="flex items-center gap-2 pt-1">
                            <Badge
                              variant={
                                qualityData.overall_health_status === 'Excellent'
                                  ? 'emerald'
                                  : qualityData.overall_health_status === 'Good'
                                  ? 'cyan'
                                  : 'amber'
                              }
                            >
                              {qualityData.overall_health_status}
                            </Badge>
                          </div>
                        </div>

                        <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                          <span className="text-[11px] text-slate-400 uppercase font-semibold">Missingness</span>
                          <p className="text-base font-bold font-mono text-white pt-1">
                            {qualityData.missing_cells_percent}%
                          </p>
                          <span className="text-[10px] text-slate-500">
                            {qualityData.missing_cells_count} of {qualityData.total_cells} cells
                          </span>
                        </div>

                        <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                          <span className="text-[11px] text-slate-400 uppercase font-semibold">Sparsity</span>
                          <p className="text-base font-bold font-mono text-white pt-1">
                            {qualityData.distribution.sparsity_percent}%
                          </p>
                          <span className="text-[10px] text-slate-500">
                            Exact zero values
                          </span>
                        </div>

                        <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                          <span className="text-[11px] text-slate-400 uppercase font-semibold">Zero Variance</span>
                          <p className="text-base font-bold font-mono text-white pt-1">
                            {qualityData.constant_features_count}
                          </p>
                          <span className="text-[10px] text-slate-500">
                            Constant / uninformative genes
                          </span>
                        </div>
                      </div>

                      {/* Scale Inference & Statistical Appropriateness Alert */}
                      <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 space-y-2">
                        <div className="flex items-center justify-between">
                          <h5 className="text-xs font-semibold text-white flex items-center gap-2">
                            <Activity className="w-4 h-4 text-cyan-400" />
                            Data Scale Inference: <span className="font-mono text-cyan-300">{qualityData.distribution.scale_inference}</span>
                          </h5>
                          <span className="text-[11px] font-mono text-slate-400">
                            Range: [{qualityData.distribution.min_val}, {qualityData.distribution.max_val}]
                          </span>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed">
                          {qualityData.distribution.scale_explanation}
                        </p>
                      </div>

                      {/* Outlier Alert Banner */}
                      {qualityData.potential_outliers.length > 0 && (
                        <div className="p-4 rounded-xl border border-amber-900/60 bg-amber-950/30 text-amber-200 text-xs space-y-1">
                          <span className="font-semibold flex items-center gap-1.5 text-amber-300">
                            <AlertCircle className="w-4 h-4" />
                            Potential Sample Quality Concerns ({qualityData.potential_outliers.length} samples)
                          </span>
                          <p className="text-[11px] text-amber-300/80 leading-relaxed">
                            The following samples exhibit inter-sample Pearson correlation &gt;2 standard deviations below the cohort mean:
                            <strong> {qualityData.potential_outliers.join(', ')}</strong>. Note: this flag is advisory and non-fatal; review biological metadata or batch effects before discarding.
                          </p>
                        </div>
                      )}

                      {/* PCA Projection Scatter (2D) */}
                      {qualityData.pca && (
                        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-5 space-y-3">
                          <div className="flex items-center justify-between">
                            <h5 className="text-xs font-semibold text-white">
                              Principal Component Analysis (PCA)
                            </h5>
                            <span className="text-[11px] font-mono text-cyan-400">
                              PC1: {(qualityData.pca.pc1_variance_ratio * 100).toFixed(1)}% var • PC2: {(qualityData.pca.pc2_variance_ratio * 100).toFixed(1)}% var
                            </span>
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 pt-2">
                            {qualityData.pca.coordinates.slice(0, 16).map((coord, idx) => (
                              <div
                                key={idx}
                                className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-mono space-y-0.5"
                              >
                                <span className="font-semibold text-slate-200 truncate block">
                                  {coord.sample_id}
                                </span>
                                <div className="text-[10px] text-slate-400 flex justify-between">
                                  <span>PC1: {coord.pc1.toFixed(2)}</span>
                                  <span>PC2: {coord.pc2.toFixed(2)}</span>
                                </div>
                                {coord.group && (
                                  <span className="inline-block text-[9px] px-1.5 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-800/50 mt-1">
                                    {coord.group}
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 4: EXPERIMENTAL GROUPS */}
                  {activeTab === 'groups' && (
                    <div className="space-y-6">
                      {/* Statistical Readiness Banner */}
                      {qualityData?.group_validation && (
                        <div className={`p-4 rounded-xl border text-xs space-y-2 ${
                          qualityData.group_validation.readiness_state === 'ready_for_exploratory_analysis' ||
                          qualityData.group_validation.readiness_state === 'analysis_completed'
                            ? 'bg-emerald-950/30 border-emerald-800/60 text-emerald-200'
                            : qualityData.group_validation.readiness_state === 'unsupported_data_type'
                            ? 'bg-rose-950/30 border-rose-800/60 text-rose-200'
                            : 'bg-amber-950/30 border-amber-800/60 text-amber-200'
                        }`}>
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              {qualityData.group_validation.readiness_state === 'ready_for_exploratory_analysis' ||
                              qualityData.group_validation.readiness_state === 'analysis_completed' ? (
                                <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                              ) : (
                                <AlertCircle className="w-5 h-5 text-amber-400 shrink-0" />
                              )}
                              <div>
                                <span className="font-semibold text-sm block">
                                  Readiness State: <span className="font-mono">{qualityData.group_validation.readiness_state}</span>
                                </span>
                                <span className="text-[11px] text-slate-300">
                                  {qualityData.group_validation.readiness_state === 'ready_for_exploratory_analysis'
                                    ? 'Valid for exploratory two-sample Welch t-test screening (conditional readiness).'
                                    : qualityData.group_validation.readiness_state === 'unsupported_data_type'
                                    ? 'Incompatible data scale (raw counts require count-based DESeq2 modeling).'
                                    : qualityData.group_validation.readiness_state === 'insufficient_samples'
                                    ? 'Insufficient sample size (minimum 3 independent biological samples per group required).'
                                    : 'Experimental annotations incomplete or unsupported design.'}
                                </span>
                              </div>
                            </div>
                            <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-900 border border-slate-700 text-slate-300">
                              Assigned: {qualityData.group_validation.assigned_samples_count ?? Object.values(groupMappings).filter(Boolean).length} / {inspectionData?.sample_identifiers.length || 0}
                            </span>
                          </div>

                          {qualityData.group_validation.warnings.map((w, i) => (
                            <p key={i} className="text-[11px] leading-relaxed text-amber-300/90 pl-7">
                              • {w}
                            </p>
                          ))}

                          {qualityData.group_validation.recommendations.map((r, i) => (
                            <p key={i} className="text-[11px] leading-relaxed text-slate-300 pl-7">
                              💡 {r}
                            </p>
                          ))}

                          {/* Explicit Scientific Caveats */}
                          <div className="mt-2 pt-2 border-t border-slate-800/60 pl-7 space-y-1 text-[10px] text-slate-400 italic">
                            <p>
                              Note: Statistical readiness for exploratory screening indicates structural compatibility with Welch's t-test ($N \ge 3$ per group on continuous data). It does not guarantee statistical power, biological validity, or generalizability. Confirmatory testing and orthogonal biological validation are strictly required.
                            </p>
                          </div>
                        </div>
                      )}

                      {/* Primary Comparison Groups */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-1 text-xs">
                          <label className="text-slate-400 font-medium">Control / Baseline Group Name</label>
                          <input
                            type="text"
                            value={controlGroup}
                            onChange={(e) => setControlGroup(e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-sans text-xs focus:outline-none focus:border-cyan-400"
                          />
                        </div>
                        <div className="space-y-1 text-xs">
                          <label className="text-slate-400 font-medium">Treatment / Condition Group Name</label>
                          <input
                            type="text"
                            value={treatmentGroup}
                            onChange={(e) => setTreatmentGroup(e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-sans text-xs focus:outline-none focus:border-cyan-400"
                          />
                        </div>
                      </div>

                      {/* Sample Assignment Table */}
                      <div className="rounded-xl border border-slate-800 bg-slate-950/40 overflow-hidden">
                        <div className="p-3 bg-slate-900/80 border-b border-slate-800 flex items-center justify-between text-xs">
                          <div className="space-y-0.5">
                            <span className="font-semibold text-white block">
                              Assign Samples to Comparison Groups ({inspectionData?.sample_identifiers.length || 0} total)
                            </span>
                            <span className="text-[10px] text-slate-400 font-mono">
                              {controlGroup}: {Object.values(groupMappings).filter((g) => g === controlGroup).length} • {treatmentGroup}: {Object.values(groupMappings).filter((g) => g === treatmentGroup).length} • Unassigned: {(inspectionData?.sample_identifiers.length || 0) - Object.values(groupMappings).filter((g) => g === controlGroup || g === treatmentGroup).length}
                            </span>
                          </div>
                          <div className="flex gap-2">
                            <button
                              onClick={() => {
                                setGroupMappings({});
                              }}
                              className="text-[11px] text-slate-400 hover:text-slate-200 underline"
                            >
                              Clear All
                            </button>
                          </div>
                        </div>

                        <div className="max-h-72 overflow-y-auto divide-y divide-slate-800/40">
                          {inspectionData?.sample_identifiers.map((sid) => {
                            const currentGrp = groupMappings[sid];
                            return (
                              <div
                                key={sid}
                                className="px-4 py-2 flex items-center justify-between text-xs font-mono hover:bg-slate-800/20"
                              >
                                <span className="text-slate-300">{sid}</span>
                                <div className="flex items-center gap-1.5">
                                  <button
                                    onClick={() =>
                                      setGroupMappings({
                                        ...groupMappings,
                                        [sid]: controlGroup,
                                      })
                                    }
                                    className={`px-2.5 py-1 rounded text-[11px] font-sans font-medium transition-colors ${
                                      currentGrp === controlGroup
                                        ? 'bg-blue-600 text-white font-semibold'
                                        : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                                    }`}
                                  >
                                    {controlGroup}
                                  </button>
                                  <button
                                    onClick={() =>
                                      setGroupMappings({
                                        ...groupMappings,
                                        [sid]: treatmentGroup,
                                      })
                                    }
                                    className={`px-2.5 py-1 rounded text-[11px] font-sans font-medium transition-colors ${
                                      currentGrp === treatmentGroup
                                        ? 'bg-purple-600 text-white font-semibold'
                                        : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                                    }`}
                                  >
                                    {treatmentGroup}
                                  </button>
                                  <button
                                    onClick={() => {
                                      const updated = { ...groupMappings };
                                      delete updated[sid];
                                      setGroupMappings(updated);
                                    }}
                                    className={`px-2 py-1 rounded text-[11px] font-sans font-medium transition-colors ${
                                      !currentGrp
                                        ? 'bg-slate-700 text-slate-200 font-semibold'
                                        : 'bg-slate-900 text-slate-500 hover:bg-slate-800'
                                    }`}
                                    title="Leave sample unassigned"
                                  >
                                    Unassigned
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      {canUpload && (
                        <div className="flex items-center justify-between pt-2">
                          {groupSaveMessage ? (
                            <span className="text-xs text-emerald-400 flex items-center gap-1">
                              <Check className="w-3.5 h-3.5" />
                              {groupSaveMessage}
                            </span>
                          ) : <div />}
                          <button
                            onClick={handleSaveGroupMappings}
                            disabled={isSavingGroups}
                            className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs transition-colors disabled:opacity-50"
                          >
                            {isSavingGroups ? 'Validating...' : 'Save & Validate Groups'}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
