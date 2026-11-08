import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  FolderGit2,
  Database,
  FlaskConical,
  FileText,
  Plus,
  Upload,
  Dna,
  Shield,
  Activity,
} from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import { OverviewStats } from '../../types';
import { StatCard } from '../../components/common/StatCard';
import { Button } from '../../components/common/Button';
import { Badge } from '../../components/common/Badge';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';

export const OverviewPage: React.FC = () => {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const navigate = useNavigate();

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await apiClient.get<OverviewStats>('/overview/stats');
        setStats(res.data);
      } catch (err) {
        setError(formatErrorMessage(err));
      } finally {
        setIsLoading(false);
      }
    };
    fetchStats();
  }, []);

  if (isLoading) {
    return <LoadingSkeleton rows={3} />;
  }

  return (
    <div className="space-y-8">
      {error && (
        <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
          {error}
        </div>
      )}
      {/* Scope Banner */}
      <section className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-900/90 to-slate-950 p-6 sm:p-8 shadow-2xl">
        <div className="absolute top-0 right-0 -mt-10 -mr-10 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="relative z-10 max-w-3xl space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-md bg-slate-800/80 border border-slate-700 text-xs font-mono text-cyan-300">
            <Activity className="w-3.5 h-3.5 text-cyan-400" />
            <span>Autonomous Scientific Experimentation Platform</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">
            Cancer Gene-Expression Research Workspace
          </h2>
          <p className="text-slate-400 text-xs sm:text-sm leading-relaxed">
            Formulate testable transcriptomic hypotheses, plan machine learning validation pipelines, and evaluate statistical evidence within isolated zero-blast-radius execution environments.
          </p>
          <div className="pt-2 text-xs text-slate-500 flex items-center gap-2">
            <Shield className="w-4 h-4 text-slate-400" />
            <span>Scientific research &amp; discovery platform &bull; Not for medical diagnosis or clinical treatment.</span>
          </div>
        </div>
      </section>

      {/* Metrics Row (Real Backend Counts Only) */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
        <StatCard
          title="Research Projects"
          value={stats?.projects_count ?? 0}
          subtitle="Accessible projects"
          icon={<FolderGit2 className="w-5 h-5 text-cyan-400" />}
          badge={
            <Badge variant="cyan" size="sm">
              Active
            </Badge>
          }
        />
        <StatCard
          title="Uploaded Datasets"
          value={stats?.datasets_count ?? 0}
          subtitle="Validated matrices"
          icon={<Database className="w-5 h-5 text-cyan-400" />}
          badge={
            <Badge variant="emerald" size="sm">
              Ready
            </Badge>
          }
        />
        <StatCard
          title="Executed Experiments"
          value={stats?.experiments_count ?? 0}
          subtitle="Isolated sandbox runs"
          icon={<FlaskConical className="w-5 h-5 text-cyan-400" />}
          badge={
            <Badge variant="slate" size="sm">
              Standby
            </Badge>
          }
        />
        <StatCard
          title="Verified Reports"
          value={stats?.reports_count ?? 0}
          subtitle="Evidence-backed artifacts"
          icon={<FileText className="w-5 h-5 text-cyan-400" />}
          badge={
            <Badge variant="slate" size="sm">
              Standby
            </Badge>
          }
        />
      </section>

      {/* Primary Action Guidance */}
      {stats?.projects_count === 0 ? (
        <EmptyState
          icon={<FolderGit2 className="w-6 h-6" />}
          title="No research projects created yet"
          description="Begin your autonomous experimentation journey by creating your first cancer gene-expression research project."
          actionLabel="Create Your First Research Project"
          onAction={() => navigate('/projects')}
          actionIcon={<Plus className="w-4 h-4" />}
        />
      ) : (
        <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <FolderGit2 className="w-4 h-4 text-cyan-400" />
                Active Research Operations
              </span>
              <Link to="/projects" className="text-xs text-cyan-400 hover:text-cyan-300">
                View All &rarr;
              </Link>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              You have <strong className="text-white">{stats?.projects_count}</strong> active research projects in your scientific workspace. Open your project library to review or formulate hypotheses.
            </p>
            <div className="pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => navigate('/projects')}
                icon={<FolderGit2 className="w-4 h-4" />}
              >
                Open Project Workspace
              </Button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <Database className="w-4 h-4 text-cyan-400" />
                Dataset Library
              </span>
              <Link to="/datasets" className="text-xs text-cyan-400 hover:text-cyan-300">
                Manage &rarr;
              </Link>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Upload transcriptomics profiles (CSV, TSV, GCT) to validate dimension parameters and prepare for differential expression analysis.
            </p>
            <div className="pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => navigate('/datasets')}
                icon={<Upload className="w-4 h-4" />}
              >
                Upload Research Dataset
              </Button>
            </div>
          </div>
        </section>
      )}

      {/* System Integrity & Pipeline Status */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
            <Dna className="w-4 h-4 text-cyan-400" />
            Autonomous Pipeline Readiness
          </span>
          <Badge variant="cyan" size="sm">
            Phase 1 Foundation
          </Badge>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 text-xs text-slate-300">
          <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-1">
            <span className="font-semibold text-white block">Restricted Docker Execution</span>
            <p className="text-slate-400 text-[11px]">
              Experiments run in restricted containers with network access disabled, a read-only root filesystem, and configured resource limits.
            </p>
          </div>
          <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-1">
            <span className="font-semibold text-white block">Authentication &amp; RBAC</span>
            <p className="text-slate-400 text-[11px]">
              Argon2 password hashing, rotating refresh tokens, and server-side session tracking.
            </p>
          </div>
          <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-1">
            <span className="font-semibold text-white block">Inference Gateway</span>
            <p className="text-slate-400 text-[11px]">
              Prepared for Vultr Serverless Inference LLM orchestration in upcoming milestone.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
};
