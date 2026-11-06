import React from 'react';

export const LoadingSkeleton: React.FC<{ rows?: number }> = ({ rows = 4 }) => {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 bg-slate-800/60 rounded-lg w-1/3"></div>
      <div className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="h-16 bg-slate-900/60 border border-slate-800/80 rounded-xl w-full"></div>
        ))}
      </div>
    </div>
  );
};

