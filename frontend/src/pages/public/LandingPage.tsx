import React from 'react';
import { Link } from 'react-router-dom';
import {
  Dna,
  Shield,
  ArrowRight,
  Cpu,
  CheckCircle2,
  Lock,
} from 'lucide-react';
import { Button } from '../../components/common/Button';

export const LandingPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col selection:bg-cyan-500 selection:text-white">
      {/* Navigation */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Dna className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="text-xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-200 to-cyan-300">
                NeuroForge AI
              </span>
              <span className="hidden sm:inline-block ml-3 px-2 py-0.5 text-xs font-medium rounded-full bg-cyan-950/80 text-cyan-400 border border-cyan-800/60">
                Blast Radius Zero
              </span>
            </div>
          </div>

          <div className="flex items-center space-x-3 sm:space-x-4">
            <Link to="/signin">
              <Button variant="ghost" size="sm">
                Sign In
              </Button>
            </Link>
            <Link to="/register">
              <Button size="sm" icon={<ArrowRight className="w-4 h-4" />}>
                Get Started
              </Button>
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative overflow-hidden py-16 sm:py-24 border-b border-slate-800/60">
        <div className="absolute top-0 right-1/4 -mt-20 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 text-center space-y-6">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-slate-900 border border-slate-800 text-xs font-medium text-cyan-400">
            <Shield className="w-3.5 h-3.5 text-cyan-400" />
            <span>Autonomous Scientific Discovery Platform</span>
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-white max-w-4xl mx-auto leading-tight">
            Autonomous Experimentation for High-Dimensional Scientific Data
          </h1>

          <p className="text-base sm:text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
            NeuroForge AI formulates testable scientific hypotheses, plans machine learning and statistical workflows, and executes experiments inside zero-blast-radius isolated environments.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-4">
            <Link to="/register" className="w-full sm:w-auto">
              <Button size="lg" className="w-full sm:w-auto text-sm font-semibold" icon={<ArrowRight className="w-4 h-4" />}>
                Create Researcher Account
              </Button>
            </Link>
            <Link to="/signin" className="w-full sm:w-auto">
              <Button variant="secondary" size="lg" className="w-full sm:w-auto text-sm">
                Sign In to Workspace
              </Button>
            </Link>
          </div>

          <div className="pt-6 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400">
            <Lock className="w-3.5 h-3.5 text-cyan-400" />
            <span>Scientific research platform &bull; Not designed or marketed for clinical diagnosis or medical treatment.</span>
          </div>
        </div>
      </section>

      {/* How it Works / Workflow */}
      <section className="py-16 sm:py-20 border-b border-slate-800/60 bg-slate-900/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-12">
          <div className="text-center space-y-2">
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">
              The Autonomous Scientific Workflow
            </h2>
            <p className="text-sm text-slate-400 max-w-xl mx-auto">
              Transforming complex multi-dimensional datasets into verified, reproducible scientific discoveries.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-3">
              <div className="h-10 w-10 rounded-lg bg-cyan-950/80 border border-cyan-800/60 flex items-center justify-center text-cyan-400 font-bold">
                1
              </div>
              <h3 className="text-base font-semibold text-white">Data Ingestion</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Upload cancer transcriptomics and gene expression matrices with automated structural integrity and dimension checks.
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-3">
              <div className="h-10 w-10 rounded-lg bg-cyan-950/80 border border-cyan-800/60 flex items-center justify-center text-cyan-400 font-bold">
                2
              </div>
              <h3 className="text-base font-semibold text-white">Hypothesis Formulation</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Autonomous identification of differential expression patterns and formulation of mathematically testable research questions.
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-3">
              <div className="h-10 w-10 rounded-lg bg-cyan-950/80 border border-cyan-800/60 flex items-center justify-center text-cyan-400 font-bold">
                3
              </div>
              <h3 className="text-base font-semibold text-white">Isolated Execution</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Execution of machine learning and statistical pipelines within containerized sandbox environments with zero blast radius.
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-3">
              <div className="h-10 w-10 rounded-lg bg-cyan-950/80 border border-cyan-800/60 flex items-center justify-center text-cyan-400 font-bold">
                4
              </div>
              <h3 className="text-base font-semibold text-white">Evidence Evaluation</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Rigorous statistical significance evaluation, distinguishing correlation from causation, and generating reproducible reports.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Core Principles */}
      <section className="py-16 sm:py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-12">
          <div className="text-center space-y-2">
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">
              Built on Scientific Rigor &amp; Security
            </h2>
            <p className="text-sm text-slate-400 max-w-xl mx-auto">
              Engineered specifically for laboratory researchers, not software engineers.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-3">
              <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/60 w-fit text-cyan-400">
                <Shield className="w-5 h-5" />
              </div>
              <h3 className="text-base font-semibold text-white">Zero Blast Radius Isolation</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Scientific computation code runs in constrained, isolated environments with strict memory boundaries and execution timeouts.
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-3">
              <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/60 w-fit text-cyan-400">
                <CheckCircle2 className="w-5 h-5" />
              </div>
              <h3 className="text-base font-semibold text-white">No Fabricated Discoveries</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Every metric, p-value, and finding displayed on the platform derives strictly from real computational evidence, never simulated placeholders.
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-3">
              <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/60 w-fit text-cyan-400">
                <Cpu className="w-5 h-5" />
              </div>
              <h3 className="text-base font-semibold text-white">Researcher-First Interface</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Technical complexity like containers, API endpoints, tokens, and database schemas remain behind the scenes so scientists can focus on discovery.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="mt-auto border-t border-slate-800/80 bg-slate-950 py-8 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Dna className="w-4 h-4 text-cyan-400" />
            <span className="font-semibold text-slate-300">NeuroForge AI</span>
            <span>&bull; Autonomous Scientific Discovery Platform</span>
          </div>
          <div className="flex items-center gap-4">
            <span>Challenge 1: Blast Radius Zero</span>
            <span>Vultr Agent Rush</span>
          </div>
        </div>
      </footer>
    </div>
  );
};
