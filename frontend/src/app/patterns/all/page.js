'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  ChevronDown, ChevronUp, BookOpen, Layers, Clock, 
  Settings2, Plus, Info, Eye, Edit2, Trash2, 
  Settings, CheckCircle, HelpCircle, FileText,
  Lightbulb, PenTool, MessageSquare, Files, Calculator,
  Filter, Search, ArrowLeft, MoreHorizontal, Calendar, 
  User, Hash, Target
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function PatternsListPage() {
  const [patterns, setPatterns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    fetchPatterns();
  }, []);

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

  const filteredPatterns = patterns.filter(p => 
    p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    p.subject.toLowerCase().includes(searchTerm.toLowerCase()) ||
    p.class_name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) return (
    <div className="min-h-screen mesh-gradient flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-2 mb-20">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 mb-12">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Link href="/patterns" className="text-[10px] font-black text-blue-600 uppercase tracking-widest hover:underline">Patterns</Link>
            <span className="text-gray-300">/</span>
            <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">All Records</span>
          </div>
          <h1 className="text-4xl font-black text-gray-900 leading-tight tracking-tight">Pattern Repository</h1>
          <p className="text-gray-500 font-medium text-lg mt-1 tracking-tight">Complete database of all exam structural definitions.</p>
        </div>
        <Link href="/create-pattern" className="flex items-center gap-3 bg-[#1e293b] text-white px-8 py-4 rounded-2xl font-black shadow-2xl shadow-slate-200 hover:bg-black transition-all active:scale-95 group">
          <Plus size={22} className="group-hover:rotate-90 transition-transform duration-300" />
          <span>New Pattern</span>
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      {/* Control Bar */}
      <div className="glass-card mb-10 p-4 flex flex-col md:flex-row items-center gap-4 bg-white/50 backdrop-blur-xl">
        <div className="relative flex-1 group w-full">
            <div className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-600 transition-colors">
                <Search size={20} />
            </div>
            <input 
                type="text" 
                placeholder="Search by name, subject, or class..."
                className="w-full pl-12 pr-4 py-3.5 bg-white border border-gray-100 rounded-xl text-gray-900 focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
            />
        </div>
        <div className="flex items-center gap-3 w-full md:w-auto">
            <button className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-3.5 bg-white border border-gray-100 rounded-xl font-bold text-gray-600 hover:bg-gray-50 transition-all">
                <Filter size={18} />
                <span>Filter</span>
            </button>
            <div className="h-10 w-[1px] bg-gray-100 hidden md:block mx-1"></div>
            <p className="text-xs font-black text-gray-400 uppercase tracking-widest px-2">
                {filteredPatterns.length} Total
            </p>
        </div>
      </div>

      {/* Table Section */}
      <div className="glass-card overflow-hidden shadow-2xl shadow-blue-900/5">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-gray-50/50 border-b border-gray-100">
                <th className="px-8 py-5 text-[10px] font-black text-gray-400 uppercase tracking-widest">Pattern Identity</th>
                <th className="px-6 py-5 text-[10px] font-black text-gray-400 uppercase tracking-widest">Context</th>
                <th className="px-6 py-5 text-[10px] font-black text-gray-400 uppercase tracking-widest text-center">Stats</th>
                <th className="px-6 py-5 text-[10px] font-black text-gray-400 uppercase tracking-widest">Ownership</th>
                <th className="px-8 py-5 text-[10px] font-black text-gray-400 uppercase tracking-widest text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 bg-white">
              {filteredPatterns.map((pattern) => (
                <tr key={pattern.id} className="hover:bg-blue-50/30 transition-all group">
                  <td className="px-8 py-6">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 bg-blue-50 text-blue-600 rounded-2xl flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                        <FileText size={24} />
                      </div>
                      <div>
                        <p className="font-black text-gray-900 leading-tight mb-1 group-hover:text-blue-600 transition-colors">{pattern.name}</p>
                        <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-[8px] font-black uppercase tracking-wider rounded-md border border-blue-200">
                                {pattern.pattern_source || 'Manual'}
                            </span>
                            <span className="text-[10px] text-gray-400 font-bold">ID: #{pattern.id.toString().padStart(4, '0')}</span>
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-6">
                    <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                            <Hash size={12} className="text-gray-400" />
                            <span className="text-xs font-extrabold text-gray-700 underline decoration-blue-200 underline-offset-2">Class {pattern.class_name}</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <Target size={12} className="text-gray-400" />
                            <span className="text-xs font-bold text-gray-500 uppercase tracking-tight">{pattern.subject}</span>
                        </div>
                    </div>
                  </td>
                  <td className="px-6 py-6">
                    <div className="flex items-center justify-center gap-6">
                        <div className="text-center">
                            <p className="text-xs font-black text-gray-900">{pattern.total_marks || 0}</p>
                            <p className="text-[8px] font-black text-gray-400 uppercase tracking-widest">Marks</p>
                        </div>
                        <div className="w-px h-6 bg-gray-100"></div>
                        <div className="text-center">
                            <p className="text-xs font-black text-gray-900">{pattern.sections?.length || 0}</p>
                            <p className="text-[8px] font-black text-gray-400 uppercase tracking-widest">Sections</p>
                        </div>
                    </div>
                  </td>
                  <td className="px-6 py-6">
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center border-2 border-white shadow-sm overflow-hidden">
                            <User size={16} className="text-slate-500" />
                        </div>
                        <div>
                            <p className="text-xs font-bold text-gray-900 leading-none mb-1">Admin</p>
                            <div className="flex items-center gap-1.5 text-gray-400">
                                <Calendar size={10} />
                                <span className="text-[9px] font-bold tracking-tight">{new Date(pattern.created_at).toLocaleDateString()}</span>
                            </div>
                        </div>
                    </div>
                  </td>
                  <td className="px-8 py-6 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Link 
                        href={`/pattern/${pattern.id}/edit`} 
                        className="p-2.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-xl transition-all"
                        title="Edit Pattern"
                      >
                        <Edit2 size={18} />
                      </Link>
                      <button 
                        onClick={() => handleDelete(pattern.id)}
                        className="p-2.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-xl transition-all"
                        title="Delete Pattern"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filteredPatterns.length === 0 && (
                <tr>
                    <td colSpan="5" className="px-8 py-20 text-center">
                        <div className="flex flex-col items-center">
                            <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mb-4 border border-gray-100">
                                <Search size={32} className="text-gray-200" />
                            </div>
                            <p className="text-sm font-black text-gray-400 uppercase tracking-widest">No matching patterns found</p>
                        </div>
                    </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="bg-gray-50/30 p-6 border-t border-gray-100 flex items-center justify-between">
            <span className="text-[10px] font-black text-gray-400 uppercase tracking-[0.2em]">Listing {filteredPatterns.length} of {patterns.length} Records</span>
            <div className="flex gap-2">
                <button className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-xs font-bold text-gray-400 disabled:opacity-50 cursor-not-allowed">Previous</button>
                <button className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-xs font-bold text-gray-400 disabled:opacity-50 cursor-not-allowed">Next</button>
            </div>
        </div>
      </div>
    </div>
  );
}
