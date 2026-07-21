'use client';

import { useState, useEffect, use } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import {
  ArrowLeft, Users, BarChart3, FileText, Settings,
  Plus, Trash2, Edit3, Check, X, ChevronDown, ShieldCheck, ShieldOff,
  Database, Link2, Sparkles, Building2
} from 'lucide-react';

const TABS = [
  { id: 'overview', label: 'Overview', icon: Settings },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'data', label: 'Data & Access', icon: Database },
  { id: 'usage', label: 'Usage', icon: BarChart3 },
  { id: 'papers', label: 'Papers', icon: FileText },
];

const STATUS_COLORS = {
  done: 'bg-emerald-50 text-emerald-700 border border-emerald-200/50',
  generating: 'bg-indigo-50 text-indigo-700 border border-indigo-200/50',
  queued: 'bg-slate-100 text-slate-600 border border-slate-200/50',
  failed: 'bg-red-50 text-red-700 border border-red-200/50',
  cancelled: 'bg-slate-100 text-slate-500 border border-slate-200/50',
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
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [subjects, setSubjects] = useState([]);
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!school) return;
    if (tab === 'users') fetchUsers();
    else if (tab === 'usage') fetchUsage();
    else if (tab === 'papers') fetchPapers();
    else if (tab === 'data') { fetchVectorLinks(); fetchVectorStores(); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, school]);

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

  async function fetchPapers() {
    setTabLoading(true);
    try { const r = await apiClient.get(`/admin/schools/${id}/papers/`); setPapers(r.data); }
    catch (e) { console.error(e); }
    finally { setTabLoading(false); }
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

  if (loading) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin"></div>
    </div>
  );
  if (error) return (
    <div className="bg-red-50 border border-red-200 rounded-2xl p-6 text-red-700 text-sm font-semibold max-w-2xl mx-auto mt-10 text-center">
      {error}
    </div>
  );

  return (
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="max-w-5xl mx-auto mb-10">
        <Link href="/superadmin/schools" className="inline-flex items-center gap-2 px-4 py-2 bg-white/80 border border-slate-200/60 rounded-full text-[12px] font-bold text-slate-500 hover:text-indigo-600 hover:border-indigo-200 transition-all shadow-sm mb-6 group">
          <ArrowLeft size={14} className="group-hover:-translate-x-1 transition-transform" />
          Back to Directory
        </Link>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 bg-white border border-slate-200/60 shadow-lg rounded-2xl flex items-center justify-center text-indigo-600 text-[24px] font-extrabold">
              {school.name.charAt(0)}
            </div>
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-[28px] font-extrabold text-slate-900 tracking-tight leading-tight">{school.name}</h1>
                <span className={`px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${school.is_active ? 'bg-emerald-50 text-emerald-700 border border-emerald-100/50' : 'bg-slate-100 text-slate-500 border border-slate-200/50'}`}>
                  {school.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <p className="text-[13px] font-medium text-slate-500">
                {school.member_count} member{school.member_count !== 1 ? 's' : ''} · {school.paper_count} paper{school.paper_count !== 1 ? 's' : ''}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto">
        {/* Tabs */}
        <div className="flex gap-2 border-b border-slate-200 mb-8 overflow-x-auto no-scrollbar pb-1">
          {TABS.map(t => {
            const Icon = t.icon;
            const isActive = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 px-5 py-3 text-[13px] font-bold rounded-xl transition-all whitespace-nowrap ${
                  isActive
                    ? 'bg-indigo-50 text-indigo-700 shadow-sm'
                    : 'text-slate-500 hover:text-slate-900 hover:bg-slate-50'
                }`}
              >
                <Icon size={16} />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Tab content */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[32px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          {tab === 'overview' && (
            <div className="space-y-8">
              <div className="flex items-center justify-between pb-4 border-b border-slate-100">
                <div>
                  <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">School Details</h2>
                  <p className="text-[12px] font-medium text-slate-500 mt-1">Manage core tenant information.</p>
                </div>
                <div className="flex gap-3">
                  {editing ? (
                    <>
                      <button onClick={() => setEditing(false)} className="px-5 py-2.5 text-[12px] font-bold border border-slate-200 text-slate-600 rounded-xl hover:bg-slate-50 transition-colors shadow-sm">
                        Cancel
                      </button>
                      <button onClick={handleSaveEdit} className="px-5 py-2.5 text-[12px] font-bold bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-colors shadow-sm flex items-center gap-1.5">
                        <Check size={14} /> Save Changes
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => setEditing(true)} className="px-5 py-2.5 text-[12px] font-bold border border-slate-200 text-slate-600 rounded-xl hover:bg-slate-50 transition-colors shadow-sm flex items-center gap-1.5">
                        <Edit3 size={14} /> Edit Details
                      </button>
                      <button onClick={handleDeleteSchool} className="px-5 py-2.5 text-[12px] font-bold border border-red-200 text-red-600 rounded-xl hover:bg-red-50 transition-colors shadow-sm flex items-center gap-1.5">
                        <Trash2 size={14} /> Delete Tenant
                      </button>
                    </>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div className="space-y-6">
                  {[
                    { label: 'School Name', field: 'name', type: 'text' },
                    { label: 'Address', field: 'address', type: 'textarea' },
                    { label: 'Phone', field: 'phone', type: 'text' },
                    { label: 'Email', field: 'email', type: 'email' },
                  ].map(({ label, field, type }) => (
                    <div key={field}>
                      <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2">{label}</label>
                      {editing ? (
                        type === 'textarea' ? (
                          <textarea
                            value={editForm[field]}
                            onChange={e => setEditForm(prev => ({ ...prev, [field]: e.target.value }))}
                            rows={3}
                            className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none shadow-sm"
                          />
                        ) : (
                          <input
                            type={type}
                            value={editForm[field]}
                            onChange={e => setEditForm(prev => ({ ...prev, [field]: e.target.value }))}
                            className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                          />
                        )
                      ) : (
                        <div className="px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-[14px] font-bold text-slate-900 min-h-[46px] flex items-center">
                          {school[field] || <span className="text-slate-400 font-medium italic">Not provided</span>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className="space-y-6">
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2">Token Budget</label>
                    {editing ? (
                      <div>
                        <input
                          type="number"
                          value={editForm.monthly_token_budget}
                          onChange={e => setEditForm(prev => ({ ...prev, monthly_token_budget: e.target.value }))}
                          className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                        />
                        <p className="mt-1.5 text-[11px] font-medium text-slate-400">Set 0 for unlimited API consumption.</p>
                      </div>
                    ) : (
                      <div className="px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-[14px] font-bold text-slate-900">
                        {school.monthly_token_budget > 0 ? school.monthly_token_budget.toLocaleString() + ' tokens / mo' : 'Unlimited Budget'}
                      </div>
                    )}
                  </div>
                  
                  {editing && (
                    <label className={`flex flex-col p-4 rounded-xl border-2 cursor-pointer transition-all ${editForm.is_active ? 'bg-emerald-50/50 border-emerald-500 shadow-sm' : 'bg-slate-50 border-slate-200'}`}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[13px] font-extrabold text-slate-900">Tenant Active</span>
                        <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${editForm.is_active ? 'bg-emerald-500 border-emerald-500' : 'bg-white border-slate-300'}`}>
                          {editForm.is_active && <Check size={12} className="text-white" />}
                        </div>
                      </div>
                      <p className="text-[11px] font-medium text-slate-500">Allow users to log in.</p>
                      <input
                        type="checkbox"
                        checked={editForm.is_active}
                        onChange={e => setEditForm(prev => ({ ...prev, is_active: e.target.checked }))}
                        className="hidden"
                      />
                    </label>
                  )}
                </div>
              </div>
            </div>
          )}

          {tab === 'data' && (
            <div className="space-y-8">
              {/* Shared store toggle */}
              <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm flex items-center justify-between">
                <div>
                  <h3 className="text-[16px] font-bold text-slate-900 flex items-center gap-2">
                    <Database size={18} className="text-indigo-600" />
                    Global Shared Store
                  </h3>
                  <p className="text-[12px] font-medium text-slate-500 mt-1 max-w-xl">
                    Allows this school to query all shared textbooks and official materials uploaded by the superadmin. Changes take effect instantly.
                  </p>
                </div>
                <button
                  onClick={() => handleToggleShared(!school.access_shared_vector_store)}
                  disabled={sharedBusy}
                  className={`px-6 py-3 text-[12px] font-bold rounded-xl transition-all shadow-sm flex items-center gap-2 disabled:opacity-60 ${school.access_shared_vector_store ? 'bg-white border border-red-200 text-red-600 hover:bg-red-50' : 'bg-indigo-600 text-white hover:bg-indigo-700'}`}
                >
                  {sharedBusy ? <Loader2 size={16} className="animate-spin" /> : school.access_shared_vector_store ? 'Revoke Access' : 'Grant Access'}
                </button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                {/* Custom Vector Stores */}
                <div className="bg-slate-50 border border-slate-100 rounded-2xl p-6">
                  <div className="mb-6">
                    <h3 className="text-[15px] font-bold text-slate-900">Assigned Vector Stores</h3>
                    <p className="text-[11px] font-medium text-slate-500 mt-1">Additional corpora explicitly assigned to this school.</p>
                  </div>
                  {!storeData ? (
                    <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-indigo-500" /></div>
                  ) : (
                    <div className="space-y-4">
                      {storeData.allocated.length === 0 ? (
                        <p className="text-[12px] font-medium text-slate-400 italic py-2">No custom stores assigned.</p>
                      ) : (
                        <div className="space-y-2">
                          {storeData.allocated.map(s => (
                            <div key={s.id} className="flex items-center justify-between bg-white border border-slate-200 rounded-xl p-3 shadow-sm">
                              <div>
                                <p className="text-[13px] font-bold text-slate-900">{s.name}</p>
                                <p className="text-[10px] font-bold text-slate-400 tracking-wider uppercase">{s.material_count} materials</p>
                              </div>
                              <button onClick={() => handleRemoveStore(s.id)} className="w-8 h-8 flex items-center justify-center text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                                <X size={16} />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {storeData.allocatable.length > 0 && (
                        <div className="flex flex-col gap-3 pt-4 border-t border-slate-200">
                          <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Assign new store</label>
                          <select
                            value={addStore}
                            onChange={e => setAddStore(e.target.value)}
                            className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[12px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                          >
                            <option value="">Select a vector store…</option>
                            {storeData.allocatable.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                          </select>
                          <button
                            onClick={handleAllocateStore}
                            disabled={!addStore || storeBusy}
                            className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-[12px] font-bold rounded-xl transition-colors flex items-center justify-center gap-2 shadow-sm"
                          >
                            <Plus size={14} /> Assign Store
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Cross-school access */}
                <div className="bg-slate-50 border border-slate-100 rounded-2xl p-6">
                  <div className="mb-6">
                    <h3 className="text-[15px] font-bold text-slate-900">Cross-School Links</h3>
                    <p className="text-[11px] font-medium text-slate-500 mt-1">Allow this school to read another school's private materials.</p>
                  </div>
                  {tabLoading || !vectorData ? (
                    <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-indigo-500" /></div>
                  ) : (
                    <div className="space-y-4">
                      {vectorData.links.length === 0 ? (
                        <p className="text-[12px] font-medium text-slate-400 italic py-2">No cross-school links.</p>
                      ) : (
                        <div className="space-y-2">
                          {vectorData.links.map(l => (
                            <div key={l.source_id} className="flex items-center justify-between bg-white border border-slate-200 rounded-xl p-3 shadow-sm">
                              <div>
                                <div className="flex items-center gap-2">
                                  <Link2 size={12} className="text-slate-400" />
                                  <p className="text-[13px] font-bold text-slate-900">{l.source_name}</p>
                                </div>
                                <p className="text-[10px] font-bold text-indigo-500 tracking-wider uppercase mt-0.5">
                                  {l.mutual ? 'Mutual Link' : 'One-way Read Access'}
                                </p>
                              </div>
                              <button onClick={() => handleRemoveLink(l.source_id, l.mutual)} className="w-8 h-8 flex items-center justify-center text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                                <X size={16} />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}

                      <div className="flex flex-col gap-3 pt-4 border-t border-slate-200">
                        <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Create new link</label>
                        <select
                          value={addSource}
                          onChange={e => setAddSource(e.target.value)}
                          className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[12px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                        >
                          <option value="">Select a school to link…</option>
                          {vectorData.linkable
                            .filter(s => !vectorData.links.some(l => l.source_id === s.id))
                            .map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                        </select>
                        <div className="flex items-center justify-between">
                          <label className="flex items-center gap-2 text-[12px] font-bold text-slate-700 cursor-pointer">
                            <input type="checkbox" checked={addMutual} onChange={e => setAddMutual(e.target.checked)} className="w-4 h-4 text-indigo-600 border-slate-300 rounded" />
                            Mutual (Two-way access)
                          </label>
                          <button
                            onClick={handleAddLink}
                            disabled={!addSource || linkBusy}
                            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-[12px] font-bold rounded-lg transition-colors shadow-sm"
                          >
                            Add Link
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {tab === 'users' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">User Management</h2>
                  <p className="text-[12px] font-medium text-slate-500 mt-1">{users.length} registered members</p>
                </div>
                <button
                  onClick={() => setShowAddUser(!showAddUser)}
                  className="px-5 py-2.5 bg-indigo-600 text-white text-[12px] font-bold rounded-xl hover:bg-indigo-700 transition-all shadow-sm flex items-center gap-2 active:scale-[0.98]"
                >
                  {showAddUser ? <X size={14} /> : <Plus size={14} />}
                  {showAddUser ? 'Cancel' : 'Add User'}
                </button>
              </div>

              {showAddUser && (
                <div className="bg-slate-50 border border-slate-200 rounded-2xl p-6 shadow-sm">
                  <h3 className="text-[15px] font-bold text-slate-900 mb-6">Create New User</h3>
                  {addUserError && <div className="mb-4 text-[12px] font-bold text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">{addUserError}</div>}
                  <form onSubmit={handleAddUser} className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2 ml-1">Username *</label>
                      <input
                        type="text"
                        value={newUser.username}
                        onChange={e => setNewUser(p => ({ ...p, username: e.target.value }))}
                        className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                        required
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2 ml-1">Email</label>
                      <input
                        type="email"
                        value={newUser.email}
                        onChange={e => setNewUser(p => ({ ...p, email: e.target.value }))}
                        className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2 ml-1">Password *</label>
                      <input
                        type="password"
                        value={newUser.password}
                        onChange={e => setNewUser(p => ({ ...p, password: e.target.value }))}
                        className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                        required
                        minLength={8}
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2 ml-1">Role</label>
                      <select
                        value={newUser.role}
                        onChange={e => setNewUser(p => ({ ...p, role: e.target.value }))}
                        className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                      >
                        <option value="teacher">Teacher</option>
                        <option value="school_admin">School Admin</option>
                      </select>
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2 ml-1">Subject Restriction</label>
                      <select
                        value={newUser.allowed_subject}
                        onChange={e => setNewUser(p => ({ ...p, allowed_subject: e.target.value }))}
                        className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[13px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                      >
                        <option value="">All Subjects (no restriction)</option>
                        {subjects.map(s => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </div>
                    <div className="md:col-span-2 pt-2">
                      <button
                        type="submit"
                        disabled={addUserLoading}
                        className="px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-[13px] font-bold rounded-xl transition-all shadow-sm active:scale-[0.98] flex items-center justify-center gap-2"
                      >
                        {addUserLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Create User'}
                      </button>
                    </div>
                  </form>
                </div>
              )}

              <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
                {tabLoading ? (
                  <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-indigo-600" /></div>
                ) : users.length === 0 ? (
                  <div className="py-16 text-center">
                    <Users size={32} className="mx-auto text-slate-300 mb-3" />
                    <p className="text-[14px] font-bold text-slate-900">No users in this school yet.</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-slate-50/80 text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                        <tr>
                          <th className="px-6 py-4">User</th>
                          <th className="px-6 py-4">Role</th>
                          <th className="px-6 py-4 text-right">Joined</th>
                          <th className="px-6 py-4 w-20 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-50">
                        {users.map(u => (
                          <tr key={u.id} className="hover:bg-slate-50/80 transition-colors">
                            <td className="px-6 py-4">
                              <p className="font-bold text-slate-900">{u.username}</p>
                              {u.email && <p className="text-[11px] font-medium text-slate-500 mt-0.5">{u.email}</p>}
                            </td>
                            <td className="px-6 py-4">
                              <span className={`inline-flex px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${
                                u.role === 'school_admin' ? 'bg-indigo-50 text-indigo-700 border border-indigo-100' : 'bg-slate-100 text-slate-600 border border-slate-200'
                              }`}>
                                {u.role === 'school_admin' ? 'School Admin' : 'Teacher'}
                              </span>
                            </td>
                            <td className="px-6 py-4 text-right text-[12px] font-semibold text-slate-500">
                              {new Date(u.date_joined).toLocaleDateString()}
                            </td>
                            <td className="px-6 py-4 text-right">
                              <div className="inline-flex items-center justify-end gap-3">
                                {u.role === 'teacher' ? (
                                  <button onClick={() => handleChangeRole(u.id, u.username, 'school_admin')} className="text-slate-400 hover:text-indigo-600 transition-colors" title="Promote to School Admin">
                                    <ShieldCheck size={16} />
                                  </button>
                                ) : u.role === 'school_admin' ? (
                                  <button onClick={() => handleChangeRole(u.id, u.username, 'teacher')} className="text-slate-400 hover:text-amber-500 transition-colors" title="Demote to Teacher">
                                    <ShieldOff size={16} />
                                  </button>
                                ) : null}
                                <button onClick={() => handleRemoveUser(u.id, u.username)} className="text-slate-400 hover:text-red-500 transition-colors" title="Remove user">
                                  <Trash2 size={16} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === 'usage' && (
            <div className="space-y-8">
              <div className="mb-2">
                <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">API Usage Metrics</h2>
              </div>
              {tabLoading ? (
                <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-indigo-600" /></div>
              ) : usage ? (
                <>
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                    {[
                      { label: 'Total Papers', value: usage.total_papers },
                      { label: 'Completed', value: usage.done_papers },
                      { label: 'Total Tokens', value: usage.total_tokens > 0 ? usage.total_tokens.toLocaleString() : '—' },
                      { label: 'Total Cost', value: `₹${Number(usage.total_cost).toFixed(4)}` },
                    ].map(({ label, value }) => (
                      <div key={label} className="bg-slate-50 border border-slate-100 rounded-2xl p-6">
                        <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2">{label}</p>
                        <p className="text-[28px] font-extrabold text-slate-900 tracking-tight">{value}</p>
                      </div>
                    ))}
                  </div>

                  <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm max-w-2xl">
                    <h3 className="text-[15px] font-bold text-slate-900 mb-6">Current Month Consumption</h3>
                    <div className="space-y-6">
                      <div className="flex justify-between text-[14px]">
                        <span className="font-bold text-slate-500">Tokens used</span>
                        <span className="font-extrabold text-slate-900">{usage.monthly_tokens.toLocaleString()}</span>
                      </div>
                      {usage.monthly_token_budget > 0 && (
                        <div>
                          <div className="w-full bg-slate-100 rounded-full h-3 mb-3 overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all duration-1000 ${
                                (usage.budget_used_pct || 0) > 90 ? 'bg-red-500' :
                                (usage.budget_used_pct || 0) > 70 ? 'bg-amber-500' : 'bg-indigo-500'
                              }`}
                              style={{ width: `${Math.min(usage.budget_used_pct || 0, 100)}%` }}
                            />
                          </div>
                          <div className="flex justify-between text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                            <span>{usage.budget_used_pct || 0}% of budget used</span>
                            <span>Limit: {usage.monthly_token_budget.toLocaleString()}</span>
                          </div>
                        </div>
                      )}
                      <div className="flex justify-between text-[14px] pt-4 border-t border-slate-100">
                        <span className="font-bold text-slate-500">Estimated Cost</span>
                        <span className="font-extrabold text-slate-900">₹{Number(usage.monthly_cost).toFixed(4)}</span>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="py-16 text-center text-[13px] font-bold text-slate-400">No usage data available</div>
              )}
            </div>
          )}

          {tab === 'papers' && (
            <div className="space-y-6">
              <div className="mb-2">
                <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Generation History</h2>
              </div>
              <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
                {tabLoading ? (
                  <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-indigo-600" /></div>
                ) : papers.length === 0 ? (
                  <div className="py-16 text-center">
                    <FileText size={32} className="mx-auto text-slate-300 mb-3" />
                    <p className="text-[14px] font-bold text-slate-900">No papers generated yet.</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-slate-50/80 text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                        <tr>
                          <th className="px-6 py-4">Paper Details</th>
                          <th className="px-6 py-4">Created By</th>
                          <th className="px-6 py-4 text-center">Status</th>
                          <th className="px-6 py-4 text-right">Cost</th>
                          <th className="px-6 py-4 text-right">Date</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-50">
                        {papers.map(p => (
                          <tr key={p.id} className="hover:bg-slate-50/80 transition-colors">
                            <td className="px-6 py-4">
                              <p className="font-bold text-slate-900">{p.subject}</p>
                              <p className="text-[11px] font-medium text-slate-500 mt-0.5">Class {p.class_name} · <span className="capitalize">{p.difficulty}</span></p>
                            </td>
                            <td className="px-6 py-4 text-[13px] font-bold text-slate-600">{p.created_by || '—'}</td>
                            <td className="px-6 py-4 text-center">
                              <span className={`inline-flex px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${STATUS_COLORS[p.status] || 'bg-slate-100 text-slate-500'}`}>
                                {p.status}
                              </span>
                            </td>
                            <td className="px-6 py-4 text-right text-[12px] font-bold text-slate-500">
                              {p.cost ? `₹${Number(p.cost).toFixed(4)}` : '—'}
                            </td>
                            <td className="px-6 py-4 text-right text-[12px] font-semibold text-slate-400">
                              {new Date(p.created_at).toLocaleDateString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
