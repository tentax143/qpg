'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { Plus, Database, X, Trash2, School as SchoolIcon, ChevronDown, ChevronRight, Check, FileText, Layers, BookOpen, Sparkles, Loader2 } from 'lucide-react';

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

  if (loading) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
    </div>
  );

  return (
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-amber-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Global Master Data</span>
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Vector Stores</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">
            Named corpora of shared materials, allocatable to specific institutions.
          </p>
        </div>
        
        <button
          onClick={() => setShowCreate(v => !v)}
          className="px-6 py-3.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-indigo-200/50 transition-all flex items-center gap-2 active:scale-[0.98] shrink-0"
        >
          {showCreate ? <X size={16} strokeWidth={2.5} /> : <Plus size={16} strokeWidth={2.5} />}
          {showCreate ? 'Cancel' : 'New Store'}
        </button>
      </div>

      <div className="max-w-7xl mx-auto space-y-8">
        {error && (
          <div className="flex items-center justify-between bg-red-50 border border-red-100 rounded-2xl p-5 text-[13px] font-bold text-red-600 shadow-sm">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="w-8 h-8 flex items-center justify-center text-red-400 hover:bg-red-100 hover:text-red-600 rounded-full transition-colors"><X size={16} /></button>
          </div>
        )}

        {/* Create form */}
        {showCreate && (
          <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[32px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)] animate-in fade-in zoom-in duration-300">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-12 h-12 bg-indigo-50 border border-indigo-100 rounded-2xl flex items-center justify-center text-indigo-600">
                <Database size={24} />
              </div>
              <div>
                <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Create New Vector Store</h2>
                <p className="text-[13px] font-medium text-slate-500 mt-0.5">Define a new isolated corpora for retrieval.</p>
              </div>
            </div>
            
            <div className="space-y-5">
              <div>
                <label className="block text-[12px] font-bold text-slate-500 uppercase tracking-wider ml-1 mb-2">Store Name *</label>
                <input
                  autoFocus
                  type="text"
                  placeholder="e.g. NCERT Hindi, TN Tamil"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow"
                />
              </div>
              <div>
                <label className="block text-[12px] font-bold text-slate-500 uppercase tracking-wider ml-1 mb-2">Description</label>
                <textarea
                  placeholder="Description (optional)"
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  rows={3}
                  className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow resize-none"
                />
              </div>
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-100">
                <button onClick={() => { setShowCreate(false); setForm({ name: '', description: '' }); }}
                  className="px-6 py-3 text-[13px] font-bold text-slate-600 bg-white border border-slate-200 hover:bg-slate-50 rounded-xl transition-colors shadow-sm">
                  Cancel
                </button>
                <button onClick={createStore} disabled={creating || !form.name.trim()}
                  className="px-6 py-3 text-[13px] font-bold bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl transition-all shadow-sm active:scale-[0.98] disabled:opacity-50 flex items-center justify-center gap-2 min-w-[140px]">
                  {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                  {creating ? 'Creating…' : 'Create Store'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* List */}
        {stores.length === 0 && !showCreate ? (
          <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[32px] py-20 text-center shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
            <Database size={32} className="mx-auto text-slate-300 mb-4" />
            <h3 className="text-[16px] font-bold text-slate-900 mb-1">No Vector Stores</h3>
            <p className="text-[13px] text-slate-500">Create one to start organizing and sharing materials.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {stores.map(store => {
              const open = expanded === store.id;
              return (
                <div key={store.id} className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)] transition-all">
                  <div className="flex flex-col md:flex-row md:items-center gap-4 p-6 hover:bg-slate-50/80 transition-colors">
                    <button onClick={() => toggleExpand(store)} className="flex items-center gap-4 flex-1 text-left">
                      <div className="w-14 h-14 bg-indigo-50 border border-indigo-100 rounded-2xl flex items-center justify-center text-indigo-600 shrink-0 shadow-sm">
                        <Database size={24} />
                      </div>
                      <div className="min-w-0">
                        <p className="text-[18px] font-extrabold text-slate-900 tracking-tight">{store.name}</p>
                        {store.description && <p className="text-[13px] font-medium text-slate-500 truncate max-w-2xl mt-0.5">{store.description}</p>}
                      </div>
                    </button>
                    <div className="flex items-center gap-6 justify-between md:justify-end ml-18 md:ml-0">
                      <div className="flex gap-4">
                        <span className="flex flex-col items-center">
                          <span className="text-[16px] font-extrabold text-slate-700">{store.material_count}</span>
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1"><FileText size={10} /> Materials</span>
                        </span>
                        <div className="w-px h-8 bg-slate-200 self-center" />
                        <span className="flex flex-col items-center">
                          <span className="text-[16px] font-extrabold text-slate-700">{store.school_count}</span>
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1"><SchoolIcon size={10} /> Schools</span>
                        </span>
                      </div>
                      <div className="flex items-center gap-2 pl-4 border-l border-slate-200">
                        <button onClick={() => setConfirmDelete(store)} title="Delete store" className="w-10 h-10 flex items-center justify-center text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-xl transition-colors">
                          <Trash2 size={18} />
                        </button>
                        <button onClick={() => toggleExpand(store)} className={`w-10 h-10 flex items-center justify-center rounded-xl transition-colors ${open ? 'bg-indigo-50 text-indigo-600' : 'bg-slate-50 text-slate-400 hover:bg-slate-100'}`}>
                          {open ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Allocation panel */}
                  {open && (
                    <div className="border-t border-slate-100 bg-slate-50/50 p-8">
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
                        {/* Left Col: Schools */}
                        <div>
                          <div className="mb-4 flex items-center gap-2">
                            <SchoolIcon size={16} className="text-indigo-600" />
                            <h3 className="text-[15px] font-bold text-slate-900">Allocated Institutions</h3>
                          </div>
                          
                          {detailLoading || !detail ? (
                            <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin text-indigo-600" /></div>
                          ) : (
                            <div className="space-y-4">
                              {detail.schools.length === 0 ? (
                                <p className="text-[12px] font-medium text-slate-400 italic py-2">No institutions allocated yet — this store is not visible to anyone.</p>
                              ) : (
                                <div className="flex flex-wrap gap-2">
                                  {detail.schools.map(s => (
                                    <span key={s.id} className="inline-flex items-center gap-2 pl-3 pr-2 py-1.5 bg-white border border-slate-200 shadow-sm text-slate-700 rounded-xl text-[12px] font-bold">
                                      {s.name}
                                      <button onClick={() => removeSchool(store.id, s.id)} disabled={savingAlloc} className="w-5 h-5 flex items-center justify-center rounded-md bg-slate-100 text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors">
                                        <X size={12} />
                                      </button>
                                    </span>
                                  ))}
                                </div>
                              )}
                              {detail.allocatable.length > 0 && (
                                <div className="pt-2">
                                  <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Assign to School</label>
                                  <select
                                    value=""
                                    disabled={savingAlloc}
                                    onChange={e => addSchool(store.id, e.target.value)}
                                    className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-[12px] font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm"
                                  >
                                    <option value="">+ Allocate an institution…</option>
                                    {detail.allocatable.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                                  </select>
                                </div>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Right Col: Content */}
                        <div>
                          <div className="mb-4 flex items-center gap-2">
                            <FileText size={16} className="text-indigo-600" />
                            <h3 className="text-[15px] font-bold text-slate-900">Uploaded Content</h3>
                          </div>
                          
                          {detailLoading || !detail ? (
                            <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin text-indigo-600" /></div>
                          ) : (
                            <div>
                              {(!detail.content || detail.content.length === 0) ? (
                                <p className="text-[12px] font-medium text-slate-400 italic py-2">No materials uploaded into this store yet.</p>
                              ) : (
                                <div className="space-y-4">
                                  {detail.content.map((cls, ci) => (
                                    <div key={ci} className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
                                      <div className="px-4 py-3 bg-slate-50/80 border-b border-slate-100 text-[13px] font-extrabold text-slate-800 flex items-center gap-2">
                                        <Layers size={14} className="text-indigo-500" /> Class {cls.class_name}
                                        <span className="ml-auto px-2 py-0.5 bg-slate-200/50 rounded-lg text-[10px] font-bold text-slate-500 tracking-wider uppercase">{cls.material_count} Items</span>
                                      </div>
                                      <div className="divide-y divide-slate-100">
                                        {cls.subjects.map((sub, si) => (
                                          <div key={si} className="p-4">
                                            <div className="flex items-center gap-2 mb-3">
                                              <BookOpen size={14} className="text-slate-400" />
                                              <span className="text-[14px] font-bold text-slate-900">{sub.subject}</span>
                                              <span className="text-[11px] font-bold text-slate-400">· {sub.material_count} items</span>
                                            </div>
                                            {sub.units.length > 0 && (
                                              <div className="flex flex-wrap gap-2 pl-6">
                                                {sub.units.map((u, ui) => (
                                                  <span key={ui} className="px-2.5 py-1 bg-slate-50 border border-slate-200 text-slate-600 rounded-lg text-[11px] font-medium shadow-sm">{u}</span>
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
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Delete confirmation */}
        {confirmDelete && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="bg-white rounded-[28px] shadow-2xl w-full max-w-md mx-4 p-8 border border-slate-100 scale-100 animate-in zoom-in-95 duration-200">
              <div className="flex items-start gap-4 mb-6">
                <div className="w-12 h-12 rounded-2xl bg-red-50 text-red-600 flex items-center justify-center shrink-0">
                  <Trash2 size={24} />
                </div>
                <div>
                  <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Delete "{confirmDelete.name}"?</h2>
                  <p className="text-[13px] font-medium text-slate-500 mt-2 leading-relaxed">
                    The <strong className="text-slate-700">{confirmDelete.material_count} material(s)</strong> in this store keep their files and embeddings, but lose their store link. Schools that only reached them through this store will no longer see them. This cannot be undone.
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-100">
                <button
                  onClick={() => setConfirmDelete(null)}
                  className="px-6 py-3 text-[13px] font-bold text-slate-600 bg-white border border-slate-200 hover:bg-slate-50 rounded-xl transition-colors shadow-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={() => deleteStore(confirmDelete)}
                  className="px-6 py-3 text-[13px] font-bold bg-red-600 hover:bg-red-700 text-white rounded-xl transition-all shadow-sm active:scale-[0.98]"
                >
                  Delete Store
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
