'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { Plus, ChevronRight, Search, School, Database, X, Sparkles, Building2 } from 'lucide-react';

export default function SchoolsPage() {
  const router = useRouter();
  const [schools, setSchools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');

  // Per-school action state: { [schoolId]: 'granting' | 'revoking' | null }
  const [actionState, setActionState] = useState({});
  // Confirmation modal state
  const [confirm, setConfirm] = useState(null); // { school, action: 'grant'|'revoke' }
  const [actionError, setActionError] = useState(null);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') { router.replace('/dashboard'); return; }
    apiClient.get('/admin/schools/')
      .then(r => setSchools(r.data))
      .catch(e => setError(e.response?.data?.error || 'Failed to load'))
      .finally(() => setLoading(false));
  }, [router]);

  const filtered = schools.filter(s =>
    s.name.toLowerCase().includes(search.toLowerCase()) ||
    s.email.toLowerCase().includes(search.toLowerCase())
  );

  function setSchoolShared(id, value) {
    setSchools(prev => prev.map(s => s.id === id ? { ...s, access_shared_vector_store: value } : s));
  }

  async function runAction(school, action) {
    setConfirm(null);
    setActionError(null);
    setActionState(prev => ({ ...prev, [school.id]: action === 'grant' ? 'granting' : 'revoking' }));
    try {
      const enabled = action === 'grant';
      await apiClient.patch(`/admin/schools/${school.id}/`, { access_shared_vector_store: enabled });
      setSchoolShared(school.id, enabled);   // scope-based: instant, no copy task
    } catch (e) {
      setActionError(e.response?.data?.error || `Failed to ${action} shared access`);
    } finally {
      setActionState(prev => ({ ...prev, [school.id]: null }));
    }
  }

  function openConfirm(school, action) {
    setActionError(null);
    setConfirm({ school, action });
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

  const confirmMeta = {
    grant: {
      title: 'Grant Shared Content Access',
      body: (name) => `Give ${name} read access to the entire shared (superadmin) vector store — all shared textbooks and chapters. Takes effect immediately; nothing is copied. The school's own private materials are unaffected.`,
      btn: 'Grant Access',
      btnClass: 'bg-indigo-600 hover:bg-indigo-700 text-white',
    },
    revoke: {
      title: 'Revoke Shared Content Access',
      body: (name) => `Immediately remove ${name}'s access to the shared vector store. The school keeps its own private materials, and you can re-grant access anytime.`,
      btn: 'Revoke Access',
      btnClass: 'bg-red-600 hover:bg-red-700 text-white',
    },
  };

  return (
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col xl:flex-row xl:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-amber-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Superadmin</span>
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Schools Management</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">Manage tenant organizations, monitor usage, and configure access.</p>
        </div>
        
        <div className="flex items-center gap-3">
          <Link
            href="/superadmin/schools/new"
            className="px-6 py-3.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-indigo-200/50 transition-all flex items-center gap-2 active:scale-[0.98]"
          >
            <Plus size={16} strokeWidth={2.5} />
            Add New School
          </Link>
        </div>
      </div>

      <div className="max-w-7xl mx-auto space-y-8">
        {/* Search */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)] relative z-[50]">
          <div className="relative">
            <Search className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="text"
              placeholder="Search schools by name or email..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-12 pr-6 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow"
            />
          </div>
        </div>

        {actionError && (
          <div className="flex items-center justify-between bg-red-50 border border-red-100 rounded-2xl p-4 text-[13px] font-bold text-red-600">
            <span>{actionError}</span>
            <button onClick={() => setActionError(null)} className="w-8 h-8 flex items-center justify-center text-red-400 hover:bg-red-100 rounded-full transition-colors"><X className="w-4 h-4" /></button>
          </div>
        )}

        {/* Table */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center gap-4 bg-slate-50/50">
            <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center border border-indigo-100">
              <Building2 size={20} strokeWidth={2} />
            </div>
            <div>
              <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Registered Tenants</h2>
              <p className="text-[12px] text-slate-500 font-medium mt-0.5">Directory of all schools in the system</p>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="py-20 text-center">
              <div className="w-16 h-16 bg-slate-50 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-slate-100">
                <School size={24} className="text-slate-300" strokeWidth={1.5} />
              </div>
              <h3 className="text-[16px] font-bold text-slate-900 mb-1">
                {search ? 'No schools match your search' : 'No schools yet'}
              </h3>
              <p className="text-[13px] text-slate-500 mb-6">
                {search ? 'Try adjusting your search terms.' : 'Create the first tenant to start onboarding users.'}
              </p>
              {!search && (
                <Link href="/superadmin/schools/new" className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 text-white rounded-xl font-bold text-[13px] hover:bg-indigo-700 transition-all shadow-sm active:scale-[0.98]">
                  <Plus size={16} />
                  Create School
                </Link>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-slate-50/80 text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                  <tr>
                    <th className="px-8 py-5">School Info</th>
                    <th className="px-6 py-5">Contact</th>
                    <th className="px-6 py-5 text-center">Members</th>
                    <th className="px-6 py-5 text-center">Papers</th>
                    <th className="px-6 py-5 text-center">Status</th>
                    <th className="px-6 py-5 text-center">Vector Store</th>
                    <th className="px-8 py-5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50 bg-white/50">
                  {filtered.map(school => {
                    const busy = actionState[school.id];
                    const shared = school.access_shared_vector_store;
                    return (
                      <tr key={school.id} className="hover:bg-slate-50/80 transition-colors group">
                        <td className="px-8 py-5">
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 bg-slate-100 rounded-xl flex items-center justify-center text-[13px] font-extrabold shadow-sm group-hover:bg-indigo-50 group-hover:text-indigo-600 transition-colors">
                              {school.name.charAt(0)}
                            </div>
                            <div>
                              <p className="font-bold text-slate-900">{school.name}</p>
                              {school.address && <p className="text-[11px] font-semibold text-slate-400 truncate max-w-[220px]">{school.address}</p>}
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-5 text-[13px] font-bold text-slate-500">
                          {school.email || school.phone || <span className="text-slate-300 italic">—</span>}
                        </td>
                        <td className="px-6 py-5 text-center font-bold text-slate-700">{school.member_count}</td>
                        <td className="px-6 py-5 text-center font-bold text-slate-700">{school.paper_count}</td>
                        <td className="px-6 py-5 text-center">
                          <span className={`inline-flex px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${school.is_active ? 'bg-emerald-50 text-emerald-700 border border-emerald-100/50' : 'bg-slate-100 text-slate-500 border border-slate-200/50'}`}>
                            {school.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>

                        {/* Vector Store column */}
                        <td className="px-6 py-5">
                          <div className="flex flex-col items-center justify-center gap-2">
                            {/* Status badge */}
                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${shared ? 'bg-indigo-50 text-indigo-700 border border-indigo-100/50' : 'bg-slate-100 text-slate-400 border border-slate-200/50'}`}>
                              <Database className="w-3 h-3" />
                              {shared ? 'Shared' : 'Private'}
                            </span>

                            {/* Grant when private; Revoke when shared. */}
                            {busy ? (
                              <div className="w-4 h-4 border-2 border-slate-300 border-t-indigo-600 rounded-full animate-spin mt-1" />
                            ) : shared ? (
                              <button
                                onClick={() => openConfirm(school, 'revoke')}
                                title="Revoke shared content access"
                                className="inline-flex items-center gap-1 text-[10px] font-bold text-red-500 hover:text-red-700 transition-colors mt-1"
                              >
                                <X className="w-3 h-3" /> Revoke
                              </button>
                            ) : (
                              <button
                                onClick={() => openConfirm(school, 'grant')}
                                title="Grant shared content access"
                                className="px-3 py-1 text-[10px] font-bold bg-white border border-indigo-200 hover:bg-indigo-50 text-indigo-600 rounded-lg transition-colors mt-1 shadow-sm"
                              >
                                Grant Access
                              </button>
                            )}
                          </div>
                        </td>

                        <td className="px-8 py-5 text-right">
                          <Link
                            href={`/superadmin/schools/${school.id}`}
                            className="inline-flex items-center gap-1 text-[12px] text-indigo-600 hover:text-indigo-800 font-bold transition-all group-hover/link:translate-x-1"
                          >
                            View Details <ChevronRight className="w-4 h-4" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Confirmation Modal */}
        {confirm && (() => {
          const meta = confirmMeta[confirm.action];
          return (
            <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200">
              <div className="bg-white rounded-[28px] shadow-2xl w-full max-w-md mx-4 p-8 border border-slate-100 scale-100 animate-in zoom-in-95 duration-200">
                <div className="flex items-start gap-4 mb-6">
                  <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 ${confirm.action === 'grant' ? 'bg-indigo-50 text-indigo-600' : 'bg-red-50 text-red-600'}`}>
                    <Database size={24} />
                  </div>
                  <div>
                    <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">{meta.title}</h2>
                    <p className="text-[13px] font-medium text-slate-500 mt-2 leading-relaxed">{meta.body(confirm.school.name)}</p>
                  </div>
                </div>
                <div className="flex justify-end gap-3 pt-4 border-t border-slate-100">
                  <button
                    onClick={() => setConfirm(null)}
                    className="px-6 py-3 text-[13px] font-bold text-slate-600 bg-white border border-slate-200 hover:bg-slate-50 rounded-xl transition-colors shadow-sm"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => runAction(confirm.school, confirm.action)}
                    className={`px-6 py-3 text-[13px] font-bold rounded-xl transition-all shadow-sm active:scale-[0.98] ${meta.btnClass}`}
                  >
                    {meta.btn}
                  </button>
                </div>
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
