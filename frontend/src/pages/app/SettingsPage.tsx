import React, { useState } from 'react';
import { Settings, Shield, Lock, CheckCircle2 } from 'lucide-react';
import { Button } from '../../components/common/Button';

export const SettingsPage: React.FC = () => {
  const [compactDensity, setCompactDensity] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const handleSave = () => {
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-white">
          Account Settings
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Functional parameters governing workspace layout, execution security, and sessions.
        </p>
      </div>

      {saveSuccess && (
        <div className="p-3 rounded-lg bg-emerald-950/40 border border-emerald-800/60 text-xs text-emerald-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>Settings saved successfully.</span>
        </div>
      )}

      {/* Security & Authentication Configuration */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
          <Lock className="w-4 h-4 text-cyan-400" />
          Authentication &amp; Session Boundaries
        </h3>

        <div className="space-y-3 text-xs text-slate-300">
          <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800">
            <div>
              <span className="font-semibold text-white block">Access Token Lifespan</span>
              <p className="text-slate-400 text-[11px]">
                Short-lived JWT tokens delivered exclusively through HttpOnly cookies.
              </p>
            </div>
            <span className="font-mono text-cyan-300 bg-cyan-950/60 px-2.5 py-1 rounded border border-cyan-800/60">
              15 Minutes
            </span>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800">
            <div>
              <span className="font-semibold text-white block">Refresh Session Rotation</span>
              <p className="text-slate-400 text-[11px]">
                Server-side session tracking with cryptographic rotation on each token renewal.
              </p>
            </div>
            <span className="font-mono text-cyan-300 bg-cyan-950/60 px-2.5 py-1 rounded border border-cyan-800/60">
              7 Days
            </span>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800">
            <div>
              <span className="font-semibold text-white block">CSRF Double-Submit Validation</span>
              <p className="text-slate-400 text-[11px]">
                State-changing HTTP requests require matching cryptographic CSRF header and cookie tokens.
              </p>
            </div>
            <span className="font-mono text-emerald-400 bg-emerald-950/60 px-2.5 py-1 rounded border border-emerald-800/60">
              Enforced
            </span>
          </div>
        </div>
      </section>

      {/* Execution Environment */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
          <Shield className="w-4 h-4 text-cyan-400" />
          Execution Isolation Policy
        </h3>

        <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2 text-xs text-slate-300">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-white">Blast Radius Zero Sandbox</span>
            <span className="text-emerald-400 font-mono text-[11px]">Docker Configured</span>
          </div>
          <p className="text-slate-400 text-[11px] leading-relaxed">
            All statistical computation tasks run within isolated containerized sandboxes with restricted network capabilities and hard memory ceilings.
          </p>
        </div>
      </section>

      {/* Interface Display Density */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
          <Settings className="w-4 h-4 text-cyan-400" />
          Scientific Interface Preferences
        </h3>

        <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-xs">
          <div>
            <span className="font-semibold text-white block">Compact Table Density</span>
            <p className="text-slate-400 text-[11px]">
              Display denser dataset rows for high-volume genomic screens.
            </p>
          </div>
          <input
            type="checkbox"
            checked={compactDensity}
            onChange={(e) => setCompactDensity(e.target.checked)}
            className="rounded border-slate-700 bg-slate-900 text-cyan-600 focus:ring-cyan-500 h-4 w-4"
          />
        </div>

        <div className="pt-2">
          <Button onClick={handleSave} size="sm">
            Save Preferences
          </Button>
        </div>
      </section>
    </div>
  );
};
