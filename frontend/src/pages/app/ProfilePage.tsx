import React, { useState } from 'react';
import { User, KeyRound, CheckCircle2, Lock, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { apiClient, formatErrorMessage } from '../../services/api';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { Badge } from '../../components/common/Badge';

export const ProfilePage: React.FC = () => {
  const { user, updateUser } = useAuth();

  // Profile form state
  const [fullName, setFullName] = useState(user?.full_name || '');
  const [isUpdatingProfile, setIsUpdatingProfile] = useState(false);
  const [profileSuccess, setProfileSuccess] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);

  // Password form state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPasswords, setShowPasswords] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setProfileError(null);
    setProfileSuccess(null);

    if (!fullName.trim()) {
      setProfileError('Please provide a valid full name.');
      return;
    }

    setIsUpdatingProfile(true);
    try {
      const res = await apiClient.patch('/auth/profile', { full_name: fullName.trim() });
      updateUser(res.data);
      setProfileSuccess('Profile information updated successfully.');
    } catch (err) {
      setProfileError(formatErrorMessage(err));
    } finally {
      setIsUpdatingProfile(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);

    if (!currentPassword || !newPassword) {
      setPasswordError('Please complete all password fields.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError('The new passwords do not match. Please re-enter.');
      return;
    }

    if (newPassword.length < 8 || !/[A-Za-z]/.test(newPassword) || !/\d/.test(newPassword)) {
      setPasswordError('New password must be at least 8 characters and include letters and numbers.');
      return;
    }

    setIsChangingPassword(true);
    try {
      await apiClient.post('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setPasswordSuccess('Your password was updated securely. Previous sessions have been revoked.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setPasswordError(formatErrorMessage(err));
    } finally {
      setIsChangingPassword(false);
    }
  };

  const roleVariant =
    user?.role === 'ADMIN' ? 'purple' : user?.role === 'RESEARCHER' ? 'cyan' : 'slate';

  return (
    <div className="max-w-4xl space-y-8">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-white">
          Researcher Profile
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Review your scientific platform identity and update account credentials.
        </p>
      </div>

      {/* Account Overview Card */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 shadow-lg backdrop-blur-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800/80">
          <div className="flex items-center gap-3">
            <div className="h-12 w-12 rounded-xl bg-cyan-950/80 border border-cyan-800/60 flex items-center justify-center text-cyan-400 text-lg font-bold">
              {user?.full_name?.charAt(0) || 'R'}
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">{user?.full_name}</h3>
              <p className="text-xs text-slate-400 font-mono">{user?.email}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Assigned Role:</span>
            <Badge variant={roleVariant} size="md">
              {user?.role}
            </Badge>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs text-slate-300 pt-1">
          <div>
            <span className="text-slate-400 block text-[11px]">Member Since</span>
            <span className="font-mono text-slate-200">
              {user?.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
            </span>
          </div>
          <div>
            <span className="text-slate-400 block text-[11px]">Account Status</span>
            <span className="text-emerald-400 font-medium">Active &amp; Verified</span>
          </div>
        </div>
      </div>

      {/* Edit Profile Form */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 shadow-lg space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
          <User className="w-4 h-4 text-cyan-400" />
          Update Profile Information
        </h3>

        {profileSuccess && (
          <div className="p-3 rounded-lg bg-emerald-950/40 border border-emerald-800/60 text-xs text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{profileSuccess}</span>
          </div>
        )}

        {profileError && (
          <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
            {profileError}
          </div>
        )}

        <form onSubmit={handleUpdateProfile} className="space-y-4 max-w-md">
          <Input
            label="Full Name & Academic Title"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
          />

          <Input
            label="Email Address (Fixed Institutional Identifier)"
            value={user?.email || ''}
            disabled
            helperText="To transfer institutional email ownership, contact an administrator."
          />

          <Button type="submit" isLoading={isUpdatingProfile} size="sm">
            Save Profile Details
          </Button>
        </form>
      </div>

      {/* Change Password Form */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 shadow-lg space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
          <KeyRound className="w-4 h-4 text-cyan-400" />
          Change Password
        </h3>

        {passwordSuccess && (
          <div className="p-3 rounded-lg bg-emerald-950/40 border border-emerald-800/60 text-xs text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{passwordSuccess}</span>
          </div>
        )}

        {passwordError && (
          <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
            {passwordError}
          </div>
        )}

        <form onSubmit={handleChangePassword} className="space-y-4 max-w-md">
          <Input
            label="Current Password"
            type={showPasswords ? 'text' : 'password'}
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            leftIcon={<Lock className="w-4 h-4" />}
            required
          />

          <Input
            label="New Password"
            type={showPasswords ? 'text' : 'password'}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            leftIcon={<KeyRound className="w-4 h-4" />}
            helperText="Minimum 8 characters with at least one letter and one number."
            required
          />

          <Input
            label="Confirm New Password"
            type={showPasswords ? 'text' : 'password'}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            leftIcon={<KeyRound className="w-4 h-4" />}
            required
          />

          <div className="flex items-center gap-2 text-xs text-slate-400">
            <button
              type="button"
              onClick={() => setShowPasswords(!showPasswords)}
              className="flex items-center gap-1.5 hover:text-slate-200 transition-colors"
            >
              {showPasswords ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              <span>{showPasswords ? 'Hide passwords' : 'Show passwords'}</span>
            </button>
          </div>

          <Button type="submit" isLoading={isChangingPassword} size="sm">
            Update Password
          </Button>
        </form>
      </div>
    </div>
  );
};
