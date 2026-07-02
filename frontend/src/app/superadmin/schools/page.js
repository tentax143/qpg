'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { Plus, ChevronRight, Search, School, Database, X } from 'lucide-react';

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

  if (loading) return <div className="flex justify-center py-20"><div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>;
  if (error) return <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">{error}</div>;

  const confirmMeta = {
    grant: {
      title: 'Grant Shared Content Access',
      body: (name) => `Give ${name} read access to the entire shared (superadmin) vector store — all shared textbooks and chapters. Takes effect immediately; nothing is copied. The school's own private materials are unaffected.`,
      btn: 'Grant Access',
      btnClass: 'bg-blue-600 hover:bg-blue-700 text-white',
    },
    revoke: {
      title: 'Revoke Shared Content Access',
      body: (name) => `Immediately remove ${name}'s access to the shared vector store. The school keeps its own private materials, and you can re-grant access anytime.`,
      btn: 'Revoke Access',
      btnClass: 'bg-red-600 hover:bg-red-700 text-white',
    },
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Schools</h1>
        <Link
          href="/superadmin/schools/new"
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          New School
        </Link>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input
          type="text"
          placeholder="Search schools…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full pl-9 pr-4 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>

      {actionError && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          <span className="flex-1">{actionError}</span>
          <button onClick={() => setActionError(null)}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        {filtered.length === 0 ? (
          <div className="py-16 text-center text-sm text-slate-400">
            {search ? 'No schools match your search' : 'No schools yet'}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">School</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Contact</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Members</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Papers</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider">Vector Store</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map(school => {
                const busy = actionState[school.id];
                const shared = school.access_shared_vector_store;
                return (
                  <tr key={school.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center text-blue-600">
                          <School className="w-4 h-4" />
                        </div>
                        <div>
                          <p className="font-medium text-slate-900">{school.name}</p>
                          {school.address && <p className="text-xs text-slate-400 truncate max-w-[180px]">{school.address}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {school.email || school.phone || <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-700">{school.member_count}</td>
                    <td className="px-4 py-3 text-right text-slate-700">{school.paper_count}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${school.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                        {school.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>

                    {/* Vector Store column */}
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-center gap-2">
                        {/* Status badge */}
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${shared ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-400'}`}>
                          <Database className="w-3 h-3" />
                          {shared ? 'Shared' : 'Private'}
                        </span>

                        {/* Grant when private; Revoke when shared. Scope-based — instant, no sync. */}
                        {busy ? (
                          <div className="w-4 h-4 border-2 border-slate-300 border-t-blue-500 rounded-full animate-spin" />
                        ) : shared ? (
                          <button
                            onClick={() => openConfirm(school, 'revoke')}
                            title="Revoke shared content access"
                            className="p-1 text-slate-300 hover:text-red-500 transition-colors"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        ) : (
                          <button
                            onClick={() => openConfirm(school, 'grant')}
                            title="Grant shared content access"
                            className="px-2 py-0.5 text-[11px] font-medium bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
                          >
                            Grant
                          </button>
                        )}
                      </div>
                    </td>

                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/superadmin/schools/${school.id}`}
                        className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 font-medium"
                      >
                        View <ChevronRight className="w-3.5 h-3.5" />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Confirmation Modal */}
      {confirm && (() => {
        const meta = confirmMeta[confirm.action];
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
            <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6 space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div className="flex-1">
                  <h2 className="text-base font-semibold text-slate-900">{meta.title}</h2>
                  <p className="text-sm text-slate-500 mt-1">{meta.body(confirm.school.name)}</p>
                </div>
                <button onClick={() => setConfirm(null)} className="text-slate-400 hover:text-slate-600 mt-0.5">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <button
                  onClick={() => setConfirm(null)}
                  className="px-4 py-2 text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => runAction(confirm.school, confirm.action)}
                  className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${meta.btnClass}`}
                >
                  {meta.btn}
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
