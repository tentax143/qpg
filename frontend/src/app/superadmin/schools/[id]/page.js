'use client';

import { useState, useEffect, use } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import {
  ArrowLeft, Users, BarChart3, FileText, Settings,
  Plus, Trash2, Edit3, Check, X, ShieldCheck, ShieldOff,
  Database, Link2, Download, RefreshCw, Zap, Pencil, RotateCw,
} from 'lucide-react';

const TABS = [
  { id: 'overview', label: 'Overview', icon: Settings },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'usage', label: 'Usage', icon: BarChart3 },
  { id: 'papers', label: 'Papers', icon: FileText },
];

const STATUS_COLORS = {
  done: 'bg-emerald-50 text-emerald-700',
  generating: 'bg-blue-50 text-blue-700',
  processing: 'bg-blue-50 text-blue-700',
  queued: 'bg-slate-100 text-slate-600',
  failed: 'bg-red-50 text-red-700',
  cancelled: 'bg-slate-100 text-slate-500',
};

export default function SchoolDetailPage({ params }) {
  const { id } = use(params);
  const router = useRouter();
  const [tab, setTab] = useState('overview');
  const [school, setSchool] = useState(null);
  const [users, setUsers] = useState([]);
  const [usage, setUsage] = useState(null);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tabLoading, setTabLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [showAddUser, setShowAddUser] = useState(false);
  const [newUser, setNewUser] = useState({ username: '', email: '', password: '', role: 'teacher', allowed_subject: '' });
  const [addUserError, setAddUserError] = useState(null);
  const [addUserLoading, setAddUserLoading] = useState(false);
  const [subjects, setSubjects] = useState([]);
  const [paperSuccess, setPaperSuccess] = useState(null);
  const [paperError, setPaperError] = useState(null);
  const [rerenderingId, setRerenderingId] = useState(null);
  const [regeneratingId, setRegeneratingId] = useState(null);
  const [retryingId, setRetryingId] = useState(null);
  const [deletingPaperId, setDeletingPaperId] = useState(null);
  // Data tab — shared-store + cross-school links
  const [vectorData, setVectorData] = useState(null);
  const [addSource, setAddSource] = useState('');
  const [addMutual, setAddMutual] = useState(false);
  const [linkBusy, setLinkBusy] = useState(false);
  const [sharedBusy, setSharedBusy] = useState(false);
  // Data tab — named vector-store allocations
  const [storeData, setStoreData] = useState(null);   // {allocated:[{id,name,material_count}], allocatable:[{id,name}]}
  const [addStore, setAddStore] = useState('');
  const [storeBusy, setStoreBusy] = useState(false);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') { router.replace('/dashboard'); return; }
    fetchSchool();
    apiClient.get('/subjects/').then(r => setSubjects(r.data.subjects || [])).catch(() => {});
  }, [id]);

  useEffect(() => {
    if (!school) return;
    if (tab === 'users') fetchUsers();
    else if (tab === 'usage') fetchUsage();
    else if (tab === 'papers') fetchPapers();
    else if (tab === 'data') { fetchVectorLinks(); fetchVectorStores(); }
  }, [tab, school]);

  useEffect(() => {
    if (tab !== 'papers') return undefined;
    if (!papers.some((p) => ['generating', 'processing', 'queued'].includes(p.status))) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      fetchPapers(false);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [tab, papers]);

  async function fetchSchool() {
    try {
      const r = await apiClient.get(`/admin/schools/${id}/`);
      setSchool(r.data);
      setEditForm({
        name: r.data.name,
        address: r.data.address,
        phone: r.data.phone,
        email: r.data.email,
        monthly_token_budget: r.data.monthly_token_budget,
        is_active: r.data.is_active,
        access_shared_vector_store: r.data.access_shared_vector_store,
      });
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to load school');
    } finally {
      setLoading(false);
    }
  }

  async function fetchUsers() {
    setTabLoading(true);
    try { const r = await apiClient.get(`/admin/schools/${id}/users/`); setUsers(r.data); }
    catch (e) { console.error(e); }
    finally { setTabLoading(false); }
  }

  async function fetchUsage() {
    setTabLoading(true);
    try { const r = await apiClient.get(`/admin/schools/${id}/usage/`); setUsage(r.data); }
    catch (e) { console.error(e); }
    finally { setTabLoading(false); }
  }

  async function fetchPapers(showLoading = true) {
    if (showLoading) setTabLoading(true);
    try {
      const r = await apiClient.get(`/admin/schools/${id}/papers/`);
      setPapers(r.data);
      setPaperError(null);
    } catch (e) {
      console.error(e);
      setPaperError(e.response?.data?.error || 'Failed to load papers');
    } finally {
      if (showLoading) setTabLoading(false);
    }
  }

  const isStuck = (paper) => paper.status === 'generating' && paper.updated_at
    && (Date.now() - new Date(paper.updated_at).getTime() > 15 * 60 * 1000);

  async function handleDeletePaper(paperId) {
    if (!window.confirm('Delete this paper?')) return;
    setDeletingPaperId(paperId);
    setPaperError(null);
    try {
      await apiClient.delete(`/papers/${paperId}/`);
      setPaperSuccess('Paper deleted');
      await fetchPapers(false);
    } catch (e) {
      setPaperError(e.response?.data?.error || 'Failed to delete paper');
    } finally {
      setDeletingPaperId(null);
    }
  }

  async function handleRetryPaper(paperId) {
    setRetryingId(paperId);
    setPaperError(null);
    try {
      const res = await apiClient.post(`/papers/${paperId}/retry/`);
      setPaperSuccess(res?.data?.queued
        ? 'Queued — this paper will start when the current generation finishes'
        : 'Generation restarted');
      await fetchPapers(false);
    } catch (e) {
      setPaperError(e.response?.data?.error || 'Failed to retry paper generation');
    } finally {
      setRetryingId(null);
    }
  }

  async function handleRerenderPaper(paperId) {
    setRerenderingId(paperId);
    setPaperError(null);
    try {
      await apiClient.post(`/papers/${paperId}/rerender/`);
      setPaperSuccess('Paper re-rendered successfully');
      await fetchPapers(false);
    } catch (e) {
      setPaperError(e.response?.data?.error || 'Re-render failed');
    } finally {
      setRerenderingId(null);
    }
  }

  async function handleRegeneratePaper(paperId) {
    if (!window.confirm('Regenerate this paper from its pattern? This creates fresh questions and replaces the current content.')) {
      return;
    }
    setRegeneratingId(paperId);
    setPaperError(null);
    try {
      const res = await apiClient.post(`/papers/${paperId}/regenerate/`);
      setPaperSuccess(res?.data?.queued
        ? 'Queued — regeneration will start when the current generation finishes'
        : 'Regenerating — refresh in a minute to see the new paper');
      await fetchPapers(false);
    } catch (e) {
      setPaperError(e.response?.data?.error || 'Could not start regeneration');
    } finally {
      setRegeneratingId(null);
    }
  }

  async function fetchVectorLinks() {
    setTabLoading(true);
    try { const r = await apiClient.get(`/admin/schools/${id}/vector-links/`); setVectorData(r.data); }
    catch (e) { console.error(e); }
    finally { setTabLoading(false); }
  }

  async function fetchVectorStores() {
    try { const r = await apiClient.get(`/admin/schools/${id}/vector-stores/`); setStoreData(r.data); }
    catch (e) { console.error(e); }
  }

  async function handleAllocateStore() {
    if (!addStore) return;
    setStoreBusy(true);
    try {
      await apiClient.post(`/admin/schools/${id}/vector-stores/`, { store_id: addStore });
      setAddStore('');
      await fetchVectorStores();
    } catch (e) { alert(e.response?.data?.error || 'Failed to allocate store'); }
    finally { setStoreBusy(false); }
  }

  async function handleRemoveStore(storeId) {
    if (!window.confirm('Remove this vector store from the school? Its materials will no longer be visible to them.')) return;
    try {
      await apiClient.delete(`/admin/schools/${id}/vector-stores/${storeId}/`);
      await fetchVectorStores();
    } catch (e) { alert(e.response?.data?.error || 'Failed to remove store'); }
  }

  async function handleToggleShared(enabled) {
    setSharedBusy(true);
    try {
      const r = await apiClient.patch(`/admin/schools/${id}/`, { access_shared_vector_store: enabled });
      setSchool(r.data);
      setEditForm(prev => ({ ...prev, access_shared_vector_store: enabled }));
    } catch (e) { alert(e.response?.data?.error || 'Failed to update access'); }
    finally { setSharedBusy(false); }
  }

  async function handleAddLink() {
    if (!addSource) return;
    setLinkBusy(true);
    try {
      await apiClient.post(`/admin/schools/${id}/vector-links/`, { source_id: addSource, mutual: addMutual });
      setAddSource(''); setAddMutual(false);
      await fetchVectorLinks();
    } catch (e) { alert(e.response?.data?.error || 'Failed to add link'); }
    finally { setLinkBusy(false); }
  }

  async function handleRemoveLink(sourceId, mutual) {
    if (!window.confirm('Remove this cross-school access link?')) return;
    try {
      await apiClient.delete(`/admin/schools/${id}/vector-links/${sourceId}/${mutual ? '?mutual=1' : ''}`);
      await fetchVectorLinks();
    } catch (e) { alert(e.response?.data?.error || 'Failed to remove link'); }
  }

  async function handleSaveEdit() {
    try {
      const r = await apiClient.patch(`/admin/schools/${id}/`, {
        ...editForm,
        monthly_token_budget: parseInt(editForm.monthly_token_budget) || 0,
      });
      setSchool(r.data);
      setEditing(false);
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to update');
    }
  }

  async function handleDeleteSchool() {
    if (!window.confirm(`Delete "${school.name}"? This cannot be undone.`)) return;
    try {
      await apiClient.delete(`/admin/schools/${id}/`);
      router.push('/superadmin/schools');
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to delete school');
    }
  }

  async function handleAddUser(e) {
    e.preventDefault();
    setAddUserError(null);
    if (!newUser.username || !newUser.password) { setAddUserError('Username and password are required'); return; }
    setAddUserLoading(true);
    try {
      const r = await apiClient.post(`/admin/schools/${id}/users/`, {
        ...newUser,
        allowed_subject: newUser.allowed_subject || null,
      });
      setUsers(prev => [...prev, r.data]);
      setNewUser({ username: '', email: '', password: '', role: 'teacher', allowed_subject: '' });
      setShowAddUser(false);
    } catch (e) {
      const errs = e.response?.data;
      setAddUserError(typeof errs === 'object' ? Object.values(errs).flat().join(' ') : 'Failed to create user');
    } finally {
      setAddUserLoading(false);
    }
  }

  async function handleRemoveUser(userId, username) {
    if (!window.confirm(`Remove user "${username}"? This will delete their account.`)) return;
    try {
      await apiClient.delete(`/admin/schools/${id}/users/${userId}/`);
      setUsers(prev => prev.filter(u => u.id !== userId));
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to remove user');
    }
  }

  async function handleChangeRole(userId, username, newRole) {
    const label = newRole === 'school_admin' ? 'promote to School Admin' : 'demote to Teacher';
    if (!window.confirm(`${label.charAt(0).toUpperCase() + label.slice(1)} "${username}"?`)) return;
    try {
      const res = await apiClient.patch(`/admin/schools/${id}/users/${userId}/`, { role: newRole });
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, role: res.data.role } : u));
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to update role');
    }
  }

  if (loading) return <div className="flex justify-center py-20"><div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>;
  if (error) return <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">{error}</div>;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/superadmin/schools" className="text-slate-400 hover:text-slate-600 transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-slate-900">{school.name}</h1>
          <p className="text-sm text-slate-400">
            {school.member_count} member{school.member_count !== 1 ? 's' : ''} · {school.paper_count} paper{school.paper_count !== 1 ? 's' : ''}
          </p>
        </div>
        <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${school.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
          {school.is_active ? 'Active' : 'Inactive'}
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map(t => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                tab === t.id
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          );
        })}
      </div>

      {paperError && <ErrorAlert message={paperError} onClose={() => setPaperError(null)} />}
      {paperSuccess && <SuccessAlert message={paperSuccess} onClose={() => setPaperSuccess(null)} />}

      {/* Tab content */}
      {tab === 'overview' && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">School Information</h2>
            <div className="flex gap-2">
              {editing ? (
                <>
                  <button onClick={handleSaveEdit} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    <Check className="w-3.5 h-3.5" /> Save
                  </button>
                  <button onClick={() => setEditing(false)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-slate-300 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors">
                    <X className="w-3.5 h-3.5" /> Cancel
                  </button>
                </>
              ) : (
                <>
                  <button onClick={() => setEditing(true)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-slate-300 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors">
                    <Edit3 className="w-3.5 h-3.5" /> Edit
                  </button>
                  <button onClick={handleDeleteSchool} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-red-200 text-red-600 rounded-lg hover:bg-red-50 transition-colors">
                    <Trash2 className="w-3.5 h-3.5" /> Delete
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4">
            {[
              { label: 'School Name', field: 'name', type: 'text' },
              { label: 'Address', field: 'address', type: 'textarea' },
              { label: 'Phone', field: 'phone', type: 'text' },
              { label: 'Email', field: 'email', type: 'email' },
              { label: 'Monthly Token Budget', field: 'monthly_token_budget', type: 'number' },
            ].map(({ label, field, type }) => (
              <div key={field} className="flex items-start gap-4">
                <span className="text-sm text-slate-500 w-40 shrink-0 pt-1">{label}</span>
                {editing ? (
                  type === 'textarea' ? (
                    <textarea
                      value={editForm[field]}
                      onChange={e => setEditForm(prev => ({ ...prev, [field]: e.target.value }))}
                      rows={2}
                      className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                    />
                  ) : (
                    <input
                      type={type}
                      value={editForm[field]}
                      onChange={e => setEditForm(prev => ({ ...prev, [field]: e.target.value }))}
                      className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  )
                ) : (
                  <span className="text-sm text-slate-900">
                    {field === 'monthly_token_budget'
                      ? (school[field] > 0 ? school[field].toLocaleString() + ' tokens' : 'Unlimited')
                      : (school[field] || <span className="text-slate-400">—</span>)
                    }
                  </span>
                )}
              </div>
            ))}
            {editing && (
              <div className="flex items-center gap-4">
                <span className="text-sm text-slate-500 w-40 shrink-0">Status</span>
                <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editForm.is_active}
                    onChange={e => setEditForm(prev => ({ ...prev, is_active: e.target.checked }))}
                    className="w-4 h-4 text-blue-600 border-slate-300 rounded"
                  />
                  Active
                </label>
              </div>
            )}

            <div className="flex items-center gap-2 text-xs text-slate-400 pt-1">
              <Database className="w-3.5 h-3.5" />
              Vector-store access (shared store + cross-school links) is managed in the <span className="font-medium text-slate-600">Data</span> tab.
            </div>
          </div>
        </div>
      )}

      {tab === 'data' && (
        <div className="space-y-5">
          {/* Shared (super-admin) store */}
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-blue-600" />
                <h2 className="text-sm font-semibold text-slate-900">Shared (super-admin) vector store</h2>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${school.access_shared_vector_store ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                  {school.access_shared_vector_store ? 'Granted' : 'Not granted'}
                </span>
              </div>
              <button
                onClick={() => handleToggleShared(!school.access_shared_vector_store)}
                disabled={sharedBusy}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-60 ${school.access_shared_vector_store ? 'border border-red-200 text-red-600 hover:bg-red-50' : 'bg-blue-600 text-white hover:bg-blue-700'}`}
              >
                {sharedBusy ? '…' : school.access_shared_vector_store ? 'Revoke' : 'Grant'}
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              When granted, this school reads all shared textbooks &amp; chapters uploaded by the super-admin, alongside its own materials. Instant — nothing is copied.
            </p>
          </div>

          {/* Named vector stores allocated to this school */}
          <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-4">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-slate-900">Named vector stores</h2>
            </div>
            <p className="text-xs text-slate-500 -mt-2">
              Shared corpora allocated to <span className="font-medium text-slate-700">{school.name}</span> — it retrieves from every store listed here, alongside its own materials. Store contents are managed on the <span className="font-medium text-slate-600">Vector Stores</span> page.
            </p>

            {!storeData ? (
              <div className="flex justify-center py-6"><div className="w-4 h-4 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>
            ) : (
              <>
                {storeData.allocated.length === 0 ? (
                  <p className="text-sm text-slate-400 py-1">No vector stores allocated yet.</p>
                ) : (
                  <div className="space-y-2">
                    {storeData.allocated.map(s => (
                      <div key={s.id} className="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2">
                        <div className="flex items-center gap-2 text-sm">
                          <Database className="w-3.5 h-3.5 text-slate-400" />
                          <span className="font-medium text-slate-900">{s.name}</span>
                          <span className="text-[11px] text-slate-400">· {s.material_count} material(s)</span>
                        </div>
                        <button
                          onClick={() => handleRemoveStore(s.id)}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-red-500 hover:bg-red-50 hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 transition-colors"
                          title="Remove allocation"
                          aria-label={`Remove ${s.name} allocation`}
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {storeData.allocatable.length > 0 && (
                  <div className="flex items-center gap-2 pt-3 border-t border-slate-100">
                    <select
                      value={addStore}
                      onChange={e => setAddStore(e.target.value)}
                      className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                    >
                      <option value="">Select a vector store to allocate…</option>
                      {storeData.allocatable.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                    <button
                      onClick={handleAllocateStore}
                      disabled={!addStore || storeBusy}
                      className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-1.5"
                    >
                      <Plus className="w-3.5 h-3.5" /> Add
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Cross-school links */}
          <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-4">
            <div className="flex items-center gap-2">
              <Link2 className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-slate-900">Cross-school access</h2>
            </div>
            <p className="text-xs text-slate-500 -mt-2">
              Let <span className="font-medium text-slate-700">{school.name}</span> also read the private materials of other schools. Directional — tick <span className="font-medium">Mutual</span> to share both ways.
            </p>

            {tabLoading || !vectorData ? (
              <div className="flex justify-center py-6"><div className="w-4 h-4 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>
            ) : (
              <>
                {vectorData.links.length === 0 ? (
                  <p className="text-sm text-slate-400 py-1">No cross-school links yet.</p>
                ) : (
                  <div className="space-y-2">
                    {vectorData.links.map(l => (
                      <div key={l.source_id} className="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2">
                        <div className="flex items-center gap-2 text-sm">
                          <span className="text-slate-400">can read</span>
                          <span className="font-medium text-slate-900">{l.source_name}</span>
                          {l.mutual && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-700 font-medium">Mutual</span>}
                        </div>
                        <button
                          onClick={() => handleRemoveLink(l.source_id, l.mutual)}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-red-500 hover:bg-red-50 hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 transition-colors"
                          title="Remove link"
                          aria-label={`Remove access link to ${l.source_name}`}
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex items-center gap-2 pt-3 border-t border-slate-100">
                  <select
                    value={addSource}
                    onChange={e => setAddSource(e.target.value)}
                    className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  >
                    <option value="">Select a school to link…</option>
                    {vectorData.linkable
                      .filter(s => !vectorData.links.some(l => l.source_id === s.id))
                      .map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer whitespace-nowrap">
                    <input type="checkbox" checked={addMutual} onChange={e => setAddMutual(e.target.checked)} className="w-4 h-4 text-blue-600 border-slate-300 rounded" />
                    Mutual
                  </label>
                  <button
                    onClick={handleAddLink}
                    disabled={!addSource || linkBusy}
                    className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-1.5"
                  >
                    <Plus className="w-3.5 h-3.5" /> Add
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {tab === 'users' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500">{users.length} user{users.length !== 1 ? 's' : ''} in this school</p>
            <button
              onClick={() => setShowAddUser(!showAddUser)}
              className="inline-flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4" />
              Add User
            </button>
          </div>

          {showAddUser && (
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-900 mb-4">New User</h3>
              {addUserError && <div className="mb-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{addUserError}</div>}
              <form onSubmit={handleAddUser} className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Username *</label>
                  <input
                    type="text"
                    value={newUser.username}
                    onChange={e => setNewUser(p => ({ ...p, username: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Email</label>
                  <input
                    type="email"
                    value={newUser.email}
                    onChange={e => setNewUser(p => ({ ...p, email: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Password *</label>
                  <input
                    type="password"
                    value={newUser.password}
                    onChange={e => setNewUser(p => ({ ...p, password: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    required
                    minLength={8}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Role</label>
                  <select
                    value={newUser.role}
                    onChange={e => setNewUser(p => ({ ...p, role: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="teacher">Teacher</option>
                    <option value="school_admin">School Admin</option>
                  </select>
                </div>
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-slate-700 mb-1">Subject Restriction</label>
                  <select
                    value={newUser.allowed_subject}
                    onChange={e => setNewUser(p => ({ ...p, allowed_subject: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  >
                    <option value="">All Subjects (no restriction)</option>
                    {subjects.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <p className="mt-1 text-xs text-slate-400">If set, this user can only generate papers and upload materials for this subject.</p>
                </div>
                <div className="col-span-2 flex gap-2">
                  <button
                    type="submit"
                    disabled={addUserLoading}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
                  >
                    {addUserLoading ? <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : 'Create User'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowAddUser(false); setAddUserError(null); }}
                    className="px-4 py-2 border border-slate-300 text-slate-600 text-sm rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}

          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            {tabLoading ? (
              <div className="flex justify-center py-10"><div className="w-4 h-4 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>
            ) : users.length === 0 ? (
              <div className="py-12 text-center text-sm text-slate-400">No users in this school yet</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">User</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Role</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Joined</th>
                    <th className="px-4 py-3 w-12" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {users.map(u => (
                    <tr key={u.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3">
                        <div>
                          <p className="font-medium text-slate-900">{u.username}</p>
                          {u.email && <p className="text-xs text-slate-400">{u.email}</p>}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          u.role === 'school_admin' ? 'bg-violet-50 text-violet-700' : 'bg-slate-100 text-slate-600'
                        }`}>
                          {u.role === 'school_admin' ? 'School Admin' : 'Teacher'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-xs text-slate-400">
                        {new Date(u.date_joined).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex items-center gap-1 whitespace-nowrap">
                          {u.role === 'teacher' ? (
                            <button
                              onClick={() => handleChangeRole(u.id, u.username, 'school_admin')}
                              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-violet-600 hover:bg-violet-50 hover:text-violet-700 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-1 transition-colors"
                              title="Promote to School Admin"
                              aria-label={`Promote ${u.username} to School Admin`}
                            >
                              <ShieldCheck className="w-4 h-4" />
                            </button>
                          ) : u.role === 'school_admin' ? (
                            <button
                              onClick={() => handleChangeRole(u.id, u.username, 'teacher')}
                              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-amber-600 hover:bg-amber-50 hover:text-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-1 transition-colors"
                              title="Demote to Teacher"
                              aria-label={`Demote ${u.username} to Teacher`}
                            >
                              <ShieldOff className="w-4 h-4" />
                            </button>
                          ) : null}
                          <button
                            onClick={() => handleRemoveUser(u.id, u.username)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-red-500 hover:bg-red-50 hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 transition-colors"
                            title="Remove user"
                            aria-label={`Remove ${u.username}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {tab === 'usage' && (
        <div className="space-y-4">
          {tabLoading ? (
            <div className="flex justify-center py-10"><div className="w-4 h-4 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>
          ) : usage ? (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                  { label: 'Total Papers', value: usage.total_papers },
                  { label: 'Total Images', value: (usage.total_images ?? 0).toLocaleString() },
                  { label: 'Total Tokens', value: usage.total_tokens > 0 ? usage.total_tokens.toLocaleString() : '—' },
                  { label: 'Total Cost', value: `₹${Number(usage.total_cost).toFixed(4)}` },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-white border border-slate-200 rounded-xl p-4">
                    <p className="text-xs text-slate-500 mb-1">{label}</p>
                    <p className="text-xl font-semibold text-slate-900">{value}</p>
                  </div>
                ))}
              </div>

              <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-slate-900 mb-4">This Month</h3>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-500">Tokens used</span>
                    <span className="font-medium text-slate-900">{usage.monthly_tokens.toLocaleString()}</span>
                  </div>
                  {usage.monthly_token_budget > 0 && (
                    <>
                      <div className="w-full bg-slate-100 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full transition-all ${
                            (usage.budget_used_pct || 0) > 90 ? 'bg-red-500' :
                            (usage.budget_used_pct || 0) > 70 ? 'bg-amber-500' : 'bg-blue-500'
                          }`}
                          style={{ width: `${Math.min(usage.budget_used_pct || 0, 100)}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-xs text-slate-400">
                        <span>{usage.budget_used_pct || 0}% of budget used</span>
                        <span>Budget: {usage.monthly_token_budget.toLocaleString()} tokens</span>
                      </div>
                    </>
                  )}
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-500">Cost this month</span>
                    <span className="font-medium text-slate-900">₹{Number(usage.monthly_cost).toFixed(4)}</span>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="text-sm text-slate-400">No usage data available</div>
          )}
        </div>
      )}

      {tab === 'papers' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">School Papers</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {papers.length} recent paper{papers.length !== 1 ? 's' : ''} generated by {school.name}
              </p>
            </div>
            <button
              onClick={() => fetchPapers(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-slate-300 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
          </div>
          {tabLoading ? (
            <div className="flex justify-center py-10"><div className="w-4 h-4 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>
          ) : papers.length === 0 ? (
            <div className="py-12 text-center text-sm text-slate-400">No papers generated yet</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Paper</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">By</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Cost</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Date</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {papers.map(p => (
                  <tr key={p.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <p className="font-medium text-slate-900">{p.subject}</p>
                      <p className="text-xs text-slate-400">Class {p.class_name} · {p.difficulty}</p>
                    </td>
                    <td className="px-4 py-3 text-slate-500">{p.created_by || '—'}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_COLORS[p.status] || 'bg-slate-100 text-slate-500'}`}>
                        {p.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-slate-500">
                      {p.cost ? `₹${Number(p.cost).toFixed(4)}` : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-slate-400">
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-1">
                        {p.status === 'done' && (
                          <Link
                            href={`/papers/${p.id}/edit`}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-blue-600 hover:bg-blue-50 hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 transition-colors"
                            title="Edit / AI edit"
                            aria-label={`Edit ${p.subject} paper`}
                          >
                            <Pencil className="w-4 h-4" />
                          </Link>
                        )}
                        {p.file && (
                          <a
                            href={p.file}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-blue-600 hover:bg-blue-50 hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 transition-colors"
                            title="Download"
                            aria-label={`Download ${p.subject} paper`}
                          >
                            <Download className="w-4 h-4" />
                          </a>
                        )}
                        {p.status === 'done' && p.has_paper_data && (
                          <button
                            onClick={() => handleRerenderPaper(p.id)}
                            disabled={rerenderingId === p.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-violet-600 hover:bg-violet-50 hover:text-violet-700 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-1 transition-colors disabled:opacity-40"
                            title="Re-render DOCX"
                            aria-label={`Re-render ${p.subject} paper`}
                          >
                            {rerenderingId === p.id
                              ? <RefreshCw className="w-4 h-4 animate-spin" />
                              : <Zap className="w-4 h-4" />
                            }
                          </button>
                        )}
                        {p.status === 'done' && (
                          <button
                            onClick={() => handleRegeneratePaper(p.id)}
                            disabled={regeneratingId === p.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-amber-600 hover:bg-amber-50 hover:text-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-1 transition-colors disabled:opacity-40"
                            title="Regenerate fresh questions"
                            aria-label={`Regenerate ${p.subject} paper`}
                          >
                            <RotateCw className={`w-4 h-4 ${regeneratingId === p.id ? 'animate-spin' : ''}`} />
                          </button>
                        )}
                        {(p.status === 'failed' || isStuck(p)) && (
                          <button
                            onClick={() => handleRetryPaper(p.id)}
                            disabled={retryingId === p.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-emerald-600 hover:bg-emerald-50 hover:text-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1 transition-colors disabled:opacity-40"
                            title="Retry generation"
                            aria-label={`Retry ${p.subject} paper generation`}
                          >
                            <RefreshCw className={`w-4 h-4 ${retryingId === p.id ? 'animate-spin' : ''}`} />
                          </button>
                        )}
                        <button
                          onClick={() => handleDeletePaper(p.id)}
                          disabled={deletingPaperId === p.id}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-red-500 hover:bg-red-50 hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 transition-colors disabled:opacity-40"
                          title="Delete"
                          aria-label={`Delete ${p.subject} paper`}
                        >
                          {deletingPaperId === p.id
                            ? <RefreshCw className="w-4 h-4 animate-spin" />
                            : <Trash2 className="w-4 h-4" />
                          }
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
