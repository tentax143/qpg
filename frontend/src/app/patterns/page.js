'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  ChevronDown, ChevronUp, BookOpen, Layers, Clock,
  Settings2, Plus, Info, Eye, Edit2, Trash2,
  Settings, CheckCircle, HelpCircle, FileText,
  Lightbulb, PenTool, MessageSquare, Files, Calculator,
  CheckSquare, Square
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

  useEffect(() => {
    fetchPatterns();
  }, []);

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

  const fetchPatterns = async () => {
    try {
      setLoading(true);
      const res = await apiClient.get('/patterns/?page_size=1000');
      setPatterns(res.data.results || []);
    } catch (err) {
      setError(err.message || 'Failed to load patterns');
    } finally {
      setLoading(false);
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
    <div className="min-h-screen mesh-gradient flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-2">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 mb-12">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">Management</span>
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
          </div>
          <h1 className="text-4xl font-black text-gray-900 leading-tight">Exam Patterns</h1>
          <p className="text-gray-600 font-medium text-lg mt-1 tracking-tight">Define and manage question distribution structures.</p>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-8">
          <div className="glass-card overflow-hidden hover:shadow-2xl transition-shadow duration-500">
            <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-white/50">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center font-bold shadow-lg shadow-blue-100">
                  <Layers size={18} />
                </div>
                <h2 className="text-xl font-black text-gray-900">Available Patterns</h2>
              </div>
              <div className="flex items-center gap-2">
                {patterns.length > 0 && (
                  <button
                    onClick={toggleSelectAll}
                    className="px-3 py-2.5 bg-white border border-gray-200 text-gray-600 rounded-xl text-[10px] font-black uppercase tracking-[0.15em] hover:bg-gray-50 transition-all flex items-center gap-2"
                  >
                    {allSelected ? <CheckSquare size={14} className="text-blue-600" /> : <Square size={14} />}
                    {allSelected ? 'Clear' : 'Select all'}
                  </button>
                )}
                {selected.size > 0 && (
                  <button
                    onClick={handleBulkDelete}
                    disabled={bulkBusy}
                    className="px-4 py-2.5 bg-red-600 text-white rounded-xl text-[10px] font-black uppercase tracking-[0.15em] hover:bg-red-700 transition-all flex items-center gap-2 shadow-lg shadow-red-200 disabled:opacity-60"
                  >
                    <Trash2 size={14} />
                    {bulkBusy ? 'Deleting…' : `Delete (${selected.size})`}
                  </button>
                )}
                <Link href="/create-pattern" className="bg-[#1e293b] text-white px-5 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] hover:bg-slate-800 transition-all duration-300 hover:-translate-y-0.5 active:scale-95 flex items-center gap-2 shadow-xl shadow-slate-200">
                  <Plus size={14} />
                  <span>Add Pattern</span>
                </Link>
              </div>
            </div>
            
            <div className="p-8">
              {patterns.length === 0 ? (
                <div className="text-center py-20 bg-gray-50/50 rounded-[40px] border-2 border-dashed border-gray-100">
                  <div className="w-20 h-20 bg-white rounded-3xl shadow-sm flex items-center justify-center mx-auto mb-6">
                    <BookOpen size={40} className="text-gray-300" />
                  </div>
                  <h3 className="text-xl font-black text-gray-900 mb-2">No patterns defined yet</h3>
                  <p className="text-gray-600 font-medium mb-8">Create your first exam pattern to get started!</p>
                  <Link href="/create-pattern" className="inline-flex items-center gap-3 bg-blue-600 text-white px-10 py-4 rounded-2xl font-black shadow-xl shadow-blue-200 hover:bg-blue-700 transition-all duration-300 hover:-translate-y-1 active:scale-95 text-xs uppercase tracking-[0.2em]">
                    <Plus size={20} />
                    <span>Create First Pattern</span>
                  </Link>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {patterns.map((pattern, index) => (
                    <div key={pattern.id} className={`p-6 bg-white border rounded-[30px] hover:shadow-xl hover:shadow-blue-500/5 transition-all group relative ${selected.has(pattern.id) ? 'border-blue-400 ring-2 ring-blue-100' : 'border-gray-100 hover:border-blue-200'}`}>
                      <div className="absolute top-6 right-6 w-8 h-8 bg-blue-50 text-blue-600 rounded-full flex items-center justify-center text-[10px] font-black italic">
                        {index + 1}
                      </div>

                      <button
                        onClick={() => toggleSelect(pattern.id)}
                        title="Select for bulk delete"
                        className="absolute top-6 left-6 text-gray-300 hover:text-blue-600 transition-colors"
                      >
                        {selected.has(pattern.id)
                          ? <CheckSquare size={20} className="text-blue-600" />
                          : <Square size={20} />}
                      </button>

                      <div className="flex items-start gap-3 mb-6 pl-9">
                        <div className="w-10 h-10 bg-blue-50 text-blue-600 rounded-xl flex items-center justify-center shrink-0">
                          <FileText size={20} />
                        </div>
                        <div className="pr-10">
                          <h3 className="text-lg font-black text-gray-900 leading-tight mb-1">{pattern.name}</h3>
                          <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest">— Class {pattern.class_name} • {pattern.subject}</p>
                        </div>
                      </div>

                      <div className="mb-6">
                        <div className="flex items-center gap-2 mb-3">
                          <Layers size={14} className="text-blue-500" />
                          <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Pattern Structure:</span>
                        </div>
                        <div className="bg-[#0f172a] rounded-2xl p-4 overflow-hidden relative">
                          <pre className="text-blue-400 font-mono text-[10px] leading-relaxed max-h-[100px] overflow-y-auto custom-scrollbar">
                            <code>{JSON.stringify(pattern.sections, null, 2)}</code>
                          </pre>
                          <div className="absolute bottom-0 left-0 right-0 h-4 bg-gradient-to-t from-[#0f172a] to-transparent pointer-events-none"></div>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        <Link 
                          href={`/pattern/${pattern.id}`} 
                          className="flex-1 min-w-[80px] px-3 py-3 bg-[#1e293b] text-white rounded-xl font-black text-[10px] uppercase tracking-widest text-center hover:bg-slate-800 transition-all duration-300 flex items-center justify-center gap-2 hover:-translate-y-0.5"
                        >
                          <Eye size={12} />
                          View
                        </Link>
                        <Link 
                          href={`/pattern/${pattern.id}/edit`} 
                          className="flex-1 min-w-[80px] px-3 py-3 bg-blue-50 text-blue-600 rounded-xl font-black text-[10px] uppercase tracking-widest text-center hover:bg-blue-600 hover:text-white transition-all duration-300 flex items-center justify-center gap-2 border border-blue-100 hover:-translate-y-0.5"
                        >
                          <Edit2 size={12} />
                          Edit
                        </Link>
                        <Link 
                          href={`/generator?pattern=${pattern.id}`} 
                          className="flex-1 min-w-[120px] px-3 py-3 bg-emerald-600 text-white rounded-xl font-black text-[10px] uppercase tracking-widest text-center hover:bg-emerald-700 transition-all duration-300 flex items-center justify-center gap-2 shadow-lg shadow-emerald-500/10 hover:-translate-y-0.5"
                        >
                          <PenTool size={12} />
                          Generate
                        </Link>
                        <button 
                          onClick={() => handleDelete(pattern.id)}
                          className="px-3 py-3 bg-red-50 text-red-600 rounded-xl font-black text-[10px] uppercase tracking-widest hover:bg-red-600 hover:text-white transition-all duration-300 flex items-center justify-center hover:-translate-y-0.5"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Creation Guide */}
          <div className="glass-card p-8">
            <h3 className="text-xl font-black text-gray-900 mb-8 flex items-center gap-3">
              <Lightbulb className="text-amber-500" size={24} />
              Creating Effective Patterns
            </h3>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-8">
              {[
                { icon: PenTool, label: 'Objective', sub: 'MCQs, T/F, Blanks', color: 'text-blue-500', bg: 'bg-blue-50' },
                { icon: MessageSquare, label: 'Short Answer', sub: '2-3 mark brief answers', color: 'text-emerald-500', bg: 'bg-emerald-50' },
                { icon: Files, label: 'Long Answer', sub: '5-10 mark descriptive', color: 'text-amber-500', bg: 'bg-amber-50' },
                { icon: Calculator, label: 'Numerical', sub: 'Problem-solving', color: 'text-indigo-500', bg: 'bg-indigo-50' },
              ].map((item, i) => (
                <div key={i} className="flex flex-col items-center text-center group">
                  <div className={`w-16 h-16 ${item.bg} ${item.color} rounded-2xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-500`}>
                    <item.icon size={28} />
                  </div>
                  <h4 className="font-extrabold text-gray-900 text-sm mb-1">{item.label}</h4>
                  <p className="text-[10px] font-bold text-gray-500 uppercase leading-tight">{item.sub}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-8">
          {/* Quick Actions */}
          <div className="glass-card overflow-hidden hover:shadow-2xl transition-shadow duration-500">
            <div className="p-6 border-b border-gray-100 flex items-center gap-3 bg-white/50">
              <Plus size={18} className="text-blue-600" />
              <h3 className="text-lg font-black text-gray-900">Quick Actions</h3>
            </div>
            <div className="p-6 space-y-3">
              <Link href="/create-pattern" className="w-full py-4 bg-[#1e293b] text-white rounded-2xl font-black text-xs uppercase tracking-[0.2em] flex items-center justify-center gap-3 hover:bg-slate-800 transition-all duration-300 shadow-xl shadow-slate-200 hover:-translate-y-1 active:scale-95">
                <Plus size={18} />
                Add New Pattern
              </Link>
              <Link href="/patterns/all" className="w-full py-4 bg-white border border-gray-100 text-gray-700 rounded-2xl font-black text-xs uppercase tracking-[0.2em] flex items-center justify-center gap-3 hover:bg-gray-50 transition-all duration-300 hover:border-blue-200 hover:-translate-y-1 active:scale-95">
                <Settings size={18} />
                Manage All Patterns
              </Link>
            </div>
          </div>

          {/* About Section */}
          <div className="glass-card p-8">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-blue-50 text-blue-600 rounded-xl flex items-center justify-center">
                <Info size={20} />
              </div>
              <h3 className="text-lg font-black text-gray-900">About Patterns</h3>
            </div>
            <p className="text-sm font-medium text-gray-500 leading-relaxed mb-8">
              Exam patterns define the structure and sections of your question papers. They help maintain consistency across different exams.
            </p>
            <ul className="space-y-4">
              {[
                'Define question types',
                'Set marks distribution',
                'Configure time limits',
                'Standardize format'
              ].map((text, i) => (
                <li key={i} className="flex items-center gap-3 group">
                  <div className="w-1.5 h-1.5 bg-blue-500 rounded-full group-hover:scale-150 transition-transform"></div>
                  <span className="text-xs font-bold text-gray-600 uppercase tracking-wide">{text}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Upgrade Card */}
          <div className="glass-card p-8 bg-[#0f172a] text-white relative overflow-hidden group">
            <div className="absolute -right-10 -bottom-10 w-40 h-40 bg-blue-600/20 rounded-full blur-3xl group-hover:scale-150 transition-transform duration-1000"></div>
            <div className="relative z-10">
              <h3 className="text-2xl font-black mb-4">Standardize Exams</h3>
              <p className="text-slate-400 font-medium mb-8 leading-relaxed text-sm">Use globally defined patterns to ensure your AI generates consistent difficulty across departments.</p>
              <Link href="/generator" className="flex items-center gap-2 text-blue-400 font-black text-xs uppercase tracking-widest group-hover:gap-4 transition-all">
                Create Paper 
                <ArrowRight size={16} />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Dummy ArrowRight for the last card
function ArrowRight({ size, className }) {
  return (
    <svg 
      width={size} 
      height={size} 
      viewBox="0 0 24 24" 
      fill="none" 
      stroke="currentColor" 
      strokeWidth="3" 
      strokeLinecap="round" 
      strokeLinejoin="round" 
      className={className}
    >
      <path d="M5 12h14M12 5l7 7-7 7" />
    </svg>
  );
}

