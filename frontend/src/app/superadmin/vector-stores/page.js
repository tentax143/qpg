'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { Plus, Database, X, Trash2, School as SchoolIcon, ChevronDown, ChevronRight, Check, FileText, Layers, BookOpen } from 'lucide-react';

export default function VectorStoresPage() {
  const router = useRouter();
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', description: '' });
  const [creating, setCreating] = useState(false);

  const [expanded, setExpanded] = useState(null);   // store id currently open
  const [detail, setDetail] = useState(null);        // { id, schools:[], allocatable:[] }
  const [detailLoading, setDetailLoading] = useState(false);
  const [savingAlloc, setSavingAlloc] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  useEffect(() => {
    const u = JSON.parse(localStorage.getItem('user') || 'null');
    if (!u || u.role !== 'superadmin') { router.replace('/dashboard'); return; }
    load();
  }, [router]);

  async function load() {
    setLoading(true);
    try { const r = await apiClient.get('/admin/vector-stores/'); setStores(r.data || []); }
    catch (e) { setError(e.response?.data?.error || 'Failed to load'); }
    finally { setLoading(false); }
  }

  async function createStore() {
    if (!form.name.trim()) return;
    setCreating(true); setError(null);
    try {
      await apiClient.post('/admin/vector-stores/', { name: form.name.trim(), description: form.description.trim() });
      setForm({ name: '', description: '' }); setShowCreate(false);
      await load();
    } catch (e) { setError(e.response?.data?.error || 'Failed to create store'); }
    finally { setCreating(false); }
  }

  async function toggleExpand(store) {
    if (expanded === store.id) { setExpanded(null); setDetail(null); return; }
    setExpanded(store.id); setDetail(null); setDetailLoading(true);
    try { const r = await apiClient.get(`/admin/vector-stores/${store.id}/`); setDetail(r.data); }
    catch (e) { setError('Failed to load store detail'); }
    finally { setDetailLoading(false); }
  }

  async function setAllocation(storeId, schoolIds) {
    setSavingAlloc(true); setError(null);
    try {
      const r = await apiClient.patch(`/admin/vector-stores/${storeId}/`, { school_ids: schoolIds });
      setDetail(r.data);
      setStores(prev => prev.map(s => s.id === storeId ? { ...s, school_count: r.data.schools.length } : s));
    } catch (e) { setError(e.response?.data?.error || 'Failed to update allocation'); }
    finally { setSavingAlloc(false); }
  }
  const addSchool = (storeId, sid) => sid && setAllocation(storeId, [...detail.schools.map(s => s.id), Number(sid)]);
  const removeSchool = (storeId, sid) => setAllocation(storeId, detail.schools.map(s => s.id).filter(x => x !== sid));

  async function deleteStore(store) {
    setConfirmDelete(null); setError(null);
    try {
      await apiClient.delete(`/admin/vector-stores/${store.id}/`);
      if (expanded === store.id) { setExpanded(null); setDetail(null); }
      await load();
    } catch (e) { setError(e.response?.data?.error || 'Failed to delete store'); }
  }

  if (loading) return <div className="flex justify-center py-20"><div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" /></div>;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Vector Stores</h1>
          <p className="text-sm text-slate-500 mt-0.5">Named corpora of shared materials, each allocatable to specific institutions.</p>
        </div>
        <button
          onClick={() => setShowCreate(v => !v)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" /> New Store
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
          <input
            autoFocus
            type="text"
            placeholder="Store name (e.g. NCERT Hindi, TN Tamil)"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            className="w-full px-3 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <textarea
            placeholder="Description (optional)"
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            rows={2}
            className="w-full px-3 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <div className="flex justify-end gap-2">
            <button onClick={() => { setShowCreate(false); setForm({ name: '', description: '' }); }}
              className="px-4 py-2 text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors">Cancel</button>
            <button onClick={createStore} disabled={creating || !form.name.trim()}
              className="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:opacity-50">
              {creating ? 'Creating…' : 'Create Store'}
            </button>
          </div>
        </div>
      )}

      {/* List */}
      {stores.length === 0 && !showCreate ? (
        <div className="bg-white border border-slate-200 rounded-xl py-16 text-center text-sm text-slate-400">
          No vector stores yet. Create one, then choose it when uploading materials.
        </div>
      ) : (
        <div className="space-y-3">
          {stores.map(store => {
            const open = expanded === store.id;
            return (
              <div key={store.id} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="flex items-center gap-3 p-4">
                  <button onClick={() => toggleExpand(store)} className="flex items-center gap-3 flex-1 text-left">
                    <div className="w-9 h-9 bg-blue-50 rounded-lg flex items-center justify-center text-blue-600 shrink-0">
                      <Database className="w-4.5 h-4.5" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900">{store.name}</p>
                      {store.description && <p className="text-xs text-slate-400 truncate max-w-md">{store.description}</p>}
                    </div>
                  </button>
                  <div className="flex items-center gap-4 text-xs text-slate-500 shrink-0">
                    <span className="inline-flex items-center gap-1"><FileText className="w-3.5 h-3.5" />{store.material_count} material(s)</span>
                    <span className="inline-flex items-center gap-1"><SchoolIcon className="w-3.5 h-3.5" />{store.school_count} school(s)</span>
                    <button onClick={() => setConfirmDelete(store)} title="Delete store" className="p-1 text-slate-300 hover:text-red-500 transition-colors"><Trash2 className="w-4 h-4" /></button>
                    <button onClick={() => toggleExpand(store)} className="p-1 text-slate-400 hover:text-slate-600">
                      {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                {/* Allocation panel */}
                {open && (
                  <div className="border-t border-slate-100 p-4 bg-slate-50/50">
                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Allocated institutions</p>
                    {detailLoading || !detail ? (
                      <div className="w-4 h-4 border-2 border-slate-300 border-t-blue-500 rounded-full animate-spin" />
                    ) : (
                      <>
                        {detail.schools.length === 0 ? (
                          <p className="text-sm text-slate-400 mb-3">No institutions allocated yet — this store is not visible to anyone.</p>
                        ) : (
                          <div className="flex flex-wrap gap-2 mb-3">
                            {detail.schools.map(s => (
                              <span key={s.id} className="inline-flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                                {s.name}
                                <button onClick={() => removeSchool(store.id, s.id)} disabled={savingAlloc} className="text-blue-400 hover:text-red-500"><X className="w-3 h-3" /></button>
                              </span>
                            ))}
                          </div>
                        )}
                        {detail.allocatable.length > 0 && (
                          <select
                            value=""
                            disabled={savingAlloc}
                            onChange={e => addSchool(store.id, e.target.value)}
                            className="px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                          >
                            <option value="">+ Allocate an institution…</option>
                            {detail.allocatable.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                          </select>
                        )}

                        {/* Uploaded content — class → subject → units */}
                        <div className="mt-5 pt-4 border-t border-slate-200">
                          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Uploaded content</p>
                          {(!detail.content || detail.content.length === 0) ? (
                            <p className="text-sm text-slate-400">No materials uploaded into this store yet.</p>
                          ) : (
                            <div className="space-y-3">
                              {detail.content.map((cls, ci) => (
                                <div key={ci} className="rounded-lg border border-slate-200 overflow-hidden">
                                  <div className="px-3 py-2 bg-slate-50 text-xs font-bold text-slate-700 flex items-center gap-2">
                                    <Layers className="w-3.5 h-3.5 text-slate-400" /> Class {cls.class_name}
                                    <span className="ml-auto text-[11px] font-medium text-slate-400">{cls.material_count} item(s)</span>
                                  </div>
                                  <div className="divide-y divide-slate-100">
                                    {cls.subjects.map((sub, si) => (
                                      <div key={si} className="px-3 py-2">
                                        <div className="flex items-center gap-2 mb-1.5">
                                          <BookOpen className="w-3.5 h-3.5 text-blue-500" />
                                          <span className="text-sm font-medium text-slate-800">{sub.subject}</span>
                                          <span className="text-[11px] font-medium text-slate-400">· {sub.material_count} item(s)</span>
                                        </div>
                                        {sub.units.length > 0 && (
                                          <div className="flex flex-wrap gap-1.5 pl-5">
                                            {sub.units.map((u, ui) => (
                                              <span key={ui} className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded text-[11px]">{u}</span>
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6 space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center text-red-600 shrink-0"><Trash2 className="w-5 h-5" /></div>
              <div className="flex-1">
                <h2 className="text-base font-semibold text-slate-900">Delete “{confirmDelete.name}”?</h2>
                <p className="text-sm text-slate-500 mt-1">
                  The {confirmDelete.material_count} material(s) in this store keep their files and embeddings, but lose their store link — schools that only reached them through this store will no longer see them. This cannot be undone.
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmDelete(null)} className="px-4 py-2 text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg">Cancel</button>
              <button onClick={() => deleteStore(confirmDelete)} className="px-4 py-2 text-sm font-medium bg-red-600 hover:bg-red-700 text-white rounded-lg">Delete Store</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
