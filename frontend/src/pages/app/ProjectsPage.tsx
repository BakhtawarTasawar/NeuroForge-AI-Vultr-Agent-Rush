import React, { useState, useEffect } from 'react';
import {
  FolderGit2,
  Plus,
  Search,
  Calendar,
  User,
  Trash2,
  Edit2,
} from 'lucide-react';
import { apiClient, formatErrorMessage } from '../../services/api';
import { Project } from '../../types';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { Modal } from '../../components/common/Modal';
import { Badge } from '../../components/common/Badge';
import { EmptyState } from '../../components/common/EmptyState';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';

export const ProjectsPage: React.FC = () => {
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal states
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  // Form states
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [domain, setDomain] = useState('Cancer Gene-Expression');
  const [statusVal, setStatusVal] = useState<'Active' | 'Archived' | 'Draft'>('Active');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchProjects = async () => {
    try {
      setIsLoading(true);
      const res = await apiClient.get<Project[]>('/projects');
      setProjects(res.data);
      setError(null);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const openCreateModal = () => {
    setTitle('');
    setDescription('');
    setDomain('Cancer Gene-Expression');
    setFormError(null);
    setIsCreateOpen(true);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setFormError('Please enter a project title.');
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      const res = await apiClient.post<Project>('/projects', {
        title: title.trim(),
        description: description.trim() || null,
        domain,
      });
      setProjects([res.data, ...projects]);
      setIsCreateOpen(false);
    } catch (err) {
      setFormError(formatErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const openEditModal = (p: Project) => {
    setSelectedProject(p);
    setTitle(p.title);
    setDescription(p.description || '');
    setDomain(p.domain);
    setStatusVal(p.status);
    setFormError(null);
    setIsEditOpen(true);
  };

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProject || !title.trim()) return;

    setIsSubmitting(true);
    setFormError(null);
    try {
      const res = await apiClient.put<Project>(`/projects/${selectedProject.id}`, {
        title: title.trim(),
        description: description.trim() || null,
        domain,
        status: statusVal,
      });
      setProjects(projects.map((p) => (p.id === selectedProject.id ? res.data : p)));
      setIsEditOpen(false);
    } catch (err) {
      setFormError(formatErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const openDeleteModal = (p: Project) => {
    setSelectedProject(p);
    setIsDeleteOpen(true);
  };

  const handleDelete = async () => {
    if (!selectedProject) return;

    setIsSubmitting(true);
    try {
      await apiClient.delete(`/projects/${selectedProject.id}`);
      setProjects(projects.filter((p) => p.id !== selectedProject.id));
      setIsDeleteOpen(false);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const canModify = (p: Project) => {
    return user?.role === 'ADMIN' || p.owner_id === user?.id;
  };

  const canCreate = user?.role === 'ADMIN' || user?.role === 'RESEARCHER';

  const filteredProjects = projects.filter((p) => {
    const q = searchQuery.toLowerCase();
    return (
      p.title.toLowerCase().includes(q) ||
      (p.description && p.description.toLowerCase().includes(q)) ||
      p.domain.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      {/* Top action bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white">
            Research Projects
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Organize hypotheses, dataset associations, and isolated experiment parameters.
          </p>
        </div>

        {canCreate && (
          <Button onClick={openCreateModal} icon={<Plus className="w-4 h-4" />}>
            New Research Project
          </Button>
        )}
      </div>

      {/* Search Filter */}
      <div className="max-w-md">
        <Input
          placeholder="Filter projects by title, domain, or notes..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          leftIcon={<Search className="w-4 h-4" />}
        />
      </div>

      {/* Error banner if any */}
      {error && (
        <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* Projects List */}
      {isLoading ? (
        <LoadingSkeleton rows={3} />
      ) : filteredProjects.length === 0 ? (
        <EmptyState
          icon={<FolderGit2 className="w-6 h-6" />}
          title={searchQuery ? 'No matching projects found' : 'No research projects yet'}
          description={
            searchQuery
              ? 'Try modifying your search criteria to locate other research initiatives.'
              : 'Create a new project to start cataloging differential expression experiments.'
          }
          actionLabel={canCreate && !searchQuery ? 'Create New Project' : undefined}
          onAction={canCreate && !searchQuery ? openCreateModal : undefined}
          actionIcon={<Plus className="w-4 h-4" />}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredProjects.map((p) => (
            <div
              key={p.id}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-4 shadow-lg backdrop-blur-sm flex flex-col justify-between hover:border-slate-700/80 transition-all"
            >
              <div className="space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <Badge
                    variant={
                      p.status === 'Active'
                        ? 'emerald'
                        : p.status === 'Archived'
                        ? 'amber'
                        : 'slate'
                    }
                    size="sm"
                  >
                    {p.status}
                  </Badge>
                  <span className="text-[11px] font-mono text-cyan-400/80 bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-800/40">
                    {p.domain}
                  </span>
                </div>

                <h3 className="text-base font-semibold text-white tracking-tight line-clamp-1">
                  {p.title}
                </h3>

                <p className="text-xs text-slate-400 line-clamp-3 leading-relaxed">
                  {p.description || 'No detailed scientific description provided yet.'}
                </p>
              </div>

              <div className="pt-4 border-t border-slate-800/80 space-y-3">
                <div className="flex items-center justify-between text-[11px] text-slate-400">
                  <span className="flex items-center gap-1.5 truncate">
                    <User className="w-3.5 h-3.5 text-slate-400" />
                    <span className="truncate">{p.owner_name || 'Researcher'}</span>
                  </span>
                  <span className="flex items-center gap-1 shrink-0 font-mono">
                    <Calendar className="w-3 h-3 text-slate-400" />
                    {new Date(p.created_at).toLocaleDateString()}
                  </span>
                </div>

                {canModify(p) && (
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditModal(p)}
                      icon={<Edit2 className="w-3.5 h-3.5" />}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => openDeleteModal(p)}
                      icon={<Trash2 className="w-3.5 h-3.5" />}
                    >
                      Delete
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Create Research Project"
        description="Establish an isolated research project for transcriptomic experimentation."
      >
        <form onSubmit={handleCreate} className="space-y-4">
          {formError && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
              {formError}
            </div>
          )}

          <Input
            label="Project Title"
            placeholder="e.g. BRCA1 Differential Expression Screening"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Scientific Domain
            </label>
            <select
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            >
              <option value="Cancer Gene-Expression">Cancer Gene-Expression Transcriptomics</option>
              <option value="Biomarker Discovery">Biomarker Discovery &amp; Clustering</option>
              <option value="RNA-seq Differential Profiling">RNA-seq Differential Profiling</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Research Objective / Description
            </label>
            <textarea
              rows={3}
              placeholder="Outline the scientific inquiry, biological hypothesis, or target genes..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3.5 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>

          <div className="flex justify-end gap-3 pt-3">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" isLoading={isSubmitting}>
              Create Project
            </Button>
          </div>
        </form>
      </Modal>

      {/* Edit Modal */}
      <Modal
        isOpen={isEditOpen}
        onClose={() => setIsEditOpen(false)}
        title="Edit Research Project"
        description="Update project details, scientific scope, or lifecycle status."
      >
        <form onSubmit={handleEdit} className="space-y-4">
          {formError && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
              {formError}
            </div>
          )}

          <Input
            label="Project Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Status
            </label>
            <select
              value={statusVal}
              onChange={(e) => setStatusVal(e.target.value as any)}
              className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            >
              <option value="Active">Active</option>
              <option value="Draft">Draft</option>
              <option value="Archived">Archived</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Scientific Domain
            </label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Research Objective / Description
            </label>
            <textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3.5 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>

          <div className="flex justify-end gap-3 pt-3">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsEditOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" isLoading={isSubmitting}>
              Save Changes
            </Button>
          </div>
        </form>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={isDeleteOpen}
        onClose={() => setIsDeleteOpen(false)}
        title="Confirm Project Deletion"
        description="This action will permanently delete the project and disassociate its datasets."
      >
        <div className="space-y-4">
          <p className="text-xs text-slate-300 leading-relaxed">
            Are you sure you want to delete <strong className="text-white">"{selectedProject?.title}"</strong>? This action cannot be reversed.
          </p>

          <div className="flex justify-end gap-3 pt-3">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsDeleteOpen(false)}
            >
              Keep Project
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={handleDelete}
              isLoading={isSubmitting}
            >
              Delete Project
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
