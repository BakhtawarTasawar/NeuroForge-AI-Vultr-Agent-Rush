import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Sparkles,
  Play,
  AlertTriangle,
  Database,
  Layers,
  FileText,
  Shield,
  Activity,
  BarChart2,
  RefreshCw,
  Plus,
  Check,
  X,
  FolderGit2,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { apiClient, formatErrorMessage } from '../../services/api';
import {
  createResearchSession,
  listResearchSessions,
  getResearchSession,
  approveResearchPlan,
  rejectResearchPlan,
  continueResearchSession,
  getSessionEvents,
} from '../../services/agentApi';
import { Project, Dataset, ResearchSession, ResearchEvent } from '../../types';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { Modal } from '../../components/common/Modal';
import { Badge } from '../../components/common/Badge';
import { EmptyState } from '../../components/common/EmptyState';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

export const ResearchWorkspacePage: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sessions, setSessions] = useState<ResearchSession[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [activeSession, setActiveSession] = useState<ResearchSession | null>(null);
  const [events, setEvents] = useState<ResearchEvent[]>([]);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // New Session Modal
  const [isNewSessionOpen, setIsNewSessionOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newObjective, setNewObjective] = useState('');
  const [newDatasetId, setNewDatasetId] = useState('');
  const [groupAName, setGroupAName] = useState('Control');
  const [groupBName, setGroupBName] = useState('Treatment');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Safety Gate Modal / Inputs
  const [isRejectOpen, setIsRejectOpen] = useState(false);
  const [rejectNotes, setRejectNotes] = useState('');
  const [isActionPending, setIsActionPending] = useState(false);

  // Active Tab in Workspace
  const [activeTab, setActiveTab] = useState<'plan' | 'timeline' | 'evidence' | 'report'>('plan');

  // Polling ref
  const pollIntervalRef = useRef<number | null>(null);

  // Initial load
  useEffect(() => {
    fetchInitialData();
  }, []);

  const fetchInitialData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [projRes, dataRes] = await Promise.all([
        apiClient.get<Project[]>('/projects'),
        apiClient.get<Dataset[]>('/datasets'),
      ]);
      // Backend now enforces tenant isolation — use the response directly.
      const accessibleProjects = projRes.data;
      setProjects(accessibleProjects);
      setDatasets(dataRes.data);

      if (accessibleProjects.length > 0) {
        const initialProj = accessibleProjects[0].id;
        setSelectedProjectId(initialProj);
        setNewDatasetId('');
        await loadSessionsForProject(initialProj);
      } else {
        setSelectedProjectId('');
        setNewDatasetId('');
        setSessions([]);
        setActiveSession(null);
        setEvents([]);
      }
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  const loadSessionsForProject = async (projId: string) => {
    try {
      const sessionsList = await listResearchSessions(projId);
      setSessions(sessionsList);
      if (sessionsList.length > 0) {
        selectSession(sessionsList[0]);
      } else {
        setActiveSession(null);
        setEvents([]);
      }
    } catch (err) {
      setError(formatErrorMessage(err));
      // Gracefully reset session state so an unauthorized project does not stay selected
      setSessions([]);
      setActiveSession(null);
      setEvents([]);
    }
  };

  const selectSession = async (sess: ResearchSession) => {
    setActiveSession(sess);
    if (sess.status === 'Completed') {
      setActiveTab('report');
    } else if (sess.status === 'Awaiting Approval') {
      setActiveTab('plan');
    }
    await refreshSessionDetails(sess.id);
  };

  const refreshSessionDetails = async (sessId: string) => {
    try {
      const [updatedSession, eventsList] = await Promise.all([
        getResearchSession(sessId),
        getSessionEvents(sessId),
      ]);
      setActiveSession(updatedSession);
      setEvents(eventsList);

      setSessions((prev) =>
        prev.map((s) => (s.id === updatedSession.id ? updatedSession : s))
      );
    } catch (err) {
      console.error('Error refreshing session:', err);
    }
  };

  // Auto-polling for active sessions
  useEffect(() => {
    if (
      activeSession &&
      ['Initializing', 'Planning', 'Executing', 'Evaluating'].includes(activeSession.status)
    ) {
      pollIntervalRef.current = window.setInterval(() => {
        refreshSessionDetails(activeSession.id);
      }, 3000);
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [activeSession?.status, activeSession?.id]);

  const handleProjectChange = async (projId: string) => {
    setSelectedProjectId(projId);
    setNewDatasetId('');
    await loadSessionsForProject(projId);
  };

  const projectDatasets = datasets.filter((d) => d.project_id === selectedProjectId);

  const handleLaunchSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId) {
      setFormError('Please select a research project first.');
      return;
    }
    if (!newDatasetId) {
      setFormError('Please select a dataset attached to this project.');
      return;
    }
    const selectedDs = projectDatasets.find((d) => d.id === newDatasetId);
    if (!selectedDs) {
      setFormError('The selected dataset is not attached to this research project.');
      return;
    }
    if (!newTitle.trim()) {
      setFormError('Please provide a research title.');
      return;
    }
    if (!newObjective.trim()) {
      setFormError('Please state the research objective.');
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      const session = await createResearchSession(selectedProjectId, {
        dataset_id: newDatasetId,
        title: newTitle.trim(),
        objective: newObjective.trim(),
        group_a_name: groupAName.trim() || undefined,
        group_b_name: groupBName.trim() || undefined,
      });

      setIsNewSessionOpen(false);
      setNewTitle('');
      setNewObjective('');
      setNewDatasetId('');

      setSessions((prev) => [session, ...prev]);
      setActiveSession(session);
      setActiveTab('plan');
      await refreshSessionDetails(session.id);
    } catch (err) {
      setFormError(formatErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApprovePlan = async () => {
    if (!activeSession) return;
    setIsActionPending(true);
    try {
      const planHash = activeSession.research_plan?.plan_hash;
      const updated = await approveResearchPlan(activeSession.id, undefined, planHash);
      setActiveSession(updated);
      await refreshSessionDetails(activeSession.id);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const handleRejectPlan = async () => {
    if (!activeSession) return;
    if (!rejectNotes.trim()) {
      setError('Please provide feedback or reason for rejecting the research plan.');
      return;
    }
    setIsActionPending(true);
    try {
      const updated = await rejectResearchPlan(activeSession.id, rejectNotes.trim());
      setActiveSession(updated);
      setIsRejectOpen(false);
      setRejectNotes('');
      await refreshSessionDetails(activeSession.id);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const handleContinueSession = async () => {
    if (!activeSession) return;
    setIsActionPending(true);
    try {
      const updated = await continueResearchSession(activeSession.id);
      setActiveSession(updated);
      await refreshSessionDetails(activeSession.id);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const getStatusBadgeVariant = (status: string) => {
    switch (status) {
      case 'Completed':
        return 'emerald';
      case 'Executing':
      case 'Evaluating':
      case 'Planning':
      case 'Initializing':
        return 'cyan';
      case 'Awaiting Approval':
        return 'amber';
      case 'Rejected':
      case 'Failed':
        return 'rose';
      default:
        return 'slate';
    }
  };

  const formatResearcherFriendlyFailure = (reason?: string | null): string => {
    if (!reason) return 'The research session encountered an unexpected condition. You can safely resume the investigation.';
    const lower = reason.toLowerCase();
    if (lower.includes('inference') || lower.includes('vultr') || lower.includes('api key') || lower.includes('format')) {
      return 'The AI inference service encountered a temporary error or invalid response. Your dataset and research session are preserved. You can resume this session when the inference service is ready.';
    }
    if (lower.includes('timeout')) {
      return 'A service timeout occurred during execution. You can resume the investigation to retry.';
    }
    if (lower.includes('rejected')) {
      return 'This research plan was rejected by the researcher.';
    }
    const firstLine = reason.split('\n')[0].replace(/([a-zA-Z0-9_-]{32,})/g, '...');
    return `Investigation halted: ${firstLine}`;
  };

  const getWorkflowStageIndex = (status: string, step: string) => {
    if (status === 'Completed') return 5;
    if (status === 'Evaluating') return 4;
    if (status === 'Executing' || step === 'execute_experiment') return 3;
    if (status === 'Awaiting Approval' || step === 'await_human_approval') return 2;
    if (status === 'Planning' || step === 'generate_research_plan') return 1;
    return 0; // Connecting / Inspecting
  };

  const objectivePresets = [
    'Perform exploratory PCA cluster analysis and screen differentially expressed genes between tumor and normal adjacent control with FDR < 0.05.',
    'Screen transcriptional dysregulations across cohorts to discover candidate oncogenic drivers with significant effect sizes.',
    'Unsupervised PCA dimensionality reduction and quality assessment for transcriptomic expression profiles.',
  ];

  if (isLoading) {
    return <LoadingSkeleton rows={8} />;
  }

  return (
    <div className="space-y-6">
      {/* Top Banner & Control Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-950/80 border border-cyan-500/30 text-cyan-400">
              <Sparkles className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
                Autonomous Scientific Research Agent
                <span className="text-xs font-mono font-medium px-2 py-0.5 rounded-full bg-cyan-950 text-cyan-400 border border-cyan-800">
                  LangGraph + Vultr
                </span>
              </h1>
              <p className="text-sm text-slate-400">
                Evidence-grounded hypothesis generation, statistical planning, and Docker sandbox execution.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Project selector */}
          {projects.length > 0 ? (
            <select
              value={selectedProjectId}
              onChange={(e) => handleProjectChange(e.target.value)}
              className="h-10 px-3 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  Project: {p.title}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-xs font-mono text-amber-400 bg-amber-950/40 border border-amber-800/40 px-3 py-2 rounded-lg">
              No Accessible Projects
            </span>
          )}

          {user?.role !== 'VIEWER' && (
            <Button
              variant="primary"
              size="sm"
              icon={<Plus className="h-4 w-4" />}
              onClick={() => {
                if (projects.length === 0) {
                  setError('Please create a research project first before launching an autonomous research session.');
                } else {
                  setIsNewSessionOpen(true);
                }
              }}
            >
              New Research Session
            </Button>
          )}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-950/50 border border-rose-800/80 text-rose-300 text-sm flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-rose-400 hover:text-rose-200 text-xs font-mono"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Main Workspace Layout */}
      {projects.length === 0 ? (
        <EmptyState
          icon={<FolderGit2 className="h-6 w-6" />}
          title="No Accessible Research Projects"
          description="Autonomous research investigations require an active research project. Create a project to organize hypotheses, datasets, and experiment runs."
          actionLabel={user?.role !== 'VIEWER' ? "Create Research Project" : undefined}
          onAction={user?.role !== 'VIEWER' ? () => navigate('/app/projects') : undefined}
          actionIcon={<Plus className="h-4 w-4" />}
        />
      ) : sessions.length === 0 ? (
        <EmptyState
          icon={<Sparkles className="h-6 w-6" />}
          title="No Autonomous Research Sessions Yet"
          description="Formulate a testable scientific objective to let the autonomous agent inspect your cancer transcriptomics dataset, design an experiment plan, and run verified analyses."
          actionLabel={user?.role !== 'VIEWER' ? "Launch First Research Session" : undefined}
          onAction={user?.role !== 'VIEWER' ? () => setIsNewSessionOpen(true) : undefined}
          actionIcon={<Plus className="h-4 w-4" />}
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Session Selector Sidebar */}
          <div className="lg:col-span-4 space-y-3">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400 px-1">
              <span>Research Investigations ({sessions.length})</span>
              <button
                onClick={() => activeSession && refreshSessionDetails(activeSession.id)}
                className="hover:text-cyan-400 flex items-center gap-1"
                title="Refresh sessions"
              >
                <RefreshCw className="h-3 w-3" /> Refresh
              </button>
            </div>

            <div className="space-y-2 max-h-[750px] overflow-y-auto pr-1">
              {sessions.map((s) => {
                const isSelected = activeSession?.id === s.id;
                return (
                  <div
                    key={s.id}
                    onClick={() => selectSession(s)}
                    className={`p-3.5 rounded-xl border transition-all cursor-pointer text-left ${
                      isSelected
                        ? 'bg-slate-900 border-cyan-500/60 shadow-lg shadow-cyan-950/20'
                        : 'bg-slate-900/40 border-slate-800 hover:border-slate-700 hover:bg-slate-900/60'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="text-sm font-semibold text-slate-200 line-clamp-1">
                        {s.title}
                      </h4>
                      <Badge variant={getStatusBadgeVariant(s.status) as any} size="sm">
                        {s.status}
                      </Badge>
                    </div>

                    <p className="text-xs text-slate-400 line-clamp-2 mt-1">
                      {s.objective}
                    </p>

                    <div className="flex items-center justify-between text-[11px] text-slate-500 font-mono mt-2 pt-2 border-t border-slate-800/60">
                      <span>Step: {s.current_step}</span>
                      <span>{new Date(s.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Active Session Detail */}
          {activeSession && (
            <div className="lg:col-span-8 space-y-5">
              {/* Session Header Card */}
              <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 relative overflow-hidden">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-slate-100">
                        {activeSession.title}
                      </h2>
                      <Badge
                        variant={getStatusBadgeVariant(activeSession.status) as any}
                        size="md"
                      >
                        {activeSession.status}
                      </Badge>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                      <strong className="text-slate-300">Objective:</strong>{' '}
                      {activeSession.objective}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
                    {activeSession.status === 'Awaiting Approval' && user?.role !== 'VIEWER' && (
                      <div className="flex items-center gap-2">
                        <Button
                          variant="primary"
                          size="sm"
                          icon={<Check className="h-4 w-4" />}
                          onClick={handleApprovePlan}
                          isLoading={isActionPending}
                        >
                          Approve Plan
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={<X className="h-4 w-4" />}
                          onClick={() => setIsRejectOpen(true)}
                          disabled={isActionPending}
                        >
                          Reject
                        </Button>
                      </div>
                    )}

                    {['Stopped', 'Failed'].includes(activeSession.status) &&
                      user?.role !== 'VIEWER' && (
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={<Play className="h-4 w-4" />}
                          onClick={handleContinueSession}
                          isLoading={isActionPending}
                        >
                          Resume Session
                        </Button>
                      )}
                  </div>
                </div>

                {/* Sub-bar with metadata badges */}
                <div className="mt-4 pt-3 border-t border-slate-800 flex flex-wrap items-center gap-4 text-xs font-mono text-slate-400">
                  <div className="flex items-center gap-1.5">
                    <Database className="h-3.5 w-3.5 text-cyan-400" />
                    <span>Dataset ID: {activeSession.dataset_id.slice(0, 8)}...</span>
                  </div>
                  {activeSession.dataset_hash && (
                    <div className="flex items-center gap-1.5">
                      <Shield className="h-3.5 w-3.5 text-emerald-400" />
                      <span>Hash: {activeSession.dataset_hash.slice(0, 10)}...</span>
                    </div>
                  )}
                  <div className="flex items-center gap-1.5">
                    <Layers className="h-3.5 w-3.5 text-purple-400" />
                    <span>Iteration: {activeSession.iteration_count} / {activeSession.max_iterations}</span>
                  </div>
                </div>

                {/* Visual Workflow Stage Progression Tracker */}
                <div className="mt-4 pt-3 border-t border-slate-800">
                  <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 mb-2">
                    <span className="uppercase text-slate-500 font-semibold tracking-wider">Agent Lifecycle Pipeline:</span>
                    <span>
                      Stage {Math.min(getWorkflowStageIndex(activeSession.status, activeSession.current_step) + 1, 6)} of 6
                    </span>
                  </div>
                  <div className="grid grid-cols-6 gap-1.5 text-center text-[10px] font-mono">
                    {[
                      { label: 'Connecting & Inspecting', idx: 0 },
                      { label: 'Planning Research', idx: 1 },
                      { label: 'Human Safety Gate', idx: 2 },
                      { label: 'Sandbox Execution', idx: 3 },
                      { label: 'Evaluating Findings', idx: 4 },
                      { label: 'Report Synthesis', idx: 5 },
                    ].map((st) => {
                      const currentIdx = getWorkflowStageIndex(activeSession.status, activeSession.current_step);
                      const isPast = currentIdx > st.idx || activeSession.status === 'Completed';
                      const isCurrent = currentIdx === st.idx && activeSession.status !== 'Completed' && activeSession.status !== 'Failed';
                      const isFailed = activeSession.status === 'Failed' && currentIdx === st.idx;

                      return (
                        <div
                          key={st.idx}
                          className={`py-1.5 px-1 rounded border transition-all truncate ${
                            isFailed
                              ? 'bg-rose-950/60 border-rose-600/60 text-rose-300'
                              : isCurrent
                              ? 'bg-cyan-950/70 border-cyan-500/70 text-cyan-300 font-semibold shadow-sm shadow-cyan-950 animate-pulse'
                              : isPast
                              ? 'bg-emerald-950/40 border-emerald-800/50 text-emerald-300'
                              : 'bg-slate-900/40 border-slate-800 text-slate-600'
                          }`}
                          title={st.label}
                        >
                          {st.label}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Researcher-Friendly Failure Alert Banner if Failed */}
              {activeSession.status === 'Failed' && (
                <div className="p-4 rounded-xl bg-rose-950/30 border border-rose-800/50 text-rose-200 space-y-2">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-rose-300">
                        Investigation Halted
                      </h4>
                      <p className="text-xs text-rose-300/80 leading-relaxed">
                        {formatResearcherFriendlyFailure(activeSession.failure_reason)}
                      </p>
                    </div>
                  </div>
                  {user?.role !== 'VIEWER' && (
                    <div className="pt-2 flex items-center gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Play className="h-3.5 w-3.5" />}
                        onClick={handleContinueSession}
                        isLoading={isActionPending}
                      >
                        Resume Session
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {/* Workspace Navigation Tabs */}
              <div className="flex border-b border-slate-800 text-sm font-medium">
                <button
                  onClick={() => setActiveTab('plan')}
                  className={`pb-3 px-4 border-b-2 transition-all flex items-center gap-2 ${
                    activeTab === 'plan'
                      ? 'border-cyan-500 text-cyan-400'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <FileText className="h-4 w-4" />
                  Research Plan
                  {activeSession.approval_state === 'Pending' && (
                    <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
                  )}
                </button>
                <button
                  onClick={() => setActiveTab('timeline')}
                  className={`pb-3 px-4 border-b-2 transition-all flex items-center gap-2 ${
                    activeTab === 'timeline'
                      ? 'border-cyan-500 text-cyan-400'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Activity className="h-4 w-4" />
                  Live Timeline ({events.length})
                </button>
                <button
                  onClick={() => setActiveTab('evidence')}
                  className={`pb-3 px-4 border-b-2 transition-all flex items-center gap-2 ${
                    activeTab === 'evidence'
                      ? 'border-cyan-500 text-cyan-400'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <BarChart2 className="h-4 w-4" />
                  Evidence Inspector ({activeSession.evidence_store?.length || 0})
                </button>
                <button
                  onClick={() => setActiveTab('report')}
                  className={`pb-3 px-4 border-b-2 transition-all flex items-center gap-2 ${
                    activeTab === 'report'
                      ? 'border-cyan-500 text-cyan-400'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Sparkles className="h-4 w-4" />
                  Scientific Report
                  {activeSession.status === 'Completed' && (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                      Ready
                    </span>
                  )}
                </button>
              </div>

              {/* Tab 1: Research Plan & Human Safety Gate */}
              {activeTab === 'plan' && (
                <div className="space-y-4">
                  {/* Safety Gate Alert if Awaiting Approval */}
                  {activeSession.status === 'Awaiting Approval' && (
                    <div className="p-4 rounded-xl bg-amber-950/30 border border-amber-600/40 text-amber-200 space-y-3">
                      <div className="flex items-start gap-3">
                        <Shield className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
                        <div>
                          <h4 className="text-sm font-bold text-amber-300">
                            Human-in-the-Loop Verification Gate Active
                          </h4>
                          <p className="text-xs text-amber-300/80 mt-1">
                            The autonomous agent formulated the following structured research plan based on empirical dataset inspection.
                            Per Blast Radius Zero protocols, no experiment or Docker sandbox code will run until you approve this plan.
                          </p>
                        </div>
                      </div>

                      {user?.role !== 'VIEWER' && (
                        <div className="flex items-center gap-3 pt-2">
                          <Button
                            variant="primary"
                            size="sm"
                            icon={<Check className="h-4 w-4" />}
                            onClick={handleApprovePlan}
                            isLoading={isActionPending}
                          >
                            Approve & Execute Experiments
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            icon={<X className="h-4 w-4" />}
                            onClick={() => setIsRejectOpen(true)}
                            disabled={isActionPending}
                          >
                            Reject Plan
                          </Button>
                        </div>
                      )}
                    </div>
                  )}

                  {activeSession.research_plan ? (
                    <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-6">
                      {/* Observed Facts */}
                      <div>
                        <h4 className="text-xs font-semibold font-mono uppercase tracking-wider text-cyan-400 mb-2">
                          1. Observed Dataset Facts
                        </h4>
                        <ul className="space-y-1.5 text-xs text-slate-300">
                          {activeSession.research_plan.observed_facts?.map(
                            (fact: string, idx: number) => (
                              <li key={idx} className="flex items-start gap-2">
                                <span className="text-cyan-500 font-bold">•</span>
                                <span>{fact}</span>
                              </li>
                            )
                          )}
                        </ul>
                      </div>

                      {/* Hypotheses & Assumptions */}
                      <div>
                        <h4 className="text-xs font-semibold font-mono uppercase tracking-wider text-purple-400 mb-2">
                          2. Scientific Hypotheses & Assumptions
                        </h4>
                        <ul className="space-y-1.5 text-xs text-slate-300">
                          {activeSession.research_plan.assumptions_hypotheses?.map(
                            (hyp: string, idx: number) => (
                              <li key={idx} className="flex items-start gap-2">
                                <span className="text-purple-500 font-bold">•</span>
                                <span>{hyp}</span>
                              </li>
                            )
                          )}
                        </ul>
                      </div>

                      {/* Proposed Experiments */}
                      <div>
                        <h4 className="text-xs font-semibold font-mono uppercase tracking-wider text-emerald-400 mb-2">
                          3. Proposed Experiments (Controlled Scientific Registry)
                        </h4>
                        <div className="space-y-2">
                          {activeSession.research_plan.proposed_experiments?.map(
                            (exp: any, idx: number) => (
                              <div
                                key={idx}
                                className="p-3 rounded-xl bg-slate-950/70 border border-slate-800 text-xs space-y-1"
                              >
                                <div className="flex items-center justify-between">
                                  <span className="font-mono font-bold text-slate-200">
                                    Tool: {exp.tool_name}
                                  </span>
                                  <span className="text-[10px] px-2 py-0.5 rounded bg-slate-900 border border-slate-700 text-slate-300">
                                    Isolated Execution
                                  </span>
                                </div>
                                <p className="text-slate-300">{exp.description}</p>
                                <p className="text-slate-400 text-[11px]">
                                  <strong className="text-slate-400">Rationale:</strong>{' '}
                                  {exp.rationale}
                                </p>
                              </div>
                            )
                          )}
                        </div>
                      </div>

                      {/* Limitations */}
                      <div>
                        <h4 className="text-xs font-semibold font-mono uppercase tracking-wider text-rose-400 mb-2">
                          4. Scientific Caveats & Limitations
                        </h4>
                        <ul className="space-y-1.5 text-xs text-slate-400">
                          {activeSession.research_plan.scientific_limitations?.map(
                            (lim: string, idx: number) => (
                              <li key={idx} className="flex items-start gap-2">
                                <span className="text-rose-500 font-bold">•</span>
                                <span>{lim}</span>
                              </li>
                            )
                          )}
                        </ul>
                      </div>
                    </div>
                  ) : (
                    <div className="p-8 text-center text-slate-500 text-xs font-mono">
                      Formulating research plan via Vultr Serverless Inference...
                    </div>
                  )}
                </div>
              )}

              {/* Tab 2: Live Timeline */}
              {activeTab === 'timeline' && (
                <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-200">
                      Audit Trail & Execution Steps
                    </h3>
                    <span className="text-xs font-mono text-slate-500">
                      {events.length} recorded events
                    </span>
                  </div>

                  <div className="relative border-l border-slate-800 ml-3 space-y-6">
                    {events.map((ev, idx) => (
                      <div key={ev.id || idx} className="relative pl-6">
                        <div className="absolute -left-2 top-1 h-4 w-4 rounded-full bg-slate-950 border-2 border-cyan-500" />
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-bold text-slate-300">
                              {ev.step_name}
                            </span>
                            <Badge variant="cyan" size="sm">
                              {ev.event_type}
                            </Badge>
                            <span className="text-[11px] font-mono text-slate-500">
                              {new Date(ev.created_at).toLocaleTimeString()}
                            </span>
                          </div>
                          <p className="text-xs text-slate-300">{ev.message}</p>
                          {ev.payload && (
                            <details className="mt-2 text-[11px] font-mono bg-slate-950/80 p-2.5 rounded-lg border border-slate-800/80 text-slate-400">
                              <summary className="cursor-pointer text-cyan-400 hover:text-cyan-300">
                                View Event Metadata
                              </summary>
                              <pre className="mt-2 overflow-x-auto text-[10px] text-slate-300">
                                {JSON.stringify(ev.payload, null, 2)}
                              </pre>
                            </details>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tab 3: Evidence Store */}
              {activeTab === 'evidence' && (
                <div className="space-y-4">
                  {(!activeSession.evidence_store || activeSession.evidence_store.length === 0) ? (
                    <div className="p-8 text-center text-slate-500 text-xs font-mono">
                      No empirical evidence accumulated yet.
                    </div>
                  ) : (
                    activeSession.evidence_store.map((item: any, idx: number) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono font-bold text-cyan-400">
                            Evidence Source: {item.type || 'empirical_metric'}
                          </span>
                          {item.experiment_id && (
                            <span className="text-[10px] font-mono text-slate-400">
                              Exp ID: {item.experiment_id.slice(0, 8)}...
                            </span>
                          )}
                        </div>

                        <p className="text-xs text-slate-300">{item.summary}</p>

                        {/* Top candidate genes if differential expression */}
                        {item.top_significant_features && item.top_significant_features.length > 0 && (
                          <div className="mt-3 overflow-x-auto">
                            <table className="w-full text-[11px] text-left border-collapse">
                              <thead>
                                <tr className="border-b border-slate-800 text-slate-400 font-mono">
                                  <th className="py-1 px-2">Feature / Gene</th>
                                  <th className="py-1 px-2">log2 FC</th>
                                  <th className="py-1 px-2">FDR q-value</th>
                                  <th className="py-1 px-2">Status</th>
                                </tr>
                              </thead>
                              <tbody>
                                {item.top_significant_features.slice(0, 5).map((f: any, fIdx: number) => (
                                  <tr key={fIdx} className="border-b border-slate-800">
                                    <td className="py-1 px-2 font-mono text-slate-200">
                                      {f.feature_id}
                                    </td>
                                    <td className="py-1 px-2 font-mono text-slate-300">
                                      {typeof f.log2_fc === 'number' ? f.log2_fc.toFixed(3) : 'N/A'}
                                    </td>
                                    <td className="py-1 px-2 font-mono text-slate-300">
                                      {typeof f.adj_p_value === 'number'
                                        ? f.adj_p_value.toExponential(2)
                                        : 'N/A'}
                                    </td>
                                    <td className="py-1 px-2">
                                      <Badge
                                        variant={(f.log2_fc || 0) > 0 ? 'emerald' : 'rose'}
                                        size="sm"
                                      >
                                        {(f.log2_fc || 0) > 0 ? 'Upregulated' : 'Downregulated'}
                                      </Badge>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* Tab 4: Final Research Report */}
              {activeTab === 'report' && (
                <div className="p-6 rounded-2xl bg-slate-900/70 border border-slate-800 space-y-6">
                  {activeSession.final_summary ? (
                    <>
                      <div className="border-b border-slate-800 pb-4">
                        <div className="flex items-center gap-2 text-xs font-mono text-cyan-400 uppercase tracking-wider mb-1">
                          <Sparkles className="h-4 w-4" /> Final Scientific Synthesis
                        </div>
                        <h3 className="text-xl font-bold text-slate-100">
                          {activeSession.final_summary.title}
                        </h3>
                        <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                          {activeSession.final_summary.executive_summary}
                        </p>
                      </div>

                      {/* Methodology */}
                      <div>
                        <h4 className="text-xs font-mono font-semibold uppercase text-slate-400 mb-1">
                          Statistical Methodology
                        </h4>
                        <p className="text-xs text-slate-300 leading-relaxed bg-slate-950 p-3 rounded-xl border border-slate-800/80">
                          {activeSession.final_summary.methodology}
                        </p>
                      </div>

                      {/* Key Findings Table */}
                      {activeSession.final_summary.key_findings &&
                        activeSession.final_summary.key_findings.length > 0 && (
                          <div>
                            <h4 className="text-xs font-mono font-semibold uppercase text-slate-400 mb-2">
                              Statistically Significant Findings (FDR Controlled)
                            </h4>
                            <div className="overflow-x-auto rounded-xl border border-slate-800">
                              <table className="w-full text-xs text-left border-collapse bg-slate-950">
                                <thead>
                                  <tr className="border-b border-slate-800 font-mono text-slate-400">
                                    <th className="py-2.5 px-3">Feature</th>
                                    <th className="py-2.5 px-3">log2 FC</th>
                                    <th className="py-2.5 px-3">FDR q-val</th>
                                    <th className="py-2.5 px-3">Regulation</th>
                                    <th className="py-2.5 px-3">Context</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {activeSession.final_summary.key_findings.map(
                                    (kf: any, kIdx: number) => (
                                      <tr key={kIdx} className="border-b border-slate-800">
                                        <td className="py-2 px-3 font-mono font-bold text-slate-200">
                                          {kf.feature_name}
                                        </td>
                                        <td className="py-2 px-3 font-mono text-slate-300">
                                          {typeof kf.log2_fold_change === 'number'
                                            ? kf.log2_fold_change.toFixed(3)
                                            : 'N/A'}
                                        </td>
                                        <td className="py-2 px-3 font-mono text-slate-300">
                                          {typeof kf.fdr_q_value === 'number'
                                            ? kf.fdr_q_value.toExponential(2)
                                            : 'N/A'}
                                        </td>
                                        <td className="py-2 px-3">
                                          <Badge
                                            variant={
                                              kf.regulation_direction === 'Upregulated'
                                                ? 'emerald'
                                                : kf.regulation_direction === 'Downregulated'
                                                ? 'rose'
                                                : 'slate'
                                            }
                                            size="sm"
                                          >
                                            {kf.regulation_direction}
                                          </Badge>
                                        </td>
                                        <td className="py-2 px-3 text-slate-400 text-[11px]">
                                          {kf.biological_context || 'N/A'}
                                        </td>
                                      </tr>
                                    )
                                  )}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                      {/* Caveats and Future Work */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                          <h4 className="text-xs font-mono font-semibold uppercase text-rose-400">
                            Scientific Caveats & Scope
                          </h4>
                          <ul className="space-y-1 text-xs text-slate-400">
                            {activeSession.final_summary.scientific_caveats?.map(
                              (sc: string, idx: number) => (
                                <li key={idx} className="flex items-start gap-1.5">
                                  <span className="text-rose-500 font-bold">•</span>
                                  <span>{sc}</span>
                                </li>
                              )
                            )}
                          </ul>
                        </div>

                        <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                          <h4 className="text-xs font-mono font-semibold uppercase text-cyan-400">
                            Recommended Future Work
                          </h4>
                          <ul className="space-y-1 text-xs text-slate-400">
                            {activeSession.final_summary.recommended_future_work?.map(
                              (rfw: string, idx: number) => (
                                <li key={idx} className="flex items-start gap-1.5">
                                  <span className="text-cyan-500 font-bold">•</span>
                                  <span>{rfw}</span>
                                </li>
                              )
                            )}
                          </ul>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="p-8 text-center text-slate-500 text-xs font-mono">
                      Final scientific report will be synthesized upon experiment completion.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* New Research Session Modal */}
      <Modal
        isOpen={isNewSessionOpen}
        onClose={() => setIsNewSessionOpen(false)}
        title="Launch Autonomous Research Session"
        description="The agent will inspect your transcriptomics dataset and present a plan for approval."
      >
        <form onSubmit={handleLaunchSession} className="space-y-4">
          {formError && (
            <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-300 text-xs">
              {formError}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Target Research Project *
            </label>
            <select
              value={selectedProjectId}
              onChange={(e) => handleProjectChange(e.target.value)}
              className="w-full h-10 px-3 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
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

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Select Dataset *
            </label>
            <select
              value={newDatasetId}
              onChange={(e) => {
                setNewDatasetId(e.target.value);
                const ds = projectDatasets.find((d) => d.id === e.target.value);
                if (ds) {
                  if (ds.control_group) setGroupAName(ds.control_group);
                  if (ds.treatment_group) setGroupBName(ds.treatment_group);
                }
              }}
              className="w-full h-10 px-3 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              required
              disabled={projectDatasets.length === 0}
            >
              <option value="">
                {projectDatasets.length === 0
                  ? '-- No datasets attached to this project --'
                  : '-- Choose an Attached Dataset --'}
              </option>
              {projectDatasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title || d.original_name} ({d.feature_count ?? 0} features, {d.sample_count ?? 0} samples)
                </option>
              ))}
            </select>
            {projectDatasets.length === 0 && (
              <p className="mt-1 text-[11px] text-amber-400">
                No datasets are currently attached to this project. Upload a dataset selecting this project or attach one from the Dataset Library.
              </p>
            )}
          </div>

          <Input
            label="Investigation Title *"
            placeholder="e.g. Transcriptional Alterations in Primary Tumor vs Control"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            required
          />

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Research Objective *
            </label>
            <textarea
              value={newObjective}
              onChange={(e) => setNewObjective(e.target.value)}
              placeholder="State what scientific question or hypothesis you want to explore..."
              rows={3}
              className="w-full p-3 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              required
            />
            <div className="mt-2 space-y-1">
              <span className="text-[11px] text-slate-400">Example templates:</span>
              <div className="flex flex-wrap gap-1.5">
                {objectivePresets.map((preset, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setNewObjective(preset)}
                    className="text-[10px] text-left px-2 py-1 bg-slate-800/80 hover:bg-slate-800 text-slate-300 rounded border border-slate-700 line-clamp-1"
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-1">
            <Input
              label="Group A (Control)"
              placeholder="Control"
              value={groupAName}
              onChange={(e) => setGroupAName(e.target.value)}
            />
            <Input
              label="Group B (Treatment)"
              placeholder="Treatment"
              value={groupBName}
              onChange={(e) => setGroupBName(e.target.value)}
            />
          </div>

          <div className="p-3 rounded-lg bg-cyan-950/40 border border-cyan-800/50 text-[11px] text-cyan-300 flex items-start gap-2">
            <Shield className="h-4 w-4 text-cyan-400 shrink-0 mt-0.5" />
            <span>
              <strong>Blast Radius Zero Guarantee:</strong> The autonomous agent plans experiments and interprets results via Vultr Serverless Inference. All calculations occur in the deterministic statistical engine and isolated Docker sandbox.
            </span>
          </div>

          <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsNewSessionOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isSubmitting}
              icon={<Sparkles className="h-4 w-4" />}
            >
              Launch Session
            </Button>
          </div>
        </form>
      </Modal>

      {/* Reject Plan Modal */}
      <Modal
        isOpen={isRejectOpen}
        onClose={() => setIsRejectOpen(false)}
        title="Reject Research Plan"
        description="State why the plan is rejected so the agent halts and records your guidance."
      >
        <div className="space-y-4">
          <textarea
            value={rejectNotes}
            onChange={(e) => setRejectNotes(e.target.value)}
            placeholder="e.g. Statistical thresholds are too permissive; require strict FDR < 0.01 with exploratory PCA first."
            rows={4}
            className="w-full p-3 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-rose-500"
            required
          />

          <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsRejectOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={handleRejectPlan}
              isLoading={isActionPending}
            >
              Confirm Rejection
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
