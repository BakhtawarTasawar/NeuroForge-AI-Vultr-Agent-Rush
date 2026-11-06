import React, { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

export const AppShell: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  const getPageTitle = (pathname: string): string => {
    switch (pathname) {
      case '/':
        return 'Research Overview';
      case '/projects':
        return 'Research Projects';
      case '/datasets':
        return 'Dataset Library';
      case '/agent':
        return 'Autonomous Scientific Agent';
      case '/experiments':
        return 'Experiment Workspace';
      case '/findings':
        return 'Verified Findings';
      case '/reports':
        return 'Research Reports';
      case '/profile':
        return 'My Profile';
      case '/settings':
        return 'Account Settings';
      case '/users':
        return 'User Management';
      default:
        return 'Research Workspace';
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main Content Area offset by sidebar on large screens */}
      <div className="flex-1 flex flex-col lg:pl-64">
        <Topbar
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
          title={getPageTitle(location.pathname)}
        />
        <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

