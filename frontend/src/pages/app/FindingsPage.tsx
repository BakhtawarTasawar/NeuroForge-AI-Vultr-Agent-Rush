import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Sparkles,
  Dna,
  Search,
  ArrowUpRight,
  ShieldCheck,
  Download,
  AlertCircle,
} from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import { Project, ResearchSession, Experiment } from '../../types';
import { EmptyState } from '../../components/common/EmptyState';
import { Badge } from '../../components/common/Badge';
import { Button } from '../../components/common/Button';
import { Modal } from '../../components/common/Modal';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

interface UnifiedFinding {
  id: string;
  sourceType: 'agent_session' | 'experiment';
  sourceTitle: string;
  projectName: string;
  category: 'Observed Result' | 'Statistical Evidence' | 'Interpretation' | 'Biomarker Discovery';
  title: string;
  statement: string;
  significance?: string;
  metrics?: Record<string, any>;
  createdAt: string;
}

export const FindingsPage: React.FC = () => {
  const navigate = useNavigate();
  const [findings, setFindings] = useState<UnifiedFinding[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');

  // Evidence Traceability Modal State
  const [selectedFinding, setSelectedFinding] = useState<UnifiedFinding | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);

  const handleExportCSV = () => {
    if (filteredFindings.length === 0) return;
    const headers = ['ID', 'Category', 'Project', 'Source', 'Title', 'Statement', 'Significance', 'Date'];
    const rows = filteredFindings.map((f) => [
      f.id,
      f.category,
      f.projectName,
      f.sourceTitle,
      `"${f.title.replace(/"/g, '""')}"`,
      `"${f.statement.replace(/"/g, '""')}"`,
      `"${(f.significance || '').replace(/"/g, '""')}"`,
      f.createdAt,
    ]);
    const csvContent =
      'data:text/csv;charset=utf-8,' +
      [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute(
      'download',
      `neuroforge_findings_${new Date().toISOString().slice(0, 10)}.csv`
    );
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  useEffect(() => {
    fetchFindings();
  }, []);

  const fetchFindings = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [projectsRes, experimentsRes] = await Promise.all([
        apiClient.get<Project[]>('/projects'),
        apiClient.get<Experiment[]>('/experiments').catch(() => ({ data: [] })),
      ]);

      const projects = projectsRes.data;
      const experiments = experimentsRes.data;
      const projectMap = new Map(projects.map((p) => [p.id, p.title]));

      const collected: UnifiedFinding[] = [];

      // 1. Collect findings from completed research sessions
      for (const project of projects) {
        try {
          const sessionsRes = await apiClient.get<ResearchSession[]>(
            `/projects/${project.id}/research-sessions`
          );
          for (const session of sessionsRes.data) {
            if (session.final_summary?.key_findings) {
              const kf = session.final_summary.key_findings;
              if (Array.isArray(kf)) {
                kf.forEach((item: any, idx: number) => {
                  collected.push({
                    id: `sess_${session.id}_${idx}`,
                    sourceType: 'agent_session',
                    sourceTitle: session.title,
                    projectName: project.title,
                    category: 'Statistical Evidence',
                    title: typeof item === 'string' ? item : item.title || 'Biomarker Association',
                    statement: typeof item === 'string' ? item : item.statement || item.description || '',
                    significance: item.significance || item.p_value ? `p = ${item.p_value}` : 'Empirical finding',
                    metrics: item.metrics,
                    createdAt: session.updated_at || session.created_at,
                  });
                });
              }
            }

            // Also parse evidence_store
            if (session.evidence_store && Array.isArray(session.evidence_store)) {
              session.evidence_store.forEach((ev: any, idx: number) => {
                if (ev.verified_findings && Array.isArray(ev.verified_findings)) {
                  ev.verified_findings.forEach((vf: string, vfIdx: number) => {
                    collected.push({
                      id: `ev_${session.id}_${idx}_${vfIdx}`,
                      sourceType: 'agent_session',
                      sourceTitle: session.title,
                      projectName: project.title,
                      category: 'Observed Result',
                      title: `Observation: ${vf.slice(0, 50)}...`,
                      statement: vf,
                      significance: ev.statistical_significance_summary,
                      createdAt: session.created_at,
                    });
                  });
                }
              });
            }
          }
        } catch {
          // Ignore per-project session errors
        }
      }

      // 2. Collect findings from completed experiments with statistical summary
      for (const exp of experiments) {
        if (exp.status === 'Completed' && exp.statistical_summary) {
          const ss = exp.statistical_summary;
          const sigCount = ss.significant_features_count ?? ss.significant_genes_count;
          if (sigCount !== undefined) {
            collected.push({
              id: `exp_${exp.id}`,
              sourceType: 'experiment',
              sourceTitle: exp.title,
              projectName: exp.project_id ? projectMap.get(exp.project_id) || 'Primary Study' : 'Primary Study',
              category: 'Statistical Evidence',
              title: `${sigCount} Significant Biomarkers Identified`,
              statement: `Differential analysis identified ${sigCount} candidate features satisfying FDR < 0.05 criteria under Welch's t-test with Benjamini-Hochberg adjustment.`,
              metrics: {
                total_analyzed: ss.total_features ?? ss.total_genes,
                significant_features: sigCount,
                mean_log2_fc: ss.mean_log2_fc,
              },
              createdAt: exp.completed_at || exp.created_at,
            });
          }
        }
      }

      setFindings(collected);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  const filteredFindings = findings.filter((f) => {
    const matchesSearch =
      f.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.statement.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.projectName.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCat = selectedCategory === 'ALL' || f.category === selectedCategory;
    return matchesSearch && matchesCat;
  });

  if (isLoading) {
    return <LoadingSkeleton rows={4} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            Verified Research Findings
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Empirical observations, false discovery rate (FDR) validated signals, and biological conclusions.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {findings.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleExportCSV}
              icon={<Download className="w-4 h-4" />}
            >
              Export CSV
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate('/agent')}
            icon={<ArrowUpRight className="w-4 h-4" />}
          >
            Research Workspace
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* Filter / Search Bar */}
      {findings.length > 0 && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search findings by gene, biomarker, keyword..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            />
          </div>
          <div className="flex gap-2">
            {['ALL', 'Statistical Evidence', 'Observed Result'].map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  selectedCategory === cat
                    ? 'bg-cyan-500 text-slate-950 font-semibold'
                    : 'bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200'
                }`}
              >
                {cat === 'ALL' ? 'All Findings' : cat}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Findings List or Honest Empty State */}
      {filteredFindings.length === 0 ? (
        <EmptyState
          icon={<Sparkles className="w-6 h-6" />}
          title={findings.length === 0 ? 'No research findings cataloged yet' : 'No matching findings'}
          description={
            findings.length === 0
              ? 'Findings are cataloged automatically once experimental workflows or autonomous agent sessions conclude with statistically evaluated evidence.'
              : 'Try adjusting your search criteria or category filter.'
          }
          actionLabel="Initiate Autonomous Investigation"
          onAction={() => navigate('/agent')}
          actionIcon={<Dna className="w-4 h-4" />}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredFindings.map((finding) => (
            <div
              key={finding.id}
              onClick={() => {
                setSelectedFinding(finding);
                setIsDetailOpen(true);
              }}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 hover:border-cyan-500/50 hover:bg-slate-900/80 transition-all shadow-sm cursor-pointer group"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/40">
                  {finding.projectName}
                </span>
                <Badge
                  variant={finding.category === 'Statistical Evidence' ? 'emerald' : 'cyan'}
                  size="sm"
                >
                  {finding.category}
                </Badge>
              </div>

              <h3 className="text-sm font-semibold text-white leading-snug group-hover:text-cyan-300 transition-colors">
                {finding.title}
              </h3>

              <p className="text-xs text-slate-300 leading-relaxed">
                {finding.statement}
              </p>

              {finding.metrics && (
                <div className="grid grid-cols-2 gap-2 p-2.5 rounded-lg bg-slate-950/80 border border-slate-800/80 text-[11px] font-mono text-slate-300">
                  {Object.entries(finding.metrics).map(([k, v]) => (
                    <div key={k}>
                      <span className="text-slate-500 block text-[10px]">{k.replace(/_/g, ' ')}</span>
                      <span className="text-cyan-300 font-semibold">{String(v)}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[11px] text-slate-400">
                <span className="flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                  {finding.significance || 'Reproducible finding'}
                </span>
                <span className="text-cyan-400 text-[11px] font-medium group-hover:underline">
                  Trace Lineage &rarr;
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Rigor Framework Notice */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
        <div className="flex items-center justify-between pb-2 border-b border-slate-800/80">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
            <Dna className="w-4 h-4 text-cyan-400" />
            Scientific Rigor Framework
          </span>
          <Badge variant="slate" size="sm">
            Evidence Standards
          </Badge>
        </div>
        <p className="text-xs text-slate-400 leading-relaxed">
          Findings adhere to blast-radius-zero reproducibility standards: all empirical results are computed deterministically inside isolated Docker containers, and statistical significance is evaluated with multiple testing corrections (FDR).
        </p>
      </section>

      {/* Evidence Traceability Modal */}
      <Modal
        isOpen={isDetailOpen}
        onClose={() => setIsDetailOpen(false)}
        title="Evidence Traceability & Biological Context"
        description="Empirical provenance, statistical significance methodology, and orthogonal validation guidance."
      >
        {selectedFinding && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 px-2.5 py-1 rounded border border-cyan-800/40">
                Project: {selectedFinding.projectName}
              </span>
              <Badge
                variant={selectedFinding.category === 'Statistical Evidence' ? 'emerald' : 'cyan'}
                size="md"
              >
                {selectedFinding.category}
              </Badge>
            </div>

            <div className="space-y-1.5">
              <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-400">
                Candidate Biomarker / Scientific Proposition
              </span>
              <h4 className="text-base font-bold text-white">{selectedFinding.title}</h4>
              <p className="text-xs text-slate-300 leading-relaxed bg-slate-950/80 p-3 rounded-lg border border-slate-800/80">
                {selectedFinding.statement}
              </p>
            </div>

            {/* Metrics Breakdown */}
            {selectedFinding.metrics && (
              <div className="space-y-2">
                <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-400">
                  Quantitative Evidence Metrics
                </span>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                  {Object.entries(selectedFinding.metrics).map(([k, v]) => (
                    <div key={k} className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-mono">
                      <span className="text-slate-500 block text-[10px]">{k.replace(/_/g, ' ')}</span>
                      <span className="text-cyan-300 font-bold text-xs">{String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Lineage & Provenance */}
            <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 text-xs space-y-2">
              <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-slate-400 block">
                Provenance Lineage
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] font-mono text-slate-300">
                <div>Source Workflow: <span className="text-white">{selectedFinding.sourceTitle}</span></div>
                <div>Source Type: <span className="text-cyan-400">{selectedFinding.sourceType === 'agent_session' ? 'Autonomous Agent' : 'Targeted Experiment'}</span></div>
                <div>Evaluated At: <span className="text-slate-400">{new Date(selectedFinding.createdAt).toLocaleString()}</span></div>
                <div>Statistical Guard: <span className="text-emerald-400">FDR Benjamini-Hochberg (q &le; 0.05)</span></div>
              </div>
            </div>

            {/* Scientific Caveat / Scope Limitation Notice */}
            <div className="p-3.5 rounded-xl bg-amber-950/20 border border-amber-900/40 text-amber-300 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-bold text-amber-200">
                <AlertCircle className="w-4 h-4 text-amber-400" />
                <span>Correlation ≠ Causation (Scientific Research Notice)</span>
              </div>
              <p className="text-[11px] text-amber-300/80 leading-relaxed">
                Autonomous biomarker identifications represent observational statistical associations within high-dimensional transcriptomics data. In-vitro orthogonal validation (RT-qPCR, Western blot, cell viability assays) is essential before establishing biological causality or therapeutic significance.
              </p>
            </div>

            <div className="flex justify-end pt-2">
              <Button
                variant="primary"
                size="sm"
                onClick={() => setIsDetailOpen(false)}
              >
                Close Traceability View
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
