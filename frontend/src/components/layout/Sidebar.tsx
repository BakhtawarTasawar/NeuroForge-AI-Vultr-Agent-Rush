import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderGit2,
  Database,
  FlaskConical,
  Sparkles,
  FileText,
  BookOpen,
  User as UserIcon,
  Users,
  LogOut,
  Dna,
  X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { Badge } from '../common/Badge';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose }) => {
  const { user, logout } = useAuth();

  const navItems = [
    { name: 'Overview', to: '/', icon: LayoutDashboard },
    { name: 'Research Projects', to: '/projects', icon: FolderGit2 },
    { name: 'Datasets', to: '/datasets', icon: Database },
    { name: 'Scientific Knowledge', to: '/knowledge', icon: BookOpen },
    { name: 'Autonomous Agent', to: '/agent', icon: Sparkles },
    { name: 'Experiments', to: '/experiments', icon: FlaskConical },
    { name: 'Research Findings', to: '/findings', icon: Sparkles },
    { name: 'Reports', to: '/reports', icon: FileText },
  ];

  const secondaryNavItems = [
    { name: 'My Profile', to: '/profile', icon: UserIcon },
  ];

  if (user?.role === 'ADMIN') {
    secondaryNavItems.push({
      name: 'User Management',
      to: '/users',
      icon: Users,
    });
  }

  const roleBadgeVariant = (role?: string) => {
    switch (role) {
      case 'ADMIN':
        return 'purple';
      case 'RESEARCHER':
        return 'cyan';
      case 'VIEWER':
        return 'slate';
      default:
        return 'cyan';
    }
  };

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/80 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed top-0 bottom-0 left-0 z-40 flex flex-col w-64 border-r border-slate-800 bg-slate-950 transition-transform duration-200 ease-in-out lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Header Branding */}
        <div className="h-16 flex items-center justify-between px-5 border-b border-slate-800/80 bg-slate-900/40">
          <NavLink to="/" className="flex items-center gap-3" onClick={onClose}>
            <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Dna className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="text-base font-bold tracking-tight text-white block">
                NeuroForge AI
              </span>
              <span className="text-[10px] text-cyan-400 font-medium tracking-wide uppercase block">
                Scientific Platform
              </span>
            </div>
          </NavLink>
          <button
            onClick={onClose}
            className="lg:hidden p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation list */}
        <div className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
          <div>
            <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Scientific Exploration
            </div>
            <nav className="space-y-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    onClick={onClose}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                        isActive
                          ? 'bg-cyan-950/70 text-cyan-300 border border-cyan-800/60 shadow-sm'
                          : 'text-slate-300 hover:text-white hover:bg-slate-900'
                      }`
                    }
                  >
                    <Icon className="w-4 h-4 shrink-0 text-cyan-400" />
                    <span>{item.name}</span>
                  </NavLink>
                );
              })}
            </nav>
          </div>

          <div>
            <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Workspace &amp; System
            </div>
            <nav className="space-y-1">
              {secondaryNavItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={onClose}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                        isActive
                          ? 'bg-cyan-950/70 text-cyan-300 border border-cyan-800/60 shadow-sm'
                          : 'text-slate-300 hover:text-white hover:bg-slate-900'
                      }`
                    }
                  >
                    <Icon className="w-4 h-4 shrink-0 text-slate-400" />
                    <span>{item.name}</span>
                  </NavLink>
                );
              })}
            </nav>
          </div>
        </div>

        {/* User Card & Sign Out */}
        <div className="p-3 border-t border-slate-800/80 bg-slate-900/40">
          <div className="flex items-center justify-between p-2 rounded-xl bg-slate-900/80 border border-slate-800">
            <div className="min-w-0 pr-2">
              <p className="text-xs font-semibold text-white truncate">
                {user?.full_name || 'Researcher'}
              </p>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant={roleBadgeVariant(user?.role)} size="sm">
                  {user?.role || 'RESEARCHER'}
                </Badge>
              </div>
            </div>
            <button
              onClick={() => logout()}
              title="Sign Out"
              className="p-2 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
};

