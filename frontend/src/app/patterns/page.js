'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  BookOpen, Layers, Settings2, Settings, Plus, Info, Eye, Edit2, Trash2,
  FileText, Lightbulb, PenTool, MessageSquare, Files, Calculator,
  CheckSquare, Square, Sparkles, ArrowRight, LayoutGrid, Check,
  RefreshCw, AlertCircle
} from 'lucide-react';
import apiClient from '@/lib/api';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function PatternsPage() {
  const [patterns, setPatterns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [regenBusy, setRegenBusy] = useState(false);

  useEffect(() => {
    fetchPatterns();
  }, []);

  // Auto-refresh while any pattern is regenerating in the background (Celery task).
  useEffect(() => {
    const hasActive = patterns.some(p => p.status === 'generating' || p.status === 'queued');
    if (!hasActive) return;
    const interval = setInterval(() => fetchPatterns(false), 5000);
    return () => clearInterval(interval);
  }, [patterns]);

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const allSelected = patterns.length > 0 && selected.size === patterns.length;
  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(patterns.map(p => p.id)));
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} selected pattern(s)? This cannot be undone.`)) return;
    setBulkBusy(true);
    try {
      const res = await apiClient.post('/patterns/bulk-delete/', { ids });
      const data = res.data || {};
      const deletedIds = data.deleted_ids || [];
      setPatterns(prev => prev.filter(p => !deletedIds.includes(p.id)));
      setSelected(new Set());
      let msg = `Deleted ${data.deleted ?? deletedIds.length} pattern(s).`;
      if ((data.protected_skipped || []).length)
        msg += ` ${data.protected_skipped.length} shared official pattern(s) skipped — superadmin only.`;
      if ((data.not_found_or_forbidden || []).length)
        msg += ` ${data.not_found_or_forbidden.length} could not be deleted.`;
      setSuccess(msg);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to delete selected patterns');
    } finally {
      setBulkBusy(false);
    }
  };

  // Re-queue AI generation for every AI-generated pattern (or just the selected ones),
  // each using its own saved prompt. The status poller picks up the queued/generating badges.
  const handleRegenerateAll = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : null;
    const scope = ids
      ? patterns.filter(p => ids.includes(p.id))
      : patterns;
    const aiCount = scope.filter(p => p.pattern_source === 'ai_generated').length;
    if (aiCount === 0) {
      setError(ids ? 'None of the selected patterns are AI-generated — nothing to regenerate.'
                   : 'No AI-generated patterns to regenerate.');
      return;
    }
    if (!confirm(`Regenerate ${aiCount} AI pattern(s) from their saved prompts? Their current structure will be rebuilt.`)) return;
    setRegenBusy(true);
    try {
      const res = await apiClient.post('/patterns/regenerate-all/', ids ? { ids } : {});
      const data = res.data || {};
      let msg = `Queued ${data.queued ?? 0} pattern(s) for regeneration.`;
      if ((data.skipped_active || []).length) msg += ` ${data.skipped_active.length} already running.`;
      if ((data.skipped_not_ai || []).length) msg += ` ${data.skipped_not_ai.length} manual/official skipped.`;
      if ((data.skipped_no_prompt || []).length) msg += ` ${data.skipped_no_prompt.length} had no saved prompt.`;
      setSuccess(msg);
      setSelected(new Set());
      fetchPatterns(false);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to queue regeneration');
    } finally {
      setRegenBusy(false);
    }
  };

  const fetchPatterns = async (showLoading = true) => {
    try {
      if (showLoading) setLoading(true);
      const res = await apiClient.get('/patterns/?page_size=1000');
      setPatterns(res.data.results || []);
    } catch (err) {
      setError(err.message || 'Failed to load patterns');
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Are you sure you want to delete this pattern?')) return;
    try {
      await apiClient.delete(`/patterns/${id}/`);
      setSuccess('Pattern deleted successfully');
      setPatterns(prev => prev.filter(p => p.id !== id));
    } catch (err) {
      setError('Failed to delete pattern');
    }
  };

  if (loading) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full pb-12 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-indigo-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Management</span>
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Exam Patterns</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed">Define and manage question distribution structures.</p>
        </div>

        <div className="flex items-center gap-3">
          <Link href="/create-pattern" className="px-6 py-3.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-2xl font-semibold text-[13px] shadow-lg shadow-indigo-200/50 transition-all duration-300 flex items-center gap-2 hover:shadow-indigo-300/50 hover:scale-[1.02] active:scale-[0.98]">
            <Plus size={16} strokeWidth={2.5} />
            Add New Pattern
          </Link>
        </div>
      </div>

      <div className="max-w-7xl mx-auto">
        {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6" />}
        {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6" />}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

          {/* Main Content Area */}
          <div className="lg:col-span-2 space-y-8">
            <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-6 sm:p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-indigo-600 text-white rounded-xl flex items-center justify-center shadow-sm shadow-indigo-200/50">
                    <Layers size={18} strokeWidth={2} />
                  </div>
                  <div>
                    <h2 className="text-[16px] font-bold text-slate-900 tracking-tight">Available Patterns</h2>
                    <p className="text-[12px] text-slate-400">Select patterns to delete or modify.</p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {patterns.length > 0 && (
                    <button
                      onClick={toggleSelectAll}
                      className="px-4 py-2.5 bg-white border border-slate-200 text-slate-600 rounded-xl text-[11px] font-bold uppercase tracking-wider hover:bg-slate-50 hover:border-slate-300 transition-all flex items-center gap-2"
                    >
                      {allSelected ? <CheckSquare size={14} className="text-indigo-600" /> : <Square size={14} />}
                      {allSelected ? 'Clear All' : 'Select All'}
                    </button>
                  )}
                  {selected.size > 0 && (
                    <button
                      onClick={handleBulkDelete}
                      disabled={bulkBusy}
                      className="px-4 py-2.5 bg-red-50 text-red-600 border border-red-100 rounded-xl text-[11px] font-bold uppercase tracking-wider hover:bg-red-100 transition-all flex items-center gap-2 disabled:opacity-50"
                    >
                      <Trash2 size={14} />
                      {bulkBusy ? 'Deleting…' : `Delete (${selected.size})`}
                    </button>
                  )}
                  {patterns.some(p => p.pattern_source === 'ai_generated') && (
                    <button
                      onClick={handleRegenerateAll}
                      disabled={regenBusy}
                      title={selected.size > 0
                        ? 'Regenerate the selected AI patterns from their saved prompts'
                        : 'Regenerate every AI pattern from its saved prompt'}
                      className="px-4 py-2.5 bg-violet-50 text-violet-700 border border-violet-100 rounded-xl text-[11px] font-bold uppercase tracking-wider hover:bg-violet-100 transition-all flex items-center gap-2 disabled:opacity-50"
                    >
                      <RefreshCw size={14} className={regenBusy ? 'animate-spin' : ''} />
                      {regenBusy ? 'Queuing…' : selected.size > 0 ? `Regenerate (${selected.size})` : 'Regenerate All'}
                    </button>
                  )}
                </div>
              </div>

              {patterns.length === 0 ? (
                <div className="text-center py-16 bg-slate-50/50 rounded-2xl border-2 border-dashed border-slate-200">
                  <div className="w-16 h-16 bg-white rounded-2xl shadow-sm border border-slate-100 flex items-center justify-center mx-auto mb-4">
                    <BookOpen size={24} className="text-slate-300" strokeWidth={1.5} />
                  </div>
                  <h3 className="text-[16px] font-bold text-slate-900 mb-1">No patterns defined yet</h3>
                  <p className="text-[13px] text-slate-500 mb-6">Create your first exam pattern to get started!</p>
                  <Link href="/create-pattern" className="inline-flex items-center gap-2 bg-slate-900 text-white px-6 py-3 rounded-xl font-semibold text-[13px] hover:bg-slate-800 transition-all shadow-md">
                    <Plus size={16} />
                    Create First Pattern
                  </Link>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {patterns.map((pattern) => {
                    const isRegenerating = pattern.status === 'generating' || pattern.status === 'queued';
                    const isFailed = pattern.status === 'failed';
                    return (
                    <div
                      key={pattern.id}
                      className={`relative p-5 bg-white border rounded-2xl transition-all duration-200 group ${
                        selected.has(pattern.id)
                          ? 'border-indigo-400 ring-2 ring-indigo-500/10 shadow-sm'
                          : isRegenerating
                            ? 'border-indigo-200'
                            : 'border-slate-200 hover:border-slate-300 hover:shadow-sm'
                      }`}
                    >
                      <button
                        onClick={() => toggleSelect(pattern.id)}
                        title="Select for bulk delete"
                        className="absolute top-5 right-5 text-slate-300 hover:text-indigo-600 transition-colors z-10"
                      >
                        {selected.has(pattern.id)
                          ? <CheckSquare size={18} className="text-indigo-600" />
                          : <Square size={18} />}
                      </button>

                      <div className="flex items-start gap-3 mb-4 pr-8">
                        <div className="w-10 h-10 bg-indigo-50 text-indigo-600 border border-indigo-100 rounded-xl flex items-center justify-center shrink-0">
                          <FileText size={18} strokeWidth={2} />
                        </div>
                        <div className="min-w-0">
                          <h3 className="text-[15px] font-bold text-slate-900 truncate">{pattern.name}</h3>
                          <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mt-0.5 truncate">
                            Class {pattern.class_name} • {pattern.subject}
                          </p>
                        </div>
                      </div>

                      {(isRegenerating || isFailed) && (
                        <div className="mb-4">
                          {isRegenerating ? (
                            <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-indigo-50 text-indigo-600 text-[10px] font-bold uppercase tracking-wider rounded-lg border border-indigo-100 w-fit">
                              <RefreshCw size={10} className="animate-spin" />
                              {pattern.status === 'queued' ? 'Queued for regeneration' : 'Regenerating'}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-red-50 text-red-600 text-[10px] font-bold uppercase tracking-wider rounded-lg border border-red-100 w-fit">
                              <AlertCircle size={10} /> Regeneration failed
                            </span>
                          )}
                        </div>
                      )}

                      <div className="mb-4">
                        <div className="flex items-center gap-1.5 mb-2">
                          <LayoutGrid size={12} className="text-indigo-500" strokeWidth={2} />
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Pattern Structure:</span>
                        </div>
                        <div className="bg-slate-50 rounded-xl p-3 border border-slate-100 overflow-hidden relative">
                          {isRegenerating ? (
                            <p className="text-indigo-500 font-mono text-[10px] leading-relaxed">Rebuilding structure from the updated prompt…</p>
                          ) : (
                            <>
                              <pre className="text-slate-600 font-mono text-[10px] leading-relaxed max-h-[80px] overflow-y-auto custom-scrollbar">
                                <code>{JSON.stringify(pattern.sections, null, 2)}</code>
                              </pre>
                              <div className="absolute bottom-0 left-0 right-0 h-6 bg-gradient-to-t from-slate-50 to-transparent pointer-events-none"></div>
                            </>
                          )}
                        </div>
                      </div>

                      <div className="grid grid-cols-4 gap-2">
                        <Link
                          href={`/pattern/${pattern.id}`}
                          className="col-span-1 py-2 bg-slate-50 text-slate-600 border border-slate-200 rounded-xl font-bold text-[11px] uppercase tracking-wider text-center hover:bg-slate-100 hover:text-slate-900 transition-colors flex items-center justify-center gap-1.5"
                        >
                          <Eye size={14} />
                        </Link>
                        <Link
                          href={`/pattern/${pattern.id}/edit`}
                          className="col-span-1 py-2 bg-slate-50 text-slate-600 border border-slate-200 rounded-xl font-bold text-[11px] uppercase tracking-wider text-center hover:bg-slate-100 hover:text-slate-900 transition-colors flex items-center justify-center gap-1.5"
                        >
                          <Edit2 size={14} />
                        </Link>
                        {isRegenerating ? (
                          <span
                            title="Pattern is regenerating — try again once it's done"
                            className="col-span-2 py-2 bg-slate-50 text-slate-400 border border-slate-200 rounded-xl font-bold text-[11px] uppercase tracking-wider text-center flex items-center justify-center gap-1.5 cursor-not-allowed"
                          >
                            <PenTool size={14} />
                            Generate
                          </span>
                        ) : (
                          <Link
                            href={`/generator?pattern=${pattern.id}`}
                            className="col-span-2 py-2 bg-indigo-50 text-indigo-700 border border-indigo-100 rounded-xl font-bold text-[11px] uppercase tracking-wider text-center hover:bg-indigo-100 hover:text-indigo-800 transition-colors flex items-center justify-center gap-1.5"
                          >
                            <PenTool size={14} />
                            Generate
                          </Link>
                        )}
                      </div>
                    </div>
                  );})}
                </div>
              )}
            </div>

            {/* Creation Guide */}
            <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
              <div className="flex items-center gap-3 mb-8">
                <div className="w-10 h-10 rounded-xl bg-amber-50 border border-amber-100 flex items-center justify-center">
                  <Lightbulb size={20} className="text-amber-500" strokeWidth={2} />
                </div>
                <h3 className="text-xl font-bold text-slate-900">Creating Effective Patterns</h3>
              </div>

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                  { icon: PenTool, label: 'Objective', sub: 'MCQs, T/F', color: 'text-indigo-500', bg: 'bg-indigo-50', border: 'border-indigo-100' },
                  { icon: MessageSquare, label: 'Short Answer', sub: 'Brief concepts', color: 'text-emerald-500', bg: 'bg-emerald-50', border: 'border-emerald-100' },
                  { icon: Files, label: 'Long Answer', sub: 'Descriptive', color: 'text-amber-500', bg: 'bg-amber-50', border: 'border-amber-100' },
                  { icon: Calculator, label: 'Numerical', sub: 'Problems', color: 'text-purple-500', bg: 'bg-purple-50', border: 'border-purple-100' },
                ].map((item, i) => (
                  <div key={i} className={`flex flex-col p-5 rounded-2xl border ${item.border} ${item.bg} group hover:-translate-y-0.5 transition-all duration-300`}>
                    <div className={`w-10 h-10 bg-white rounded-xl flex items-center justify-center mb-3 shadow-sm`}>
                      <item.icon size={18} className={item.color} strokeWidth={2} />
                    </div>
                    <h4 className="font-bold text-slate-900 text-[14px] mb-1">{item.label}</h4>
                    <p className="text-[11px] font-semibold text-slate-500">{item.sub}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Sidebar */}
          <div className="space-y-6">

            {/* Quick Actions */}
            <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
              <div className="flex items-center gap-2.5 mb-5">
                <Settings2 size={18} className="text-indigo-500" strokeWidth={2} />
                <h3 className="text-[15px] font-bold text-slate-900">Quick Actions</h3>
              </div>
              <div className="space-y-3">
                <Link href="/create-pattern" className="w-full py-3.5 bg-slate-50 border border-slate-200 text-slate-700 hover:bg-slate-100 rounded-xl font-bold text-[12px] uppercase tracking-wider flex items-center justify-center gap-2 transition-all">
                  <Plus size={16} />
                  Add New Pattern
                </Link>
                <Link href="/patterns/all" className="w-full py-3.5 bg-white border border-slate-200 text-slate-700 hover:border-indigo-300 hover:text-indigo-700 rounded-xl font-bold text-[12px] uppercase tracking-wider flex items-center justify-center gap-2 transition-all">
                  <Settings size={16} />
                  Manage All Patterns
                </Link>
              </div>
            </div>

            {/* About Section */}
            <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
              <div className="flex items-center gap-2.5 mb-4">
                <Info size={18} className="text-indigo-500" strokeWidth={2} />
                <h3 className="text-[15px] font-bold text-slate-900">About Patterns</h3>
              </div>
              <p className="text-[13px] font-medium text-slate-500 leading-relaxed mb-5">
                Exam patterns define the structure and sections of your question papers. They help maintain consistency across different exams.
              </p>
              <div className="space-y-3">
                {[
                  'Define question types',
                  'Set marks distribution',
                  'Configure time limits',
                  'Standardize format'
                ].map((text, i) => (
                  <div key={i} className="flex items-center gap-2.5">
                    <div className="w-5 h-5 rounded-md bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                      <Check size={12} strokeWidth={3} />
                    </div>
                    <span className="text-[12px] font-bold text-slate-600">{text}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Upsell/Pro Tip Card */}
            <div className="bg-slate-900 rounded-[28px] p-6 shadow-xl relative overflow-hidden group">
              <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/30 blur-2xl rounded-full group-hover:scale-110 transition-transform duration-700" />
              <div className="absolute bottom-0 left-0 w-32 h-32 bg-purple-500/30 blur-2xl rounded-full" />

              <div className="relative z-10 text-white">
                <h3 className="text-lg font-bold mb-2">Standardize Exams</h3>
                <p className="text-slate-400 font-medium text-[13px] mb-6 leading-relaxed">
                  Use globally defined patterns to ensure your AI generates consistent difficulty across departments.
                </p>
                <Link href="/generator" className="inline-flex items-center gap-2 px-5 py-2.5 bg-white/10 hover:bg-white/20 text-white rounded-xl font-bold text-[12px] uppercase tracking-wider transition-colors">
                  Create Paper
                  <ArrowRight size={14} />
                </Link>
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}
