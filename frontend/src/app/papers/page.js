'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Download, Trash2, RefreshCw, Zap,
  Search, Filter, FileText, Calendar, Layers,
  ChevronRight, ExternalLink, Clock, CheckCircle, 
  AlertCircle, Edit, MoreVertical, FileDown, 
  RotateCcw, RotateCw, Ban, CreditCard, ArrowRight
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function PapersPage() {
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [filters, setFilters] = useState({ class_name: '', subject: '' });
  const [selectedPapers, setSelectedPapers] = useState([]);
  const [rerenderingId, setRerenderingId] = useState(null);
  const [regeneratingId, setRegeneratingId] = useState(null);

  useEffect(() => {
    fetchPapers();
    
    // Auto-refresh if papers are generating
    const interval = setInterval(() => {
      if (papers.some(p => p.status === 'generating' || p.status === 'processing')) {
        fetchPapers(false);
      }
    }, 5000);
    
    return () => clearInterval(interval);
  }, [filters]);

  const fetchPapers = async (showLoading = true) => {
    try {
      if (showLoading) setLoading(true);
      const params = new URLSearchParams();
      params.append('page_size', '1000');
      if (filters.class_name) params.append('class_name', filters.class_name);
      if (filters.subject) params.append('subject', filters.subject);
      const res = await apiClient.get(`/papers/?${params.toString()}`);
      setPapers(res.data.results || []);
    } catch (err) {
      setError('Failed to load question papers');
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Are you sure you want to delete this question paper?')) return;
    try {
      await apiClient.delete(`/papers/${id}/`);
      setSuccess('Question paper deleted');
      fetchPapers(false);
    } catch (err) {
      setError('Failed to delete paper');
    }
  };

  const handleRetry = async (id) => {
    try {
      await apiClient.post(`/papers/${id}/retry/`);
      setSuccess('Generation restarted');
      fetchPapers(false);
    } catch (err) {
      setError('Failed to retry generation');
    }
  };

  const handleRerender = async (id) => {
    setRerenderingId(id);
    try {
      await apiClient.post(`/papers/${id}/rerender/`);
      setSuccess('Paper re-rendered successfully');
      fetchPapers(false);
    } catch (err) {
      setError(err?.response?.data?.error || 'Re-render failed');
    } finally {
      setRerenderingId(null);
    }
  };

  // Regenerate fresh questions using the paper's existing config (pattern/class/subject/chapters).
  const handleRegenerate = async (id) => {
    if (!confirm('Regenerate this paper from its pattern? This creates fresh questions and replaces the current content.')) return;
    setRegeneratingId(id);
    try {
      await apiClient.post(`/papers/${id}/regenerate/`);
      setSuccess('Regenerating — refresh in a minute to see the new paper');
      fetchPapers(false);
    } catch (err) {
      setError(err?.response?.data?.error || 'Could not start regeneration');
    } finally {
      setRegeneratingId(null);
    }
  };

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-2">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-end justify-between gap-8 mb-12">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">Output Library</span>
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
          </div>
          <h1 className="text-4xl font-black text-gray-900 leading-tight">Question Papers</h1>
          <p className="text-gray-500 font-medium text-lg mt-1 tracking-tight">Your repository of Al-generated academic assessments.</p>
        </div>
        
        <div className="flex flex-wrap items-center gap-3">
          <Link href="/generator" className="flex items-center gap-2 bg-blue-600 text-white px-6 py-4 rounded-2xl font-black text-xs uppercase tracking-wider shadow-xl shadow-blue-200 hover:bg-blue-700 transition-all hover:-translate-y-1 active:translate-y-0">
            Generate New Paper
          </Link>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      {/* Filter Bar */}
      <div className="glass-card p-6 mb-8 border-l-4 border-l-blue-600">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="relative group">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-[#1e293b] transition-colors" size={18} />
            <input
              type="text"
              placeholder="Search by class..."
              value={filters.class_name}
              onChange={(e) => setFilters(prev => ({ ...prev, class_name: e.target.value }))}
              className="w-full pl-11 pr-4 py-3 bg-gray-50 border border-transparent rounded-xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all text-sm font-bold"
            />
          </div>
          <div className="relative group">
            <Filter className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-[#1e293b] transition-colors" size={18} />
            <input
              type="text"
              placeholder="Search by subject..."
              value={filters.subject}
              onChange={(e) => setFilters(prev => ({ ...prev, subject: e.target.value }))}
              className="w-full pl-11 pr-4 py-3 bg-gray-50 border border-transparent rounded-xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all text-sm font-bold"
            />
          </div>
          <button 
            onClick={() => fetchPapers(true)}
            className="flex items-center justify-center gap-2 bg-white border border-gray-100 text-gray-700 hover:text-blue-600 px-6 py-3 rounded-xl font-bold text-sm shadow-sm hover:shadow-md transition-all active:scale-95 group"
          >
            <RefreshCw size={18} className="group-hover:rotate-180 transition-transform duration-700" />
            Sync Repository
          </button>
        </div>
      </div>

      {/* Paper List Table */}
      <div className="glass-card overflow-hidden">
        {papers.length === 0 ? (
          <div className="text-center py-32">
            <div className="w-24 h-24 bg-gray-50 rounded-[40px] flex items-center justify-center mx-auto mb-6 border border-gray-100">
              <FileText size={48} className="text-gray-200" />
            </div>
            <h2 className="text-2xl font-black text-gray-900 mb-2">No Papers Found</h2>
            <p className="text-gray-400 font-medium mb-8 max-w-xs mx-auto">Your generated question papers will appear here once you start generating them.</p>
            <Link href="/generator" className="inline-flex items-center gap-2 bg-blue-600 text-white px-8 py-4 rounded-2xl font-black text-xs uppercase tracking-wider transition-all hover:bg-blue-700">
              Go to Generator <ArrowRight size={18} />
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-gray-50/50 text-[10px] font-black uppercase text-gray-400 tracking-widest border-b border-gray-100">
                <tr>
                  <th className="px-8 py-6 w-12">
                    <input type="checkbox" className="rounded-md border-gray-200 text-[#1e293b] focus:ring-[#1e293b]" />
                  </th>
                  <th className="px-4 py-6">Identity</th>
                  <th className="px-4 py-6">Academic Metadata</th>
                  <th className="px-4 py-6">Status Info</th>
                  {/* <th className="px-4 py-6 text-center">Cost</th> */}
                  <th className="px-8 py-6 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {papers.map((paper) => (
                  <tr key={paper.id} className="hover:bg-blue-50/10 transition-all group">
                    <td className="px-8 py-6">
                      <input type="checkbox" className="rounded-md border-gray-200 text-[#1e293b] focus:ring-[#1e293b]" />
                    </td>
                    <td className="px-4 py-6">
                      <div className="flex items-center gap-4">
                        <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 shadow-sm ${
                          paper.status === 'done' ? 'bg-emerald-50 text-emerald-600' : 
                          paper.status === 'failed' ? 'bg-red-50 text-red-600' : 
                          'bg-blue-50 text-blue-600'
                        }`}>
                          {paper.status === 'done' ? <CheckCircle size={22} /> : 
                           paper.status === 'failed' ? <AlertCircle size={22} /> : 
                           <Clock size={22} className={paper.status === 'generating' ? 'animate-spin' : ''} />}
                        </div>
                        <div>
                          <p className="font-black text-gray-900 leading-tight mb-1 group-hover:text-blue-600 transition-colors uppercase tracking-tight">{paper.subject}</p>
                          <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest">
                            Class {paper.class_name} • {new Date(paper.created_at).toLocaleDateString()}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-6">
                      <div className="flex flex-col gap-1.5">
                        <div className="flex items-center gap-2">
                          <Layers size={12} className="text-gray-400" />
                          <span className="text-[11px] font-bold text-gray-500 uppercase">{paper.pattern_name}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Calendar size={12} className="text-gray-400" />
                          <span className="text-[11px] font-bold text-gray-500 uppercase">Academic 24-25</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-6">
                      {paper.status === 'done' ? (
                        <span className="px-3 py-1 bg-emerald-50 text-emerald-600 text-[9px] font-black uppercase rounded-lg border border-emerald-100 flex items-center gap-1.5 w-fit">
                          <CheckCircle size={10} /> Completed
                        </span>
                      ) : paper.status === 'generating' || paper.status === 'processing' ? (
                        <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[9px] font-black uppercase rounded-lg border border-blue-100 flex items-center gap-1.5 w-fit">
                          <RefreshCw size={10} className="animate-spin" /> {paper.status}
                        </span>
                      ) : (
                        <span className="px-3 py-1 bg-red-50 text-red-600 text-[9px] font-black uppercase rounded-lg border border-red-100 flex items-center gap-1.5 w-fit">
                          <AlertCircle size={10} /> {paper.status}
                        </span>
                      )}
                    </td>
                    <td className="px-8 py-6 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {paper.pdf_url && (
                          <>
                            <Link 
                                href={`/papers/${paper.id}/edit`}
                                className="p-2.5 bg-white border border-gray-100 text-gray-400 hover:text-blue-600 hover:border-blue-100 rounded-xl shadow-sm transition-all"
                                title="Edit Content"
                            >
                                <Edit size={18} />
                            </Link>
                            <a 
                                href={paper.pdf_url} 
                                className="p-2.5 bg-blue-600 text-white rounded-xl shadow-lg shadow-blue-200 hover:scale-110 active:scale-95 transition-all"
                                title="Download PDF"
                            >
                                <FileDown size={18} />
                            </a>
                          </>
                        )}
                        {paper.status === 'done' && paper.has_paper_data && (
                          <button
                            onClick={() => handleRerender(paper.id)}
                            disabled={rerenderingId === paper.id}
                            className="p-2.5 bg-violet-600 text-white rounded-xl shadow-lg shadow-violet-200 hover:scale-110 active:scale-95 transition-all disabled:opacity-60 disabled:cursor-not-allowed disabled:scale-100"
                            title="Re-render DOCX"
                          >
                            {rerenderingId === paper.id
                              ? <RefreshCw size={18} className="animate-spin" />
                              : <Zap size={18} />
                            }
                          </button>
                        )}
                        {paper.status === 'done' && (
                          <button
                            onClick={() => handleRegenerate(paper.id)}
                            disabled={regeneratingId === paper.id}
                            className="p-2.5 bg-amber-500 text-white rounded-xl shadow-lg shadow-amber-200 hover:scale-110 active:scale-95 transition-all disabled:opacity-60 disabled:cursor-not-allowed disabled:scale-100"
                            title="Regenerate fresh questions (same pattern, class, subject & chapters)"
                          >
                            <RotateCw size={18} className={regeneratingId === paper.id ? 'animate-spin' : ''} />
                          </button>
                        )}
                        {paper.status === 'failed' && (
                          <button
                            onClick={() => handleRetry(paper.id)}
                            className="p-2.5 bg-amber-500 text-white rounded-xl shadow-lg shadow-amber-200 hover:scale-110 active:scale-95 transition-all"
                            title="Retry Generation"
                          >
                            <RotateCcw size={18} />
                          </button>
                        )}
                        <button 
                          onClick={() => handleDelete(paper.id)}
                          className="p-2.5 bg-white border border-gray-100 text-gray-400 hover:text-red-500 hover:border-red-100 rounded-xl shadow-sm transition-all"
                          title="Delete"
                        >
                          <Trash2 size={18} />
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
  );
}
