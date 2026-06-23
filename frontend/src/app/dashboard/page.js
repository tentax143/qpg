'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Plus, FileText, Download, CheckCircle,
  Trash2, RefreshCw, Settings, Upload, FileSignature, Zap, Pencil, RotateCw
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function DashboardPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState(null);
  const [stats, setStats] = useState({
    total_papers: 0,
    this_month: 0,
    success_rate: '0%',
    recent_activity: []
  });
  const [selectedPapers, setSelectedPapers] = useState([]);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [rerenderingId, setRerenderingId] = useState(null);
  const [regeneratingId, setRegeneratingId] = useState(null);
  const pollingIntervalRef = useRef(null);

  useEffect(() => {
    const token = localStorage.getItem('authToken');
    const userData = localStorage.getItem('user');
    if (!token) { router.push('/'); return; }
    if (userData) setUser(JSON.parse(userData));
    fetchDashboardData();
    setLoading(false);
    return () => { if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current); };
  }, []);

  useEffect(() => {
    const hasGeneratingPapers = stats.recent_activity.some(p =>
      p.status === 'generating' || p.status === 'queued'
    );
    if (hasGeneratingPapers && !pollingIntervalRef.current) {
      pollingIntervalRef.current = setInterval(() => { fetchDashboardData(); }, 3000);
    } else if (!hasGeneratingPapers && pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    return () => {
      if (pollingIntervalRef.current && !hasGeneratingPapers) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [stats.recent_activity]);

  const fetchDashboardData = async () => {
    try {
      const papersRes = await apiClient.get('/papers/?page_size=100');
      const papers = papersRes.data.results || [];
      const total = papers.length;
      const now = new Date();
      const firstDayOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
      const thisMonth = papers.filter(p => new Date(p.created_at) >= firstDayOfMonth).length;
      const successCount = papers.filter(p => p.status === 'done').length;
      const successRate = total > 0 ? Math.round((successCount / total) * 100) : 0;
      setStats({
        total_papers: total,
        this_month: thisMonth,
        success_rate: `${successRate}%`,
        recent_activity: papers.slice(0, 10)
      });
    } catch (err) {
      if (err.response?.status === 401) {
        localStorage.removeItem('authToken');
        router.push('/');
      }
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this paper?')) return;
    try {
      await apiClient.delete(`/papers/${id}/`);
      setSuccess('Paper deleted');
      fetchDashboardData();
    } catch { setError('Failed to delete paper'); }
  };

  const handleBulkDelete = async () => {
    if (!confirm(`Delete ${selectedPapers.length} papers?`)) return;
    try {
      await apiClient.post('/papers/bulk-delete/', { ids: selectedPapers });
      setSuccess(`${selectedPapers.length} papers deleted`);
      setSelectedPapers([]);
      fetchDashboardData();
    } catch { setError('Bulk delete failed'); }
  };

  const handleRetry = async (id) => {
    try {
      await apiClient.post(`/papers/${id}/retry/`);
      setSuccess('Retrying generation');
      fetchDashboardData();
    } catch { setError('Retry failed'); }
  };

  const handleRerender = async (id) => {
    setRerenderingId(id);
    try {
      await apiClient.post(`/papers/${id}/rerender/`);
      setSuccess('Paper re-rendered successfully');
      fetchDashboardData();
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
      fetchDashboardData();   // status flips to generating; the list shows the spinner
    } catch (err) {
      setError(err?.response?.data?.error || 'Could not start regeneration');
    } finally {
      setRegeneratingId(null);
    }
  };


  const toggleSelectPaper = (id) => {
    setSelectedPapers(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
  };

  const toggleSelectAll = () => {
    setSelectedPapers(
      selectedPapers.length === stats.recent_activity.length
        ? []
        : stats.recent_activity.map(p => p.id)
    );
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
    </div>
  );

  return (
    <div className="w-full space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 tracking-tight">Dashboard</h1>
          <p className="text-sm text-slate-500 mt-0.5">Manage and track your question papers</p>
        </div>
        <Link
          href="/generator"
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Paper
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: 'Total Papers', value: stats.total_papers, sub: 'All time' },
          { label: 'This Month', value: stats.this_month, sub: 'Current month' },
          { label: 'Success Rate', value: stats.success_rate, sub: 'Completion rate' },
        ].map((stat, i) => (
          <div key={i} className="bg-white border border-slate-200 rounded-xl p-5">
            <p className="text-xs font-medium text-slate-500">{stat.label}</p>
            <p className="text-3xl font-semibold text-slate-900 mt-1.5 tracking-tight">{stat.value}</p>
            <p className="text-xs text-slate-400 mt-1">{stat.sub}</p>
          </div>
        ))}
      </div>

      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}
      {error && <ErrorAlert message={error} onClose={() => setError(null)} />}

      <div className="space-y-6">
        {/* Papers table */}
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">Recent Papers</h2>
              {selectedPapers.length > 0 && (
                <button
                  onClick={handleBulkDelete}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-red-600 border border-red-200 bg-red-50 rounded-md text-xs font-medium hover:bg-red-100 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Delete ({selectedPapers.length})
                </button>
              )}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/60">
                    <th className="w-10 px-5 py-3 text-left">
                      <input
                        type="checkbox"
                        className="rounded border-slate-300 text-blue-600"
                        checked={selectedPapers.length === stats.recent_activity.length && stats.recent_activity.length > 0}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Paper</th>
                    <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Pattern</th>
                    <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                    <th className="px-5 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {stats.recent_activity.length > 0 ? stats.recent_activity.map((paper) => (
                    <tr key={paper.id} className="hover:bg-slate-50/70 transition-colors">
                      <td className="px-5 py-4">
                        <input
                          type="checkbox"
                          className="rounded border-slate-300 text-blue-600"
                          checked={selectedPapers.includes(paper.id)}
                          onChange={() => toggleSelectPaper(paper.id)}
                        />
                      </td>
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 bg-slate-100 border border-slate-200 rounded-md flex items-center justify-center text-slate-700 text-xs font-semibold shrink-0">
                            {paper.class_name}
                          </div>
                          <div>
                            <p className="font-medium text-slate-900">{paper.subject}</p>
                            <p className="text-xs text-slate-400">{new Date(paper.created_at).toLocaleDateString()}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-4">
                        <span className="text-xs text-slate-600 bg-slate-100 px-2.5 py-1 rounded-md font-medium">
                          {paper.pattern_name || 'Standard'}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        {paper.status === 'done' ? (
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-full">
                            <CheckCircle className="w-3.5 h-3.5" />
                            Completed
                          </span>
                        ) : paper.status === 'failed' ? (
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-red-700 bg-red-50 border border-red-200 px-2.5 py-1 rounded-full">
                            Failed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 px-2.5 py-1 rounded-full">
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                            Generating
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {paper.status === 'done' && (
                            <Link
                              href={`/papers/${paper.id}/edit`}
                              className="p-1.5 text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-md transition-colors"
                              title="Edit paper"
                            >
                              <Pencil className="w-4 h-4" />
                            </Link>
                          )}
                          {paper.file && (
                            <a
                              href={paper.file}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-1.5 text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-md transition-colors"
                              title="Download"
                            >
                              <Download className="w-4 h-4" />
                            </a>
                          )}
                          {paper.status === 'done' && paper.has_paper_data && (
                            <button
                              onClick={() => handleRerender(paper.id)}
                              disabled={rerenderingId === paper.id}
                              className="p-1.5 text-violet-600 bg-violet-50 hover:bg-violet-100 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                              title="Re-render DOCX"
                            >
                              {rerenderingId === paper.id
                                ? <RefreshCw className="w-4 h-4 animate-spin" />
                                : <Zap className="w-4 h-4" />
                              }
                            </button>
                          )}
                          {paper.status === 'done' && (
                            <button
                              onClick={() => handleRegenerate(paper.id)}
                              disabled={regeneratingId === paper.id}
                              className="p-1.5 text-amber-600 bg-amber-50 hover:bg-amber-100 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                              title="Regenerate fresh questions (same pattern, class, subject & chapters)"
                            >
                              <RotateCw className={`w-4 h-4 ${regeneratingId === paper.id ? 'animate-spin' : ''}`} />
                            </button>
                          )}
                          {paper.status === 'failed' && (
                            <button
                              onClick={() => handleRetry(paper.id)}
                              className="p-1.5 text-emerald-600 bg-emerald-50 hover:bg-emerald-100 rounded-md transition-colors"
                              title="Retry"
                            >
                              <RefreshCw className="w-4 h-4" />
                            </button>
                          )}
                          <button
                            onClick={() => handleDelete(paper.id)}
                            className="p-1.5 text-red-500 bg-red-50 hover:bg-red-100 rounded-md transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan="5" className="py-16 text-center">
                        <FileText className="w-8 h-8 text-slate-300 mx-auto mb-3" />
                        <p className="text-sm font-medium text-slate-600">No papers yet</p>
                        <p className="text-xs text-slate-400 mt-1">Generate your first question paper to get started</p>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Quick actions */}
          <div>
            <h3 className="text-sm font-semibold text-slate-900 mb-3">Quick Actions</h3>
            <div className="grid grid-cols-3 gap-3">
              {[
                { title: 'New Blueprint', icon: FileSignature, link: '/blueprints' },
                { title: 'Upload Material', icon: Upload, link: '/materials' },
                { title: 'Manage Patterns', icon: Settings, link: '/patterns' },
              ].map((action, i) => (
                <Link
                  key={i}
                  href={action.link}
                  className="flex items-center gap-2.5 p-4 bg-white border border-slate-200 rounded-xl hover:border-slate-300 hover:bg-slate-50 transition-all text-sm text-slate-700 font-medium group"
                >
                  <action.icon className="w-4 h-4 text-slate-400 group-hover:text-blue-600 transition-colors shrink-0" />
                  {action.title}
                </Link>
              ))}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
