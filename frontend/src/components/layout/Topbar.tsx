import React, { useState, useEffect } from 'react';
import { Menu } from 'lucide-react';
import { fetchHealth } from '../../services/api';
import { useAuth } from '../../context/AuthContext';

interface TopbarProps {
  onToggleSidebar: () => void;
  title: string;
}

export const Topbar: React.FC<TopbarProps> = ({ onToggleSidebar, title }) => {
  const { user } = useAuth();
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const [latency, setLatency] = useState<number | null>(null);

  const checkHealth = async () => {
    const start = performance.now();
    try {
      await fetchHealth();
      setLatency(Math.round(performance.now() - start));
      setIsHealthy(true);
    } catch {
      setLatency(Math.round(performance.now() - start));
      setIsHealthy(false);
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="h-16 border-b border-slate-800/80 bg-slate-900/40 backdrop-blur-md sticky top-0 z-30 px-4 sm:px-6 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="lg:hidden p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
          aria-label="Toggle navigation menu"
        >
          <Menu className="w-5 h-5" />
        </button>
        <div>
          <h1 className="text-base sm:text-lg font-semibold tracking-tight text-white">
            {title}
          </h1>
        </div>
      </div>

      <div className="flex items-center gap-3 sm:gap-4">
        {/* Real Backend Status Indicator */}
        <div
          title={`Backend status: ${
            isHealthy ? 'Operational' : isHealthy === false ? 'Unreachable' : 'Checking'
          }`}
          className="flex items-center gap-2 px-2.5 py-1 rounded-full border border-slate-800 bg-slate-900 text-xs"
        >
          <span className="relative flex h-2 w-2">
            {isHealthy && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            )}
            <span
              className={`relative inline-flex rounded-full h-2 w-2 ${
                isHealthy
                  ? 'bg-emerald-400'
                  : isHealthy === false
                  ? 'bg-rose-400'
                  : 'bg-amber-400'
              }`}
            ></span>
          </span>
          <span className="hidden sm:inline text-[11px] text-slate-300">
            {isHealthy ? 'Control Plane Active' : 'Control Plane Offline'}
          </span>
          {latency !== null && (
            <span className="hidden md:inline font-mono text-[10px] text-slate-400">
              {latency}ms
            </span>
          )}
        </div>

        {/* User quick pill */}
        <div className="hidden sm:flex items-center gap-2 pl-2 border-l border-slate-800">
          <div className="text-right">
            <span className="block text-xs font-medium text-slate-200">
              {user?.full_name}
            </span>
            <span className="block text-[10px] text-slate-400 font-mono">
              {user?.email}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
