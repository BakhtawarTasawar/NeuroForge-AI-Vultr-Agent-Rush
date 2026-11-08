import React, { useState, useEffect } from 'react';
import {
  FlaskConical,
  Play,
  Shield,
  AlertTriangle,
  Download,
  Trash2,
  Eye,
  Activity,
  FileText,
  CheckCircle2,
  X,
  ChevronLeft,
  ChevronRight,
  Search,
  Sliders,
  Layers,
  Table,
  ArrowLeftRight,
} from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import {
  Experiment,
  Project,
  Dataset,
  ExperimentResultsDetail,
  ExperimentComparison,
} from '../../types';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { Modal } from '../../components/common/Modal';
import { Badge } from '../../components/common/Badge';
import { EmptyState } from '../../components/common/EmptyState';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

type DetailTab = 'summary' | 'plots' | 'table' | 'reproducibility' | 'diagnostics';

export const ExperimentsPage: React.FC = () => {
  const { user } = useAuth();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal states
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [selectedExp, setSelectedExp] = useState<Experiment | null>(null);
  const [activeDetailTab, setActiveDetailTab] = useState<DetailTab>('summary');

  // Detailed results state
  const [resultsDetail, setResultsDetail] = useState<ExperimentResultsDetail | null>(null);
  const [isLoadingResults, setIsLoadingResults] = useState(false);
  const [resultsPage, setResultsPage] = useState(1);
  const [resultsSearch, setResultsSearch] = useState('');
  const [resultsSortBy, setResultsSortBy] = useState('adj_p_value');
  const [resultsSortDir, setResultsSortDir] = useState<'asc' | 'desc'>('asc');

  // Experiment Comparison State
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);
  const [comparisonData, setComparisonData] = useState<ExperimentComparison | null>(null);
  const [isCompareOpen, setIsCompareOpen] = useState(false);
  const [isLoadingCompare, setIsLoadingCompare] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  // New Experiment Form
  const [launchMode, setLaunchMode] = useState<'differential_expression' | 'custom_script'>('differential_expression');
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [customCode, setCustomCode] = useState('');

  // Guided Differential Expression Form Parameters
  const [groupAName, setGroupAName] = useState('Control');
  const [groupBName, setGroupBName] = useState('Treatment');
  const [sampleMappings, setSampleMappings] = useState<Record<string, string>>({});
  const [fdrThreshold, setFdrThreshold] = useState<number>(0.05);
  const [datasetSamples, setDatasetSamples] = useState<string[]>([]);
  const [datasetOrientation, setDatasetOrientation] = useState<string>('features_as_rows');
  const [datasetScale, setDatasetScale] = useState<string>('log2_transformed');

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchInitialData = async () => {
    try {
      setIsLoading(true);
      const [expRes, projRes, dataRes] = await Promise.all([
        apiClient.get<Experiment[]>('/experiments'),
        apiClient.get<Project[]>('/projects'),
        apiClient.get<Dataset[]>('/datasets'),
      ]);
      setExperiments(expRes.data);
      // Backend now enforces tenant isolation — use the response directly.
      const accessibleProjects = projRes.data;
      setProjects(accessibleProjects);
      setDatasets(dataRes.data);
      if (accessibleProjects.length > 0) {
        setSelectedProjectId(accessibleProjects[0].id);
      }
      if (dataRes.data.length > 0) {
        handleDatasetSelect(dataRes.data[0].id, dataRes.data);
      }
      setError(null);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchInitialData();
  }, []);

  const handleDatasetSelect = async (datasetId: string, currentDatasets: Dataset[] = datasets) => {
    setSelectedDatasetId(datasetId);
    const d = currentDatasets.find((item) => item.id === datasetId);
    if (!d) return;

    setDatasetOrientation(d.matrix_orientation || 'features_as_rows');
    setGroupAName(d.control_group || 'Control');
    setGroupBName(d.treatment_group || 'Treatment');

    // Fetch deep inspection to get sample list and quality
    try {
      const [inspRes, qualRes] = await Promise.all([
        apiClient.get(`/datasets/${datasetId}/inspection`),
        apiClient.get(`/datasets/${datasetId}/quality`),
      ]);
      setDatasetSamples(inspRes.data.sample_identifiers || []);
      setDatasetScale(qualRes.data.distribution?.scale_inference || 'log2_transformed');

      // Pre-fill existing group mappings if present
      if (qualRes.data.group_validation?.groups) {
        const existing: Record<string, string> = {};
        if (qualRes.data.pca?.coordinates) {
          qualRes.data.pca.coordinates.forEach((c: { sample_id: string; group?: string }) => {
            if (c.group) existing[c.sample_id] = c.group;
          });
        }
        setSampleMappings(existing);
      } else {
        setSampleMappings({});
      }
    } catch (err) {
      console.error('Failed to load dataset details for experiment', err);
    }
  };

  const openCreateModal = () => {
    setFormError(null);
    setTitle('Two-Group Differential Expression Screen (Welch t-test)');
    setDescription('Two-sample Welch t-test with Benjamini-Hochberg FDR multiple testing correction.');
    setIsCreateOpen(true);
  };

  const handleCreateAndRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId) {
      setFormError('Please select a target research project.');
      return;
    }

    if (launchMode === 'differential_expression') {
      if (!selectedDatasetId) {
        setFormError('Please select an uploaded transcriptomic dataset.');
        return;
      }
      if (datasetScale === 'raw_counts') {
        setFormError('Raw RNA-seq counts require a validated count-based statistical workflow, such as DESeq2. This analysis is not available yet.');
        return;
      }
      if (datasetOrientation === 'ambiguous') {
        setFormError('Dataset orientation is ambiguous. Please confirm orientation in the Datasets library before running analysis.');
        return;
      }

      const countA = Object.values(sampleMappings).filter((g) => g === groupAName).length;
      const countB = Object.values(sampleMappings).filter((g) => g === groupBName).length;

      if (countA < 3 || countB < 3) {
        setFormError(`Insufficient sample size (Group '${groupAName}': ${countA}, Group '${groupBName}': ${countB}). Minimum 3 independent samples per group are required.`);
        return;
      }
    } else {
      if (!customCode.trim()) {
        setFormError('Please provide custom scientific Python code to execute.');
        return;
      }
    }

    setIsSubmitting(true);
    setFormError(null);

    try {
      const payload: Record<string, any> = {
        title: title.trim(),
        description: description.trim() || null,
        dataset_id: selectedDatasetId || null,
        experiment_type: launchMode === 'differential_expression' ? 'differential_expression_welch' : 'custom_script',
      };

      if (launchMode === 'differential_expression') {
        payload.group_a_name = groupAName;
        payload.group_b_name = groupBName;
        payload.group_mappings = sampleMappings;
        payload.fdr_threshold = fdrThreshold;
        payload.alpha = 0.05;
      } else {
        payload.code = customCode;
      }

      const res = await apiClient.post<Experiment>(
        `/projects/${selectedProjectId}/experiments`,
        payload
      );

      setExperiments([res.data, ...experiments]);
      setIsCreateOpen(false);
      openDetailModal(res.data);
    } catch (err) {
      setFormError(formatErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleSelectForCompare = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (selectedForCompare.includes(id)) {
      setSelectedForCompare(selectedForCompare.filter((item) => item !== id));
    } else {
      if (selectedForCompare.length < 2) {
        setSelectedForCompare([...selectedForCompare, id]);
      } else {
        setSelectedForCompare([selectedForCompare[1], id]);
      }
    }
  };

  const handleLaunchCompare = async () => {
    if (selectedForCompare.length !== 2) return;
    setIsLoadingCompare(true);
    setCompareError(null);
    try {
      const res = await apiClient.get<ExperimentComparison>(
        `/experiments/compare?exp1_id=${selectedForCompare[0]}&exp2_id=${selectedForCompare[1]}`
      );
      setComparisonData(res.data);
      setIsCompareOpen(true);
    } catch (err) {
      setCompareError(formatErrorMessage(err));
    } finally {
      setIsLoadingCompare(false);
    }
  };

  const openDetailModal = async (exp: Experiment) => {
    setSelectedExp(exp);
    setActiveDetailTab('summary');
    setResultsPage(1);
    setResultsSearch('');
    loadExperimentResults(exp.id, 1, '', resultsSortBy, resultsSortDir);
  };

  const handleSort = (column: string) => {
    if (!selectedExp) return;
    const newDir = resultsSortBy === column && resultsSortDir === 'asc' ? 'desc' : 'asc';
    setResultsSortBy(column);
    setResultsSortDir(newDir);
    loadExperimentResults(selectedExp.id, 1, resultsSearch, column, newDir);
  };

  const loadExperimentResults = async (
    expId: string,
    page: number,
    search: string,
    sortBy: string,
    sortDir: string
  ) => {
    setIsLoadingResults(true);
    try {
      const searchParam = search ? `&search=${encodeURIComponent(search)}` : '';
      const res = await apiClient.get<ExperimentResultsDetail>(
        `/experiments/${expId}/results?page=${page}&limit=50&sort_by=${sortBy}&sort_dir=${sortDir}${searchParam}`
      );
      setResultsDetail(res.data);
    } catch (err) {
      console.error('Failed to load detailed experiment results', err);
    } finally {
      setIsLoadingResults(false);
    }
  };

  const handleResultsPageChange = (newPage: number) => {
    if (!selectedExp) return;
    setResultsPage(newPage);
    loadExperimentResults(selectedExp.id, newPage, resultsSearch, resultsSortBy, resultsSortDir);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedExp) return;
    setResultsPage(1);
    loadExperimentResults(selectedExp.id, 1, resultsSearch, resultsSortBy, resultsSortDir);
  };

  const handleDelete = async (expId: string) => {
    if (!window.confirm('Are you sure you want to delete this experiment and its generated artifacts?')) {
      return;
    }
    try {
      await apiClient.delete(`/experiments/${expId}`);
      setExperiments(experiments.filter((e) => e.id !== expId));
      if (selectedExp?.id === expId) {
        setSelectedExp(null);
      }
    } catch (err) {
      setError(formatErrorMessage(err));
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'Completed':
        return <Badge variant="emerald">Completed</Badge>;
      case 'Running':
        return <Badge variant="cyan">Executing</Badge>;
      case 'Timed out':
        return <Badge variant="amber">Timed out</Badge>;
      case 'Failed':
        return <Badge variant="rose">Failed</Badge>;
      default:
        return <Badge variant="slate">{status}</Badge>;
    }
  };

  const canCreate = user?.role === 'ADMIN' || user?.role === 'RESEARCHER';

  const assignedCountA = Object.values(sampleMappings).filter((g) => g === groupAName).length;
  const assignedCountB = Object.values(sampleMappings).filter((g) => g === groupBName).length;
  const unassignedCount = Math.max(0, datasetSamples.length - (assignedCountA + assignedCountB));

  return (
    <div className="space-y-6">
      {/* Action Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white">
            Deterministic Scientific Analysis Engine
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Execute reproducible differential expression screening and multivariate analysis in isolated zero-blast-radius sandboxes.
          </p>
        </div>

        {canCreate && (
          <Button
            onClick={openCreateModal}
            icon={<Play className="w-4 h-4 fill-current" />}
          >
            Launch Scientific Experiment
          </Button>
        )}
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* Isolation Boundary Guarantee Card */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs text-slate-300">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-950/80 border border-cyan-800/60 text-cyan-400 shrink-0">
            <Shield className="w-4 h-4" />
          </div>
          <div>
            <span className="font-semibold text-white block">
              Restricted Docker Execution
            </span>
            <span className="text-[11px] text-slate-400">
              Network disabled &bull; Read-only root filesystem &bull; Configured memory and CPU limits &bull; 1 CPU limit &bull; 60s default timeout
            </span>
          </div>
        </div>
        <Badge variant="cyan" size="sm">
          neuroforge-sandbox:local
        </Badge>
      </section>

      {/* Experiments List */}
      {isLoading ? (
        <LoadingSkeleton rows={3} />
      ) : experiments.length === 0 ? (
        <EmptyState
          icon={<FlaskConical className="w-6 h-6" />}
          title="No experiments executed yet"
          description="Formulate and execute your first statistical gene-expression experiment inside the isolated Docker sandbox."
          actionLabel={canCreate ? 'Launch First Experiment' : undefined}
          onAction={canCreate ? openCreateModal : undefined}
          actionIcon={<Play className="w-4 h-4 fill-current" />}
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
              Experiment History ({experiments.length})
            </h3>
            {selectedForCompare.length > 0 && (
              <div className="flex items-center gap-2 bg-cyan-950/60 border border-cyan-800/80 px-3 py-1.5 rounded-lg text-xs">
                <ArrowLeftRight className="w-3.5 h-3.5 text-cyan-400" />
                <span className="text-cyan-300">
                  {selectedForCompare.length} / 2 selected for comparison
                </span>
                {selectedForCompare.length === 2 && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleLaunchCompare}
                    isLoading={isLoadingCompare}
                    icon={<ArrowLeftRight className="w-3 h-3" />}
                  >
                    Compare
                  </Button>
                )}
                <button
                  onClick={() => setSelectedForCompare([])}
                  className="text-slate-400 hover:text-slate-200 text-xs ml-1 underline"
                >
                  Clear
                </button>
              </div>
            )}
          </div>

          {compareError && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
              {compareError}
            </div>
          )}

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden shadow-lg">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900/80 border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-3 w-10 text-center">Compare</th>
                    <th className="py-3 px-4">Experiment Title & Type</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Duration</th>
                    <th className="py-3 px-4">Key Findings</th>
                    <th className="py-3 px-4">Artifacts</th>
                    <th className="py-3 px-4">Executed At</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-200">
                  {experiments.map((exp) => (
                    <tr
                      key={exp.id}
                      className="hover:bg-slate-800/30 transition-colors cursor-pointer"
                      onClick={() => openDetailModal(exp)}
                    >
                      <td className="py-3 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedForCompare.includes(exp.id)}
                          onChange={(e) => toggleSelectForCompare(exp.id, e as any)}
                          className="rounded border-slate-700 text-cyan-500 focus:ring-cyan-500 bg-slate-900 cursor-pointer"
                          title="Select to compare"
                        />
                      </td>
                      <td className="py-3 px-4 font-medium text-white">
                        <div className="flex items-center gap-2">
                          <FlaskConical className="w-4 h-4 text-cyan-400 shrink-0" />
                          <div>
                            <span className="font-semibold block truncate max-w-xs">{exp.title}</span>
                            <span className="text-[10px] text-slate-400 font-mono">
                              {exp.experiment_type === 'differential_expression_welch'
                                ? "Welch's t-test (Two-Group FDR)"
                                : 'Custom Python Workflow'}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-4">{getStatusBadge(exp.status)}</td>
                      <td className="py-3 px-4 font-mono text-slate-400">
                        {exp.duration_seconds !== null ? `${exp.duration_seconds} s` : '—'}
                      </td>
                      <td className="py-3 px-4 text-slate-300 font-mono text-[11px]">
                        {exp.statistical_summary ? (
                          <span className="text-cyan-300">
                            {exp.statistical_summary.significant_features_count ?? 0} sig. features (FDR &le; {exp.statistical_summary.fdr_threshold ?? 0.05})
                          </span>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        {exp.artifacts && exp.artifacts.length > 0 ? (
                          <span className="inline-flex items-center gap-1 text-cyan-400 font-mono">
                            <Download className="w-3.5 h-3.5" />
                            {exp.artifacts.length} file{exp.artifacts.length > 1 ? 's' : ''}
                          </span>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-400">
                        {new Date(exp.created_at).toLocaleTimeString()} &bull;{' '}
                        {new Date(exp.created_at).toLocaleDateString()}
                      </td>
                      <td
                        className="py-3 px-4 text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="inline-flex items-center gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openDetailModal(exp)}
                          >
                            Results
                          </Button>
                          {(user?.role === 'ADMIN' || exp.owner_id === user?.id) && (
                            <button
                              onClick={() => handleDelete(exp.id)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                              title="Delete experiment"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
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
        </div>
      )}

      {/* Launch Experiment Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Launch Deterministic Scientific Experiment"
        description="Configure structured experimental comparisons or write custom scientific Python code."
        maxWidth="xl"
      >
        <form onSubmit={handleCreateAndRun} className="space-y-5">
          {formError && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
              {formError}
            </div>
          )}

          {/* Mode Switcher */}
          <div className="flex gap-2 p-1 rounded-xl bg-slate-950 border border-slate-800 text-xs font-semibold">
            <button
              type="button"
              onClick={() => setLaunchMode('differential_expression')}
              className={`flex-1 py-2 px-3 rounded-lg flex items-center justify-center gap-2 transition-colors ${launchMode === 'differential_expression'
                ? 'bg-cyan-500 text-slate-950'
                : 'text-slate-400 hover:text-white'
                }`}
            >
              <Activity className="w-4 h-4" />
              Two-Group Differential Expression (Welch t-test)
            </button>
            <button
              type="button"
              onClick={() => setLaunchMode('custom_script')}
              className={`flex-1 py-2 px-3 rounded-lg flex items-center justify-center gap-2 transition-colors ${launchMode === 'custom_script'
                ? 'bg-cyan-500 text-slate-950'
                : 'text-slate-400 hover:text-white'
                }`}
            >
              <Sliders className="w-4 h-4" />
              Custom Python Script
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-300">
                Target Research Project *
              </label>
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-xs text-slate-100 focus:ring-cyan-500"
                required
              >
                {projects.length === 0 ? (
                  <option value="">No projects available — please create one first</option>
                ) : (
                  projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title}
                    </option>
                  ))
                )}
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-300">
                Input Scientific Dataset *
              </label>
              <select
                value={selectedDatasetId}
                onChange={(e) => handleDatasetSelect(e.target.value)}
                className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-xs text-slate-100 focus:ring-cyan-500"
                required
              >
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.title || d.original_name} ({d.file_format})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Dataset Diagnostic & Warning Banners */}
          {launchMode === 'differential_expression' && (
            <div className="space-y-4">
              <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 flex items-center justify-between text-xs font-mono">
                <div>
                  <span className="text-slate-400">Orientation: </span>
                  <span className="text-cyan-300">{datasetOrientation}</span>
                </div>
                <div>
                  <span className="text-slate-400">Inferred Scale: </span>
                  <span className="text-purple-300">{datasetScale}</span>
                </div>
                <div>
                  <span className="text-slate-400">Total Samples: </span>
                  <span className="text-white">{datasetSamples.length}</span>
                </div>
              </div>

              {/* Raw Counts Incompatibility Guard */}
              {datasetScale === 'raw_counts' && (
                <div className="p-3 rounded-xl bg-rose-950/40 border border-rose-800/80 text-rose-200 text-xs flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <span className="font-semibold block">Unsupported Data Type: Raw RNA-seq Counts</span>
                    <p className="text-[11px] leading-relaxed text-rose-300/90">
                      Raw RNA-seq counts require a validated count-based statistical workflow, such as DESeq2. This analysis is not available yet.
                    </p>
                  </div>
                </div>
              )}

              {/* Group Names */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Input
                  label="Group A Name (Control / Baseline)"
                  value={groupAName}
                  onChange={(e) => setGroupAName(e.target.value)}
                  required
                />
                <Input
                  label="Group B Name (Treatment / Condition)"
                  value={groupBName}
                  onChange={(e) => setGroupBName(e.target.value)}
                  required
                />
              </div>

              {/* Sample Assignment Box */}
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-white">
                    Sample Group Mapping ({datasetSamples.length} samples)
                  </span>
                  <span className="font-mono text-[11px] text-slate-400">
                    {groupAName}: <strong className="text-cyan-400">{assignedCountA}</strong> &bull; {groupBName}: <strong className="text-purple-400">{assignedCountB}</strong> &bull; Unassigned: {unassignedCount}
                  </span>
                </div>

                <div className="max-h-48 overflow-y-auto divide-y divide-slate-800/40 pr-2">
                  {datasetSamples.map((sid) => {
                    const currentGrp = sampleMappings[sid];
                    return (
                      <div key={sid} className="py-1.5 flex items-center justify-between text-xs font-mono">
                        <span className="text-slate-300 truncate max-w-xs">{sid}</span>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => setSampleMappings({ ...sampleMappings, [sid]: groupAName })}
                            className={`px-2 py-0.5 rounded text-[11px] font-sans transition-colors ${currentGrp === groupAName ? 'bg-blue-600 text-white font-semibold' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                              }`}
                          >
                            {groupAName}
                          </button>
                          <button
                            type="button"
                            onClick={() => setSampleMappings({ ...sampleMappings, [sid]: groupBName })}
                            className={`px-2 py-0.5 rounded text-[11px] font-sans transition-colors ${currentGrp === groupBName ? 'bg-purple-600 text-white font-semibold' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                              }`}
                          >
                            {groupBName}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const updated = { ...sampleMappings };
                              delete updated[sid];
                              setSampleMappings(updated);
                            }}
                            className={`px-1.5 py-0.5 rounded text-[10px] font-sans transition-colors ${!currentGrp ? 'bg-slate-700 text-slate-200' : 'bg-slate-900 text-slate-500 hover:bg-slate-800'
                              }`}
                          >
                            Clear
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Sample Adequacy Indicator */}
                <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between text-xs">
                  {assignedCountA >= 3 && assignedCountB >= 3 ? (
                    <span className="text-emerald-400 flex items-center gap-1 font-semibold">
                      <CheckCircle2 className="w-4 h-4" />
                      Design validated for exploratory Welch t-test (N &ge; 3 per group)
                    </span>
                  ) : (
                    <span className="text-amber-400 flex items-center gap-1 font-medium">
                      <AlertTriangle className="w-4 h-4" />
                      Minimum 3 samples required per group (currently {groupAName}: {assignedCountA}, {groupBName}: {assignedCountB})
                    </span>
                  )}

                  <div className="flex items-center gap-2">
                    <label className="text-slate-400 font-mono text-[11px]">FDR Cutoff:</label>
                    <select
                      value={fdrThreshold}
                      onChange={(e) => setFdrThreshold(parseFloat(e.target.value))}
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-white font-mono text-xs"
                    >
                      <option value="0.05">0.05 (Standard)</option>
                      <option value="0.01">0.01 (Strict)</option>
                      <option value="0.10">0.10 (Permissive)</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Custom Code Mode */}
          {launchMode === 'custom_script' && (
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-300">
                Custom Scientific Python Script
              </label>
              <textarea
                rows={8}
                value={customCode}
                onChange={(e) => setCustomCode(e.target.value)}
                placeholder="# Enter Python script using numpy, scipy, pandas, or sklearn..."
                className="w-full font-mono text-xs rounded-lg border border-slate-800 bg-slate-950 px-3.5 py-2.5 text-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              />
            </div>
          )}

          <Input
            label="Experiment Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />

          <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              isLoading={isSubmitting}
              icon={<Play className="w-4 h-4 fill-current" />}
            >
              {isSubmitting ? 'Executing in Sandbox...' : 'Run Analysis'}
            </Button>
          </div>
        </form>
      </Modal>

      {/* Experiment Results & Inspection Modal */}
      {selectedExp && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-cyan-950/60 border border-cyan-800/60 flex items-center justify-center text-cyan-400">
                  <FlaskConical className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-white flex items-center gap-2">
                    {selectedExp.title}
                    {getStatusBadge(selectedExp.status)}
                  </h3>
                  <p className="text-xs text-slate-400 font-mono">
                    ID: {selectedExp.id.substring(0, 12)}... &bull; Executed in {selectedExp.duration_seconds ?? 0}s &bull; {new Date(selectedExp.created_at).toLocaleString()}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSelectedExp(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Navigation Tabs */}
            <div className="flex border-b border-slate-800 px-6 bg-slate-950/40">
              <button
                onClick={() => setActiveDetailTab('summary')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${activeDetailTab === 'summary' ? 'border-cyan-400 text-cyan-400' : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
              >
                <Activity className="w-4 h-4" />
                Statistical Summary
              </button>
              <button
                onClick={() => setActiveDetailTab('plots')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${activeDetailTab === 'plots' ? 'border-cyan-400 text-cyan-400' : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
              >
                <Eye className="w-4 h-4" />
                Volcano & PCA Plots
              </button>
              <button
                onClick={() => setActiveDetailTab('table')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${activeDetailTab === 'table' ? 'border-cyan-400 text-cyan-400' : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
              >
                <Table className="w-4 h-4" />
                Differential Features Table
              </button>
              <button
                onClick={() => setActiveDetailTab('reproducibility')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${activeDetailTab === 'reproducibility' ? 'border-cyan-400 text-cyan-400' : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
              >
                <FileText className="w-4 h-4" />
                Reproducibility Manifest
              </button>
              <button
                onClick={() => setActiveDetailTab('diagnostics')}
                className={`py-3 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${activeDetailTab === 'diagnostics' ? 'border-cyan-400 text-cyan-400' : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
              >
                <Layers className="w-4 h-4" />
                Execution Diagnostics
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto flex-1 space-y-6">
              {/* TAB 1: SUMMARY */}
              {activeDetailTab === 'summary' && (
                <div className="space-y-6">
                  {/* Status & Diagnostic Header */}
                  {selectedExp.failure_reason && (
                    <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800/80 text-rose-300 text-xs flex items-start gap-2.5">
                      <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5 text-rose-400" />
                      <div>
                        <span className="font-semibold block text-sm">Execution Diagnostic:</span>
                        <p className="text-xs text-rose-200 mt-0.5">{selectedExp.failure_reason}</p>
                      </div>
                    </div>
                  )}

                  {/* Summary Metric Cards */}
                  {selectedExp.statistical_summary ? (
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                      <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                        <span className="text-[11px] text-slate-400 uppercase font-semibold">Tested Features</span>
                        <p className="text-xl font-bold font-mono text-white">
                          {selectedExp.statistical_summary.total_features_tested ?? 'N/A'}
                        </p>
                        <span className="text-[10px] text-slate-500">Filtered finite observations</span>
                      </div>
                      <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                        <span className="text-[11px] text-slate-400 uppercase font-semibold">Significant (FDR &le; {selectedExp.statistical_summary.fdr_threshold ?? 0.05})</span>
                        <p className="text-xl font-bold font-mono text-cyan-400">
                          {selectedExp.statistical_summary.significant_features_count ?? 0}
                        </p>
                        <span className="text-[10px] text-slate-500">Benjamini-Hochberg adjusted</span>
                      </div>
                      <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                        <span className="text-[11px] text-slate-400 uppercase font-semibold">Upregulated (log2FC &gt; 0)</span>
                        <p className="text-xl font-bold font-mono text-emerald-400">
                          {selectedExp.statistical_summary.upregulated_count ?? 0}
                        </p>
                        <span className="text-[10px] text-slate-500">Higher in {selectedExp.statistical_summary.group_b_name}</span>
                      </div>
                      <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-1">
                        <span className="text-[11px] text-slate-400 uppercase font-semibold">Downregulated (log2FC &lt; 0)</span>
                        <p className="text-xl font-bold font-mono text-rose-400">
                          {selectedExp.statistical_summary.downregulated_count ?? 0}
                        </p>
                        <span className="text-[10px] text-slate-500">Lower in {selectedExp.statistical_summary.group_b_name}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-slate-400">
                      Standard script execution complete. Review artifacts or console logs.
                    </div>
                  )}

                  {/* Comparison Group Design Overview */}
                  {selectedExp.statistical_summary && (
                    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-2 text-xs">
                      <h4 className="font-semibold text-white">Statistical Methodology & Comparison Design</h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-slate-300">
                        <div>
                          <span className="text-slate-400 block font-medium">Statistical Test:</span>
                          <span>{selectedExp.statistical_summary.statistical_method || "Welch's two-sample t-test (two-sided)"}</span>
                        </div>
                        <div>
                          <span className="text-slate-400 block font-medium">Multiple Testing Correction:</span>
                          <span>Benjamini-Hochberg False Discovery Rate (FDR)</span>
                        </div>
                        <div>
                          <span className="text-slate-400 block font-medium">Group A (Baseline):</span>
                          <span className="font-mono text-blue-300">{selectedExp.statistical_summary.group_a_name} (N = {selectedExp.statistical_summary.group_a_count})</span>
                        </div>
                        <div>
                          <span className="text-slate-400 block font-medium">Group B (Condition):</span>
                          <span className="font-mono text-purple-300">{selectedExp.statistical_summary.group_b_name} (N = {selectedExp.statistical_summary.group_b_count})</span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Scientific Caveats & Limitations */}
                  <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs space-y-1.5 text-slate-400">
                    <span className="font-semibold text-slate-300 block">Scientific Limitations & Assumptions:</span>
                    <p className="text-[11px] leading-relaxed">
                      &bull; Features are evaluated independently assuming continuous, approximately normal distributions across biological replicates.
                    </p>
                    <p className="text-[11px] leading-relaxed">
                      &bull; Statistical significance at FDR cutoff does not establish causality, biological mechanism, or medical diagnosis. Confirmatory testing is strictly required.
                    </p>
                  </div>
                </div>
              )}

              {/* TAB 2: PLOTS & VISUALIZATIONS */}
              {activeDetailTab === 'plots' && (
                <div className="space-y-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Volcano Plot */}
                    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-white">Volcano Plot (Genuine Data)</span>
                        <span className="text-[11px] font-mono text-slate-400">Log2FC vs -Log10(FDR)</span>
                      </div>
                      {selectedExp.artifacts?.find((a) => a.filename === 'volcano_plot.png') ? (
                        <div className="rounded-lg border border-slate-800 overflow-hidden bg-slate-900 flex items-center justify-center p-2">
                          <img
                            src={`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8020'}${selectedExp.artifacts.find((a) => a.filename === 'volcano_plot.png')?.download_url}`}
                            alt="Volcano Plot"
                            className="max-h-72 object-contain"
                          />
                        </div>
                      ) : (
                        <div className="h-64 flex items-center justify-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-lg">
                          Volcano plot artifact not generated.
                        </div>
                      )}
                    </div>

                    {/* PCA Plot */}
                    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-white">Principal Component Analysis</span>
                        <span className="text-[11px] font-mono text-slate-400">Sample Projection (PC1 vs PC2)</span>
                      </div>
                      {selectedExp.artifacts?.find((a) => a.filename === 'pca_plot.png') ? (
                        <div className="rounded-lg border border-slate-800 overflow-hidden bg-slate-900 flex items-center justify-center p-2">
                          <img
                            src={`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8020'}${selectedExp.artifacts.find((a) => a.filename === 'pca_plot.png')?.download_url}`}
                            alt="PCA Projection"
                            className="max-h-72 object-contain"
                          />
                        </div>
                      ) : (
                        <div className="h-64 flex items-center justify-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-lg">
                          PCA plot artifact not generated.
                        </div>
                      )}
                    </div>

                    {/* Expression Heatmap */}
                    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3 md:col-span-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-white">Expression Heatmap (Top Significant Features)</span>
                        <span className="text-[11px] font-mono text-slate-400">Row Z-Scores (Blue: Group A, Purple: Group B)</span>
                      </div>
                      {selectedExp.artifacts?.find((a) => a.filename === 'heatmap_plot.png') ? (
                        <div className="rounded-lg border border-slate-800 overflow-hidden bg-slate-900 flex items-center justify-center p-2">
                          <img
                            src={`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8020'}${selectedExp.artifacts.find((a) => a.filename === 'heatmap_plot.png')?.download_url}`}
                            alt="Expression Heatmap"
                            className="max-h-96 object-contain"
                          />
                        </div>
                      ) : (
                        <div className="h-48 flex items-center justify-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-lg">
                          Heatmap plot artifact not generated.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: DIFFERENTIAL FEATURES TABLE */}
              {activeDetailTab === 'table' && (
                <div className="space-y-4">
                  {/* Table search & download toolbar */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                    <form onSubmit={handleSearchSubmit} className="flex items-center gap-2 max-w-sm w-full">
                      <div className="relative w-full">
                        <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                        <input
                          type="text"
                          value={resultsSearch}
                          onChange={(e) => setResultsSearch(e.target.value)}
                          placeholder="Search gene or feature ID..."
                          className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-400"
                        />
                      </div>
                      <Button type="submit" size="sm" variant="secondary">
                        Filter
                      </Button>
                    </form>

                    <div className="flex items-center gap-3">
                      {selectedExp.artifacts?.find((a) => a.filename === 'differential_expression_results.csv') && (
                        <a
                          href={`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8020'}${selectedExp.artifacts.find((a) => a.filename === 'differential_expression_results.csv')?.download_url}`}
                          download
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs transition-colors"
                        >
                          <Download className="w-3.5 h-3.5" />
                          Download Complete CSV ({resultsDetail?.total_features ?? 0} features)
                        </a>
                      )}
                    </div>
                  </div>

                  {/* Results Table */}
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 overflow-hidden">
                    <div className="overflow-x-auto max-h-[460px]">
                      <table className="w-full text-left text-[11px] font-mono">
                        <thead className="bg-slate-900 border-b border-slate-800 text-slate-400 sticky top-0 z-10 select-none">
                          <tr>
                            <th onClick={() => handleSort('feature_id')} className="py-2.5 px-3 cursor-pointer hover:text-white">
                              Feature ID {resultsSortBy === 'feature_id' ? (resultsSortDir === 'asc' ? '↑' : '↓') : ''}
                            </th>
                            <th className="py-2.5 px-3">Mean A</th>
                            <th className="py-2.5 px-3">Mean B</th>
                            <th onClick={() => handleSort('mean_diff')} className="py-2.5 px-3 cursor-pointer hover:text-white">
                              Mean Diff {resultsSortBy === 'mean_diff' ? (resultsSortDir === 'asc' ? '↑' : '↓') : ''}
                            </th>
                            <th onClick={() => handleSort('log2_fc')} className="py-2.5 px-3 cursor-pointer hover:text-white">
                              Log2 FC {resultsSortBy === 'log2_fc' ? (resultsSortDir === 'asc' ? '↑' : '↓') : ''}
                            </th>
                            <th onClick={() => handleSort('t_stat')} className="py-2.5 px-3 cursor-pointer hover:text-white">
                              Welch t {resultsSortBy === 't_stat' ? (resultsSortDir === 'asc' ? '↑' : '↓') : ''}
                            </th>
                            <th className="py-2.5 px-3">df</th>
                            <th onClick={() => handleSort('p_value')} className="py-2.5 px-3 cursor-pointer hover:text-white">
                              Raw p-val {resultsSortBy === 'p_value' ? (resultsSortDir === 'asc' ? '↑' : '↓') : ''}
                            </th>
                            <th onClick={() => handleSort('adj_p_value')} className="py-2.5 px-3 cursor-pointer hover:text-cyan-400">
                              FDR (Adj p) {resultsSortBy === 'adj_p_value' ? (resultsSortDir === 'asc' ? '↑' : '↓') : ''}
                            </th>
                            <th onClick={() => handleSort('hedges_g')} className="py-2.5 px-3 cursor-pointer hover:text-white">
                              Hedges g {resultsSortBy === 'hedges_g' ? (resultsSortDir === 'asc' ? '↑' : '↓') : ''}
                            </th>
                            <th className="py-2.5 px-3 text-right">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/40 text-slate-200">
                          {isLoadingResults ? (
                            <tr>
                              <td colSpan={11} className="py-8 text-center text-slate-500 font-sans">
                                Loading computed differential expressions...
                              </td>
                            </tr>
                          ) : !resultsDetail?.features || resultsDetail.features.length === 0 ? (
                            <tr>
                              <td colSpan={11} className="py-8 text-center text-slate-500 font-sans">
                                No statistical feature records found matching query.
                              </td>
                            </tr>
                          ) : (
                            resultsDetail.features.map((feat) => (
                              <tr key={feat.feature_id} className="hover:bg-slate-800/30">
                                <td className="py-2 px-3 font-semibold text-white">
                                  {feat.feature_id}
                                </td>
                                <td className="py-2 px-3 text-slate-400">{feat.mean_a.toFixed(2)}</td>
                                <td className="py-2 px-3 text-slate-400">{feat.mean_b.toFixed(2)}</td>
                                <td className="py-2 px-3 text-slate-300 font-medium">
                                  {feat.mean_diff > 0 ? `+${feat.mean_diff.toFixed(3)}` : feat.mean_diff.toFixed(3)}
                                </td>
                                <td className="py-2 px-3 font-bold text-slate-200">
                                  {feat.log2_fc !== null ? feat.log2_fc.toFixed(3) : '—'}
                                </td>
                                <td className="py-2 px-3 text-slate-400">
                                  {feat.t_stat !== null ? feat.t_stat.toFixed(2) : '—'}
                                </td>
                                <td className="py-2 px-3 text-slate-500">
                                  {feat.df !== null ? feat.df.toFixed(1) : '—'}
                                </td>
                                <td className="py-2 px-3 text-slate-400">
                                  {feat.p_value !== null ? feat.p_value.toExponential(3) : '—'}
                                </td>
                                <td className="py-2 px-3 font-semibold">
                                  {feat.adj_p_value !== null ? (
                                    <span className={feat.is_significant ? 'text-cyan-400' : 'text-slate-400'}>
                                      {feat.adj_p_value.toExponential(3)}
                                    </span>
                                  ) : '—'}
                                </td>
                                <td className="py-2 px-3 text-slate-400">
                                  {feat.hedges_g !== null ? feat.hedges_g.toFixed(2) : '—'}
                                </td>
                                <td className="py-2 px-3 text-right">
                                  {feat.is_significant ? (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-sans font-semibold bg-cyan-950 text-cyan-300 border border-cyan-800/60">
                                      Significant
                                    </span>
                                  ) : (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-sans text-slate-500">
                                      Non-sig
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>

                    {/* Table Pagination */}
                    <div className="p-3 bg-slate-900 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400 font-sans">
                      <span>
                        Showing {Math.min((resultsPage - 1) * 50 + 1, resultsDetail?.total_features || 0)} to{' '}
                        {Math.min(resultsPage * 50, resultsDetail?.total_features || 0)} of{' '}
                        {resultsDetail?.total_features || 0} features
                      </span>

                      <div className="flex items-center gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={resultsPage <= 1}
                          onClick={() => handleResultsPageChange(resultsPage - 1)}
                        >
                          <ChevronLeft className="w-3.5 h-3.5" />
                        </Button>
                        <span className="font-mono text-white">Page {resultsPage}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={(resultsPage * 50) >= (resultsDetail?.total_features || 0)}
                          onClick={() => handleResultsPageChange(resultsPage + 1)}
                        >
                          <ChevronRight className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 4: REPRODUCIBILITY RECORD */}
              {activeDetailTab === 'reproducibility' && (
                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-5 space-y-4 text-xs font-mono">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3 font-sans">
                      <div>
                        <h4 className="text-sm font-semibold text-white">Persisted Reproducibility Record</h4>
                        <span className="text-xs text-slate-400">Verifiable computational parameters, environment versions, and dataset SHA-256 hash.</span>
                      </div>
                      <Badge variant="cyan" size="sm">
                        SHA-256 Provenance
                      </Badge>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-slate-300">
                      <div>
                        <span className="text-slate-500 block">Dataset Identifier:</span>
                        <span className="text-white">{selectedExp.dataset_id || 'N/A'}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Dataset Content SHA-256:</span>
                        <span className="text-cyan-300 truncate block font-mono">
                          {selectedExp.dataset_hash || selectedExp.reproducibility_manifest?.dataset_hash || 'Unverified'}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Statistical Screening Model:</span>
                        <span>{selectedExp.reproducibility_manifest?.statistical_method || "Welch's independent t-test (two-sided, unequal variances)"}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Multiple Testing Correction:</span>
                        <span>{selectedExp.reproducibility_manifest?.multiple_testing_correction || "Benjamini-Hochberg (1995) FDR"}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Alpha & FDR Thresholds:</span>
                        <span>Alpha = {selectedExp.reproducibility_manifest?.alpha ?? 0.05}, FDR = {selectedExp.reproducibility_manifest?.fdr_threshold ?? 0.05}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Effect Size Convention:</span>
                        <span className="text-slate-300">Hedges' g with pooled variance & small-sample correction J(df)</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Exploratory Preprocessing:</span>
                        <span className="text-slate-300">Pairwise finite filter, feature-wise median imputation & unit scaling</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Execution Timestamp:</span>
                        <span>{selectedExp.reproducibility_manifest?.timestamp || selectedExp.created_at}</span>
                      </div>
                    </div>

                    {selectedExp.reproducibility_manifest?.software_versions && (
                      <div className="pt-3 border-t border-slate-800">
                        <span className="text-slate-500 block mb-1">Software Environment Versions:</span>
                        <div className="flex flex-wrap gap-2 text-[11px]">
                          {Object.entries(selectedExp.reproducibility_manifest.software_versions).map(([lib, ver]) => (
                            <span key={lib} className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300">
                              {lib}: {String(ver)}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 5: EXECUTION DIAGNOSTICS */}
              {activeDetailTab === 'diagnostics' && (
                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-5 space-y-4 text-xs font-sans">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div>
                        <h4 className="text-sm font-semibold text-white">Execution Summary & Environment</h4>
                        <span className="text-xs text-slate-400">Isolated sandbox container lifecycle and computational boundaries.</span>
                      </div>
                      <Badge variant={selectedExp.status === 'Completed' ? 'emerald' : selectedExp.status === 'Timed out' ? 'amber' : 'rose'} size="sm">
                        {selectedExp.status}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-slate-300">
                      <div>
                        <span className="text-slate-500 block">Execution State:</span>
                        <span className="text-white font-medium">{selectedExp.status}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Computation Duration:</span>
                        <span className="text-white font-mono">{selectedExp.duration_seconds ? `${selectedExp.duration_seconds.toFixed(2)}s` : '—'}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Execution Exit Code:</span>
                        <span className="text-white font-mono">{selectedExp.exit_code !== null ? selectedExp.exit_code : 'N/A'}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Artifacts Generated:</span>
                        <span className="text-white">{selectedExp.artifacts?.length || 0} files</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Sandbox Isolation:</span>
                        <span className="text-emerald-400">Zero-Blast-Radius (Network disabled, read-only root)</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Safe Execution Reference:</span>
                        <span className="text-slate-400 font-mono text-[11px] truncate block">{selectedExp.id}</span>
                      </div>
                    </div>

                    {selectedExp.failure_reason && (
                      <div className="p-3.5 rounded-lg bg-rose-950/40 border border-rose-800/60 text-rose-300 space-y-1">
                        <span className="font-semibold block text-rose-200">Execution Notice:</span>
                        <p className="text-xs">{selectedExp.failure_reason}</p>
                      </div>
                    )}
                  </div>

                  {/* Administrator Technical Diagnostics (Restricted) */}
                  {user?.role === 'ADMIN' && (selectedExp.stdout || selectedExp.stderr) && (
                    <div className="rounded-xl border border-amber-900/40 bg-amber-950/10 p-4 space-y-3">
                      <div className="flex items-center justify-between text-amber-400 text-xs font-semibold">
                        <span>Administrator Container Logs (Restricted)</span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/60 border border-amber-800/40">ADMIN ONLY</span>
                      </div>
                      {selectedExp.stdout && (
                        <div className="space-y-1">
                          <span className="text-[11px] text-slate-400 font-mono">stdout:</span>
                          <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-cyan-300 overflow-x-auto max-h-40 whitespace-pre-wrap">
                            {selectedExp.stdout}
                          </pre>
                        </div>
                      )}
                      {selectedExp.stderr && (
                        <div className="space-y-1">
                          <span className="text-[11px] text-rose-400 font-mono">stderr:</span>
                          <pre className="p-3 rounded-lg bg-rose-950/20 border border-rose-900/40 font-mono text-[11px] text-rose-300 overflow-x-auto max-h-32 whitespace-pre-wrap">
                            {selectedExp.stderr}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Experiment Comparison Modal */}
      <Modal
        isOpen={isCompareOpen}
        onClose={() => setIsCompareOpen(false)}
        title="Side-by-Side Experiment Comparison & Biomarker Concordance"
        description="Comparative statistical evaluation of candidate biomarkers, effect sizes, and reproducibility manifests across two distinct runs."
      >
        {comparisonData && (
          <div className="space-y-6 max-h-[75vh] overflow-y-auto pr-1">
            {/* Top overview cards: Exp 1 vs Exp 2 */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-4 rounded-xl bg-slate-900 border border-cyan-800/60 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-cyan-400 uppercase tracking-wider">
                    Experiment 1
                  </span>
                  <Badge variant="cyan" size="sm">
                    {comparisonData.exp1.status}
                  </Badge>
                </div>
                <h4 className="text-sm font-bold text-white line-clamp-1">{comparisonData.exp1.title}</h4>
                <div className="text-[11px] text-slate-400 font-mono space-y-1">
                  <div>Type: {comparisonData.exp1.experiment_type}</div>
                  <div>Duration: {comparisonData.exp1.duration_seconds ? `${comparisonData.exp1.duration_seconds.toFixed(2)}s` : 'N/A'}</div>
                  <div>Significant Biomarkers: <strong className="text-cyan-300">{comparisonData.exp1_significant_count}</strong></div>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-900 border border-purple-800/60 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-purple-400 uppercase tracking-wider">
                    Experiment 2
                  </span>
                  <Badge variant="purple" size="sm">
                    {comparisonData.exp2.status}
                  </Badge>
                </div>
                <h4 className="text-sm font-bold text-white line-clamp-1">{comparisonData.exp2.title}</h4>
                <div className="text-[11px] text-slate-400 font-mono space-y-1">
                  <div>Type: {comparisonData.exp2.experiment_type}</div>
                  <div>Duration: {comparisonData.exp2.duration_seconds ? `${comparisonData.exp2.duration_seconds.toFixed(2)}s` : 'N/A'}</div>
                  <div>Significant Biomarkers: <strong className="text-purple-300">{comparisonData.exp2_significant_count}</strong></div>
                </div>
              </div>
            </div>

            {/* Metrics Concordance Banner */}
            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
              <div>
                <span className="text-[10px] font-mono uppercase text-slate-400 block">Shared Dataset</span>
                <span className={`text-xs font-bold ${comparisonData.shared_dataset ? 'text-emerald-400' : 'text-slate-400'}`}>
                  {comparisonData.shared_dataset ? 'Yes (Same Cohort)' : 'Independent'}
                </span>
              </div>
              <div>
                <span className="text-[10px] font-mono uppercase text-slate-400 block">Dataset Hash Match</span>
                <span className={`text-xs font-bold ${comparisonData.dataset_hash_match ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {comparisonData.dataset_hash_match ? 'Identical (SHA-256)' : 'Distinct'}
                </span>
              </div>
              <div>
                <span className="text-[10px] font-mono uppercase text-slate-400 block">Shared Biomarkers</span>
                <span className="text-base font-bold text-cyan-400">
                  {comparisonData.shared_significant_count}
                </span>
              </div>
              <div>
                <span className="text-[10px] font-mono uppercase text-slate-400 block">Directional Concordance</span>
                <span className="text-base font-bold text-emerald-400">
                  {comparisonData.concordance_rate !== null ? `${comparisonData.concordance_rate}%` : 'N/A'}
                </span>
              </div>
            </div>

            {/* Shared Features Comparison Table */}
            <div className="space-y-2">
              <h5 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                Shared Statistically Significant Biomarkers ({comparisonData.shared_features.length})
              </h5>
              {comparisonData.shared_features.length === 0 ? (
                <p className="text-xs text-slate-500 font-mono p-4 bg-slate-950/60 rounded-lg text-center">
                  No overlapping significant features identified between these two runs.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/60">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900/80 border-b border-slate-800 text-slate-400 font-mono text-[11px]">
                      <tr>
                        <th className="py-2.5 px-3">Feature ID</th>
                        <th className="py-2.5 px-3">Exp 1 log2 FC</th>
                        <th className="py-2.5 px-3">Exp 2 log2 FC</th>
                        <th className="py-2.5 px-3">Exp 1 FDR</th>
                        <th className="py-2.5 px-3">Exp 2 FDR</th>
                        <th className="py-2.5 px-3 text-right">Directional Agreement</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px] text-slate-300">
                      {comparisonData.shared_features.map((item, idx) => (
                        <tr key={idx} className="hover:bg-slate-900/40">
                          <td className="py-2 px-3 font-bold text-white">{item.feature_id}</td>
                          <td className="py-2 px-3">{item.log2_fc_1 !== null && item.log2_fc_1 !== undefined ? item.log2_fc_1.toFixed(3) : '—'}</td>
                          <td className="py-2 px-3">{item.log2_fc_2 !== null && item.log2_fc_2 !== undefined ? item.log2_fc_2.toFixed(3) : '—'}</td>
                          <td className="py-2 px-3">{item.adj_p_value_1 !== null && item.adj_p_value_1 !== undefined ? item.adj_p_value_1.toExponential(2) : '—'}</td>
                          <td className="py-2 px-3">{item.adj_p_value_2 !== null && item.adj_p_value_2 !== undefined ? item.adj_p_value_2.toExponential(2) : '—'}</td>
                          <td className="py-2 px-3 text-right">
                            {item.concordant === true ? (
                              <Badge variant="emerald" size="sm">Concordant</Badge>
                            ) : item.concordant === false ? (
                              <Badge variant="rose" size="sm">Discordant</Badge>
                            ) : (
                              <Badge variant="slate" size="sm">Neutral</Badge>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Footer with JSON export */}
            <div className="flex justify-between items-center pt-2 border-t border-slate-800">
              <span className="text-[11px] text-slate-500">
                Reproducible manifest comparison verified via deterministic SHA-256 hashes.
              </span>
              <Button
                variant="secondary"
                size="sm"
                icon={<Download className="w-3.5 h-3.5" />}
                onClick={() => {
                  const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(comparisonData, null, 2));
                  const a = document.createElement('a');
                  a.setAttribute('href', dataStr);
                  a.setAttribute('download', `experiment_comparison_${comparisonData.exp1.id.slice(0, 8)}_${comparisonData.exp2.id.slice(0, 8)}.json`);
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                }}
              >
                Export Comparison JSON
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
