import React from 'react';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'cyan' | 'emerald' | 'amber' | 'rose' | 'purple' | 'slate';
  size?: 'sm' | 'md';
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'cyan',
  size = 'sm',
}) => {
  const styles = {
    cyan: 'bg-cyan-950/70 text-cyan-300 border-cyan-800/60',
    emerald: 'bg-emerald-950/70 text-emerald-300 border-emerald-800/60',
    amber: 'bg-amber-950/70 text-amber-300 border-amber-800/60',
    rose: 'bg-rose-950/70 text-rose-300 border-rose-800/60',
    purple: 'bg-purple-950/70 text-purple-300 border-purple-800/60',
    slate: 'bg-slate-800/80 text-slate-300 border-slate-700/60',
  };

  const sizes = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-xs font-medium',
  };

  return (
    <span
      className={`inline-flex items-center font-medium rounded-full border ${styles[variant]} ${sizes[size]} transition-colors`}
    >
      {children}
    </span>
  );
};

