import React, { useState, useEffect } from 'react';
import { Shield, CheckCircle2, ShieldAlert } from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import { User, UserRole } from '../../types';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../../components/common/Button';
import { Badge } from '../../components/common/Badge';
import { Modal } from '../../components/common/Modal';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

export const UserManagementPage: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Role change modal state
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [targetRole, setTargetRole] = useState<UserRole>('RESEARCHER');
  const [isRoleModalOpen, setIsRoleModalOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchUsers = async () => {
    try {
      setIsLoading(true);
      const res = await apiClient.get<User[]>('/users');
      setUsers(res.data);
      setError(null);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const openRoleModal = (u: User) => {
    setSelectedUser(u);
    setTargetRole(u.role);
    setIsRoleModalOpen(true);
  };

  const handleUpdateRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) return;

    setIsSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      const res = await apiClient.patch<User>(`/users/${selectedUser.id}/role`, {
        role: targetRole,
      });
      setUsers(users.map((u) => (u.id === selectedUser.id ? res.data : u)));
      setSuccess(`Role updated to ${targetRole} for ${selectedUser.full_name}.`);
      setIsRoleModalOpen(false);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggleStatus = async (u: User) => {
    setError(null);
    setSuccess(null);

    try {
      const res = await apiClient.patch<User>(`/users/${u.id}/status`, {
        is_active: !u.is_active,
      });
      setUsers(users.map((item) => (item.id === u.id ? res.data : item)));
      setSuccess(
        `Account status for ${u.full_name} set to ${res.data.is_active ? 'Active' : 'Deactivated'}.`
      );
    } catch (err) {
      setError(formatErrorMessage(err));
    }
  };

  const roleVariant = (role: string) => {
    switch (role) {
      case 'ADMIN':
        return 'purple';
      case 'RESEARCHER':
        return 'cyan';
      case 'VIEWER':
        return 'slate';
      default:
        return 'slate';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white">
            User Management &amp; Role-Based Access
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Administrator console for user verification, privilege assignment, and account governance.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="purple" size="md">
            Administrator Privilege Active
          </Badge>
        </div>
      </div>

      {success && (
        <div className="p-3 rounded-lg bg-emerald-950/40 border border-emerald-800/60 text-xs text-emerald-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {error && (
        <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300 flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Safety Notice */}
      <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center gap-3 text-xs text-slate-400">
        <Shield className="w-4 h-4 text-cyan-400 shrink-0" />
        <span>
          Demotion or deactivation of the last active system administrator is automatically blocked by the control plane.
        </span>
      </div>

      {/* Users Table */}
      {isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden shadow-lg">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/80 border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
                <tr>
                  <th className="py-3 px-4">Researcher</th>
                  <th className="py-3 px-4">Email</th>
                  <th className="py-3 px-4">Assigned Role</th>
                  <th className="py-3 px-4">Account Status</th>
                  <th className="py-3 px-4">Registered Date</th>
                  <th className="py-3 px-4 text-right">Administrative Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-200">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-3 px-4 font-medium text-white flex items-center gap-2">
                      <div className="h-7 w-7 rounded-lg bg-cyan-950/80 border border-cyan-800/60 flex items-center justify-center text-cyan-400 font-bold text-xs">
                        {u.full_name.charAt(0)}
                      </div>
                      <span className="truncate">{u.full_name}</span>
                      {u.id === currentUser?.id && (
                        <span className="text-[10px] text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-800/60">
                          You
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 font-mono text-slate-300">
                      {u.email}
                    </td>
                    <td className="py-3 px-4">
                      <Badge variant={roleVariant(u.role)} size="sm">
                        {u.role}
                      </Badge>
                    </td>
                    <td className="py-3 px-4">
                      <Badge variant={u.is_active ? 'emerald' : 'rose'} size="sm">
                        {u.is_active ? 'Active' : 'Deactivated'}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 font-mono text-slate-400">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <div className="inline-flex items-center gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => openRoleModal(u)}
                        >
                          Change Role
                        </Button>
                        <Button
                          variant={u.is_active ? 'danger' : 'secondary'}
                          size="sm"
                          onClick={() => handleToggleStatus(u)}
                        >
                          {u.is_active ? 'Deactivate' : 'Activate'}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Role Assignment Modal */}
      <Modal
        isOpen={isRoleModalOpen}
        onClose={() => setIsRoleModalOpen(false)}
        title="Assign Platform Role"
        description={`Update role permissions for ${selectedUser?.full_name}.`}
      >
        <form onSubmit={handleUpdateRole} className="space-y-4">
          <div className="space-y-2">
            <label className="block text-xs font-medium text-slate-300">
              Select Role
            </label>
            <div className="space-y-2">
              <label className="flex items-start gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-slate-700">
                <input
                  type="radio"
                  name="role"
                  value="RESEARCHER"
                  checked={targetRole === 'RESEARCHER'}
                  onChange={() => setTargetRole('RESEARCHER')}
                  className="mt-1 text-cyan-600 focus:ring-cyan-500"
                />
                <div>
                  <span className="font-semibold text-white text-xs block">RESEARCHER</span>
                  <span className="text-[11px] text-slate-400 block">
                    Can create research projects, upload datasets, and execute experimentation workflows.
                  </span>
                </div>
              </label>

              <label className="flex items-start gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-slate-700">
                <input
                  type="radio"
                  name="role"
                  value="VIEWER"
                  checked={targetRole === 'VIEWER'}
                  onChange={() => setTargetRole('VIEWER')}
                  className="mt-1 text-cyan-600 focus:ring-cyan-500"
                />
                <div>
                  <span className="font-semibold text-white text-xs block">VIEWER</span>
                  <span className="text-[11px] text-slate-400 block">
                    Read-only access to projects and verified findings. Cannot upload data or create projects.
                  </span>
                </div>
              </label>

              <label className="flex items-start gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-slate-700">
                <input
                  type="radio"
                  name="role"
                  value="ADMIN"
                  checked={targetRole === 'ADMIN'}
                  onChange={() => setTargetRole('ADMIN')}
                  className="mt-1 text-cyan-600 focus:ring-cyan-500"
                />
                <div>
                  <span className="font-semibold text-white text-xs block">ADMIN</span>
                  <span className="text-[11px] text-slate-400 block">
                    Full platform governance, role assignment, project supervision, and user lifecycle control.
                  </span>
                </div>
              </label>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-3">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsRoleModalOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" isLoading={isSubmitting}>
              Apply Role
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
