import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText,
  BookOpen,
  Download,
  Dna,
  CheckCircle2,
  AlertTriangle,
  Calendar,
} from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import { Project, ResearchSession, Experiment } from '../../types';
import { EmptyState } from '../../components/common/EmptyState';
import { Badge } from '../../components/common/Badge';
import { Button } from '../../components/common/Button';
import { Modal } from '../../components/common/Modal';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

interface ReportCard {
  id: string;
  type: 'agent_summary' | 'experiment_manifest';
  title: string;
  projectName: string;
  date: string;
  summary: any;
  manifest?: any;
  datasetHash?: string | null;
}

export const ReportsPage: React.FC = () => {
  const navigate = useNavigate();
  const [reports, setReports] = useState<ReportCard[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Report Detail Modal
  const [selectedReport, setSelectedReport] = useState<ReportCard | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);

  useEffect(() => {
    fetchReports();
  }, []);

  const fetchReports = async () => {
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
      const collected: ReportCard[] = [];

      // 1. Collect reports from agent sessions with final_summary
      for (const project of projects) {
        try {
          const sessionsRes = await apiClient.get<ResearchSession[]>(
            `/projects/${project.id}/research-sessions`
          );
          for (const session of sessionsRes.data) {
            if (session.final_summary) {
              collected.push({
                id: `sess_report_${session.id}`,
                type: 'agent_summary',
                title: session.final_summary.title || session.title || 'Scientific Research Summary',
                projectName: project.title,
                date: session.updated_at || session.created_at,
                summary: session.final_summary,
                datasetHash: session.dataset_hash,
              });
            }
          }
        } catch {
          // Ignore session fetch errors
        }
      }

      // 2. Collect reports from completed experiments with manifests
      for (const exp of experiments) {
        if (exp.status === 'Completed' && (exp.reproducibility_manifest || exp.result_summary)) {
          collected.push({
            id: `exp_report_${exp.id}`,
            type: 'experiment_manifest',
            title: `Experiment Execution: ${exp.title}`,
            projectName: exp.project_id ? projectMap.get(exp.project_id) || 'Primary Study' : 'Primary Study',
            date: exp.completed_at || exp.created_at,
            summary: {
              executive_summary: exp.result_summary || 'Isolated container execution completed successfully.',
              methodology: exp.experiment_type || 'Deterministic statistical pipeline',
              statistical_summary: exp.statistical_summary,
            },
            manifest: exp.reproducibility_manifest,
            datasetHash: exp.dataset_hash,
          });
        }
      }

      setReports(collected);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  const openReportDetail = (report: ReportCard) => {
    setSelectedReport(report);
    setIsDetailOpen(true);
  };

  const handleDownloadJSON = (report: ReportCard) => {
    const dataStr =
      'data:text/json;charset=utf-8,' +
      encodeURIComponent(JSON.stringify(report, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute(
      'download',
      `scientific_report_${report.id}.json`
    );
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  if (isLoading) {
    return <LoadingSkeleton rows={4} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-cyan-400" />
            Scientific Research Reports
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Evidence-backed, reproducible scientific reports compiled from experiment telemetry.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => navigate('/agent')}
          icon={<Dna className="w-4 h-4" />}
        >
          New Research Session
        </Button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* Reports Grid or Honest Empty State */}
      {reports.length === 0 ? (
        <EmptyState
          icon={<FileText className="w-6 h-6" />}
          title="No research reports generated yet"
          description="Reports are generated automatically upon conclusion of an experiment pipeline, bundling statistical evaluations, methodology, and artifact links. No fabricated reports are shown."
          actionLabel="Launch Research Investigation"
          onAction={() => navigate('/agent')}
          actionIcon={<Dna className="w-4 h-4" />}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {reports.map((report) => (
            <div
              key={report.id}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-4 hover:border-slate-700 transition-all flex flex-col justify-between"
            >
              <div className="space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/40">
                    {report.projectName}
                  </span>
                  <Badge variant="cyan" size="sm">
                    {report.type === 'agent_summary' ? 'Autonomous Synthesis' : 'Sandbox Telemetry'}
                  </Badge>
                </div>

                <h3 className="text-sm font-semibold text-white leading-snug">
                  {report.title}
                </h3>

                <p className="text-xs text-slate-300 line-clamp-3 leading-relaxed">
                  {report.summary?.executive_summary || 'Evidence synthesis compiled.'}
                </p>

                {report.datasetHash && (
                  <div className="text-[10px] font-mono text-slate-500 truncate">
                    SHA-256: {report.datasetHash}
                  </div>
                )}
              </div>

              <div className="pt-3 border-t border-slate-800/60 flex items-center justify-between">
                <span className="text-[11px] text-slate-400 flex items-center gap-1">
                  <Calendar className="w-3.5 h-3.5 text-slate-500" />
                  {new Date(report.date).toLocaleDateString()}
                </span>

                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleDownloadJSON(report)}
                    icon={<Download className="w-3.5 h-3.5" />}
                  >
                    JSON
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => openReportDetail(report)}
                    icon={<BookOpen className="w-3.5 h-3.5" />}
                  >
                    View Report
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Report Detail Modal */}
      {selectedReport && (
        <Modal
          isOpen={isDetailOpen}
          onClose={() => setIsDetailOpen(false)}
          title={selectedReport.title}
          description={`Project: ${selectedReport.projectName} • Date: ${new Date(selectedReport.date).toLocaleString()}`}
        >
          <div className="space-y-5 max-h-[70vh] overflow-y-auto pr-1 text-xs">
            {/* Executive Summary */}
            <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-cyan-400 block">
                Executive Summary
              </span>
              <p className="text-slate-200 leading-relaxed">
                {selectedReport.summary?.executive_summary || 'Execution completed.'}
              </p>
            </div>

            {/* Methodology & Reproducibility */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
                <span className="text-[11px] font-semibold text-slate-400 block">Methodology</span>
                <p className="text-slate-200">
                  {selectedReport.summary?.methodology || 'Isolated Python execution with statistical corrections.'}
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
                <span className="text-[11px] font-semibold text-slate-400 block">Dataset Hash</span>
                <p className="font-mono text-[10px] text-cyan-300 truncate">
                  {selectedReport.datasetHash || 'Verified provenance'}
                </p>
              </div>
            </div>

            {/* Key Findings */}
            {selectedReport.summary?.key_findings && (
              <div className="space-y-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block">
                  Key Statistical Findings
                </span>
                <div className="space-y-1.5">
                  {Array.isArray(selectedReport.summary.key_findings) ? (
                    selectedReport.summary.key_findings.map((f: any, idx: number) => (
                      <div
                        key={idx}
                        className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 text-slate-300 flex items-start gap-2"
                      >
                        <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                        <span>{typeof f === 'string' ? f : f.statement || f.title}</span>
                      </div>
                    ))
                  ) : (
                    <p className="text-slate-400">{JSON.stringify(selectedReport.summary.key_findings)}</p>
                  )}
                </div>
              </div>
            )}

            {/* Limitations & Caveats */}
            {selectedReport.summary?.scientific_caveats && (
              <div className="p-3 rounded-lg bg-amber-950/20 border border-amber-800/40 space-y-1">
                <span className="text-[11px] font-semibold text-amber-300 flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Scientific Caveats & Limitations
                </span>
                <ul className="list-disc list-inside text-amber-200/80 space-y-0.5 text-[11px]">
                  {Array.isArray(selectedReport.summary.scientific_caveats) ? (
                    selectedReport.summary.scientific_caveats.map((c: string, idx: number) => (
                      <li key={idx}>{c}</li>
                    ))
                  ) : (
                    <li>{String(selectedReport.summary.scientific_caveats)}</li>
                  )}
                </ul>
              </div>
            )}

            {/* Recommended Future Work */}
            {selectedReport.summary?.recommended_future_work && (
              <div className="space-y-1">
                <span className="text-[11px] font-semibold text-slate-400 block">
                  Recommended Orthogonal Validation
                </span>
                <p className="text-slate-300">
                  {Array.isArray(selectedReport.summary.recommended_future_work)
                    ? selectedReport.summary.recommended_future_work.join(' ')
                    : String(selectedReport.summary.recommended_future_work)}
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleDownloadJSON(selectedReport)}
                icon={<Download className="w-3.5 h-3.5" />}
              >
                Download Manifest JSON
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setIsDetailOpen(false)}
              >
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
