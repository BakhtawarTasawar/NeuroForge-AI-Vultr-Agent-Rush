import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import { ProtectedRoute } from './components/layout/ProtectedRoute';
import { AppShell } from './components/layout/AppShell';

// Public pages
import { LandingPage } from './pages/public/LandingPage';
import { SignInPage } from './pages/public/SignInPage';
import { RegisterPage } from './pages/public/RegisterPage';

// Authenticated pages
import { OverviewPage } from './pages/app/OverviewPage';
import { ProjectsPage } from './pages/app/ProjectsPage';
import { DatasetsPage } from './pages/app/DatasetsPage';
import { ExperimentsPage } from './pages/app/ExperimentsPage';
import { FindingsPage } from './pages/app/FindingsPage';
import { ReportsPage } from './pages/app/ReportsPage';
import { ProfilePage } from './pages/app/ProfilePage';

import { UserManagementPage } from './pages/app/UserManagementPage';
import { ResearchWorkspacePage } from './pages/app/ResearchWorkspacePage';

export default function App() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-4">
        <div className="h-10 w-10 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-xs font-mono text-cyan-400">Initializing NeuroForge AI...</p>
      </div>
    );
  }

  return (
    <Routes>
      {/* Public Routes */}
      <Route
        path="/signin"
        element={user ? <Navigate to="/" replace /> : <SignInPage />}
      />
      <Route
        path="/register"
        element={user ? <Navigate to="/" replace /> : <RegisterPage />}
      />
      <Route path="/welcome" element={<LandingPage />} />

      {/* Main Root: Landing Page if unauthenticated, Overview in Shell if authenticated */}
      {!user ? (
        <Route path="/" element={<LandingPage />} />
      ) : (
        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route index element={<OverviewPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="datasets" element={<DatasetsPage />} />
          <Route path="agent" element={<ResearchWorkspacePage />} />
          <Route path="experiments" element={<ExperimentsPage />} />
          <Route path="findings" element={<FindingsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="settings" element={<Navigate to="/profile" replace />} />
          <Route path="app/settings" element={<Navigate to="/profile" replace />} />
          <Route path="app/profile" element={<Navigate to="/profile" replace />} />

          <Route
            path="users"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <UserManagementPage />
              </ProtectedRoute>
            }
          />
        </Route>
      )}

      {/* Fallback for protected subroutes when unauthenticated */}
      <Route
        path="*"
        element={
          user ? (
            <Navigate to="/" replace />
          ) : (
            <Navigate to="/signin" replace />
          )
        }
      />
    </Routes>
  );
}
