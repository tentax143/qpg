'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Plus, FileText, Download, CheckCircle, AlertTriangle,
  Trash2, RefreshCw, Settings, Upload, FileSignature, Zap, Pencil, RotateCw, Clock,
  TrendingUp, CalendarDays, Award, ArrowUpRight, MoreHorizontal, Search, Filter,
  Sparkles, BookOpen, ClipboardList
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import Modal from '@/components/Modal';

// status_detail is one string of one or more teacher-facing notes. Older papers join
// them with spaces, newer ones with newlines — split on both, and also before each
// known note prefix so a space-joined blob still breaks into separate warnings.
const parseWarnings = (detail) =>
  (detail || '')
    .split(/(?=Marks check —|Coverage —|Generated without)|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);

const getGreeting = () => {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good Morning';
  if (hour < 17) return 'Good Afternoon';
  return 'Good Evening';
};

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
  const [warningPaper, setWarningPaper] = useState(null);  // paper whose warnings/failure detail is shown in the modal
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

  // A paper stuck in 'generating' for >15 min (e.g. a dead worker) is treated as retryable.
  const isStuck = (p) => p.status === 'generating' && p.updated_at
    && (Date.now() - new Date(p.updated_at).getTime() > 15 * 60 * 1000);

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
      <div className="w-6 h-6 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin" />
    </div>
  );

  const statCards = [
    {
      label: 'Total Papers',
      value: stats.total_papers,
      sub: 'All time generated',
      icon: FileText,
      gradient: 'from-indigo-500 to-indigo-600',
      lightBg: 'bg-indigo-50',
      iconColor: 'text-indigo-600',
      borderAccent: 'border-indigo-100',
    },
    {
      label: 'This Month',
      value: stats.this_month,
      sub: 'Current month activity',
      icon: CalendarDays,
      gradient: 'from-emerald-500 to-emerald-600',
      lightBg: 'bg-emerald-50',
      iconColor: 'text-emerald-600',
      borderAccent: 'border-emerald-100',
    },
    {
      label: 'Success Rate',
      value: stats.success_rate,
      sub: 'Completion rate',
      icon: Award,
      gradient: 'from-amber-500 to-orange-500',
      lightBg: 'bg-amber-50',
      iconColor: 'text-amber-600',
      borderAccent: 'border-amber-100',
    },
  ];

  const quickActions = [
    {
      title: 'Generate Paper',
      desc: 'Create a new question paper with AI',
      icon: Sparkles,
      link: '/generator',
      gradient: 'from-indigo-500 to-purple-600',
      hoverGradient: 'hover:from-indigo-600 hover:to-purple-700',
      isPrimary: true,
    },
    {
      title: 'New Blueprint',
      desc: 'Design a custom paper structure',
      icon: FileSignature,
      link: '/blueprints',
      iconBg: 'bg-sky-50',
      iconColor: 'text-sky-600',
      borderColor: 'border-sky-100',
    },
    {
      title: 'Upload Material',
      desc: 'Add study content to your library',
      icon: Upload,
      link: '/materials/upload',
      iconBg: 'bg-emerald-50',
      iconColor: 'text-emerald-600',
      borderColor: 'border-emerald-100',
    },
    {
      title: 'Manage Patterns',
      desc: 'Configure exam pattern templates',
      icon: ClipboardList,
      link: '/patterns',
      iconBg: 'bg-amber-50',
      iconColor: 'text-amber-600',
      borderColor: 'border-amber-100',
    },
  ];

  return (
    <div className="w-full space-y-8 pb-8">
      {/* Welcome Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-indigo-600 mb-1 tracking-wide uppercase">{getGreeting()}</p>
          <h1 className="text-[28px] font-bold text-slate-900 tracking-tight leading-tight">
            Welcome back{user?.username ? `, ${user.username}` : ''} 👋
          </h1>
          <p className="text-[15px] text-slate-500 mt-1.5 leading-relaxed">
            Here's what's happening with your question papers today.
          </p>
        </div>
        <Link
          href="/generator"
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white text-sm font-semibold rounded-2xl transition-all duration-300 shadow-lg shadow-indigo-200/50 hover:shadow-indigo-300/50 hover:scale-[1.02] active:scale-[0.98]"
        >
          <Plus className="w-4 h-4" strokeWidth={2.5} />
          New Paper
        </Link>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        {statCards.map((stat, i) => (
          <div
            key={i}
            className={`relative overflow-hidden bg-white border ${stat.borderAccent} rounded-2xl p-6 transition-all duration-300 hover:shadow-lg hover:shadow-slate-100/50 hover:-translate-y-0.5 group`}
          >
            {/* Subtle gradient accent line at top */}
            <div className={`absolute top-0 left-0 right-0 h-[3px] bg-gradient-to-r ${stat.gradient} opacity-80`} />
            
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[13px] font-semibold text-slate-500 tracking-wide">{stat.label}</p>
                <p className="text-[36px] font-extrabold text-slate-900 mt-2 tracking-tight leading-none">{stat.value}</p>
                <p className="text-[12px] text-slate-400 mt-2 font-medium">{stat.sub}</p>
              </div>
              <div className={`${stat.lightBg} w-12 h-12 rounded-2xl flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}>
                <stat.icon className={`w-6 h-6 ${stat.iconColor}`} strokeWidth={1.75} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}
      {error && <ErrorAlert message={error} onClose={() => setError(null)} />}

      {/* Quick Actions */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[16px] font-bold text-slate-900 tracking-tight">Quick Actions</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {quickActions.map((action, i) => (
            action.isPrimary ? (
              <Link
                key={i}
                href={action.link}
                className={`relative overflow-hidden bg-gradient-to-br ${action.gradient} ${action.hoverGradient} rounded-2xl p-5 transition-all duration-300 hover:shadow-xl hover:shadow-indigo-200/40 hover:-translate-y-0.5 group`}
              >
                <div className="absolute top-0 right-0 w-24 h-24 bg-white/10 rounded-full -translate-x-4 -translate-y-8 group-hover:scale-110 transition-transform duration-500" />
                <div className="absolute bottom-0 left-0 w-16 h-16 bg-white/5 rounded-full translate-x-2 translate-y-6" />
                <div className="relative">
                  <div className="w-11 h-11 bg-white/20 backdrop-blur-sm rounded-2xl flex items-center justify-center mb-4 group-hover:scale-105 transition-transform duration-300">
                    <action.icon className="w-5 h-5 text-white" strokeWidth={1.75} />
                  </div>
                  <h3 className="text-[15px] font-bold text-white">{action.title}</h3>
                  <p className="text-[12px] text-white/70 mt-1">{action.desc}</p>
                </div>
              </Link>
            ) : (
              <Link
                key={i}
                href={action.link}
                className={`bg-white border ${action.borderColor} rounded-2xl p-5 transition-all duration-300 hover:shadow-lg hover:shadow-slate-100/50 hover:-translate-y-0.5 group`}
              >
                <div className={`${action.iconBg} w-11 h-11 rounded-2xl flex items-center justify-center mb-4 group-hover:scale-105 transition-transform duration-300`}>
                  <action.icon className={`w-5 h-5 ${action.iconColor}`} strokeWidth={1.75} />
                </div>
                <h3 className="text-[15px] font-bold text-slate-900">{action.title}</h3>
                <p className="text-[12px] text-slate-400 mt-1">{action.desc}</p>
              </Link>
            )
          ))}
        </div>
      </div>

      {/* Papers Table */}
      <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm shadow-slate-100/50">
        <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between">
          <div>
            <h2 className="text-[16px] font-bold text-slate-900 tracking-tight">Recent Papers</h2>
            <p className="text-[12px] text-slate-400 mt-0.5">Your latest generated question papers</p>
          </div>
          <div className="flex items-center gap-2">
            {selectedPapers.length > 0 && (
              <button
                onClick={handleBulkDelete}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-red-600 border border-red-200 bg-red-50 rounded-xl text-xs font-semibold hover:bg-red-100 transition-all duration-200 active:scale-95"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Delete ({selectedPapers.length})
              </button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/50">
                <th className="w-10 px-6 py-3.5 text-left">
                  <input
                    type="checkbox"
                    className="rounded-md border-slate-300 text-indigo-600 focus:ring-indigo-500/20 transition-all w-4 h-4"
                    checked={selectedPapers.length === stats.recent_activity.length && stats.recent_activity.length > 0}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="px-6 py-3.5 text-left text-[11px] font-bold text-slate-400 uppercase tracking-widest">Paper</th>
                <th className="px-6 py-3.5 text-left text-[11px] font-bold text-slate-400 uppercase tracking-widest">Pattern</th>
                <th className="px-6 py-3.5 text-left text-[11px] font-bold text-slate-400 uppercase tracking-widest">Status</th>
                <th className="px-6 py-3.5 text-right text-[11px] font-bold text-slate-400 uppercase tracking-widest">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {stats.recent_activity.length > 0 ? stats.recent_activity.map((paper) => (
                <tr key={paper.id} className="hover:bg-slate-50/70 transition-colors duration-200 group">
                  <td className="px-6 py-4">
                    <input
                      type="checkbox"
                      className="rounded-md border-slate-300 text-indigo-600 focus:ring-indigo-500/20 transition-all w-4 h-4"
                      checked={selectedPapers.includes(paper.id)}
                      onChange={() => toggleSelectPaper(paper.id)}
                    />
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3.5">
                      <div className="w-10 h-10 bg-gradient-to-br from-slate-100 to-slate-50 border border-slate-200/80 rounded-xl flex items-center justify-center text-slate-700 text-xs font-bold shrink-0 shadow-sm">
                        {paper.class_name}
                      </div>
                      <div>
                        <p className="font-semibold text-slate-900 text-[14px]">{paper.subject}</p>
                        <p className="text-[12px] text-slate-400 mt-0.5">{new Date(paper.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[12px] text-slate-600 bg-slate-100/80 px-3 py-1.5 rounded-lg font-semibold border border-slate-100">
                      {paper.pattern_name || 'Standard'}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    {paper.status === 'done' ? (
                      paper.status_detail ? (
                        <button
                          type="button"
                          onClick={() => setWarningPaper(paper)}
                          title="Click to see what to check"
                          className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200/80 px-3 py-1.5 rounded-xl hover:bg-emerald-100 transition-all duration-200 cursor-pointer"
                        >
                          <CheckCircle className="w-3.5 h-3.5" />
                          Completed ⚠
                        </button>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200/80 px-3 py-1.5 rounded-xl">
                          <CheckCircle className="w-3.5 h-3.5" />
                          Completed
                        </span>
                      )
                    ) : paper.status === 'failed' ? (
                      <button
                        type="button"
                        onClick={() => paper.status_detail && setWarningPaper(paper)}
                        title={paper.status_detail ? 'Click to see why it failed' : 'Generation failed'}
                        className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-red-700 bg-red-50 border border-red-200/80 px-3 py-1.5 rounded-xl hover:bg-red-100 transition-all duration-200 cursor-pointer disabled:cursor-default"
                        disabled={!paper.status_detail}
                      >
                        Failed
                      </button>
                    ) : isStuck(paper) ? (
                      <span title="Generation looks stalled — you can retry." className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-amber-700 bg-amber-50 border border-amber-200/80 px-3 py-1.5 rounded-xl">
                        Stalled
                      </span>
                    ) : paper.status === 'queued' ? (
                      <span title="Waiting behind your current generation — it starts automatically." className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-amber-700 bg-amber-50 border border-amber-200/80 px-3 py-1.5 rounded-xl">
                        <Clock className="w-3.5 h-3.5" />
                        Queued
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200/80 px-3 py-1.5 rounded-xl">
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        Generating
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      {paper.status === 'done' && (
                        <Link
                          href={`/papers/${paper.id}/edit`}
                          className="p-2 text-slate-500 hover:text-indigo-600 bg-slate-50 hover:bg-indigo-50 rounded-xl transition-all duration-200 hover:scale-105 active:scale-95"
                          title="Edit paper"
                        >
                          <Pencil className="w-4 h-4" strokeWidth={1.75} />
                        </Link>
                      )}
                      {paper.file && (
                        <a
                          href={paper.file}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="p-2 text-slate-500 hover:text-emerald-600 bg-slate-50 hover:bg-emerald-50 rounded-xl transition-all duration-200 hover:scale-105 active:scale-95"
                          title="Download"
                        >
                          <Download className="w-4 h-4" strokeWidth={1.75} />
                        </a>
                      )}
                      {paper.status === 'done' && paper.has_paper_data && (
                        <button
                          onClick={() => handleRerender(paper.id)}
                          disabled={rerenderingId === paper.id}
                          className="p-2 text-slate-500 hover:text-violet-600 bg-slate-50 hover:bg-violet-50 rounded-xl transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed hover:scale-105 active:scale-95"
                          title="Re-render DOCX"
                        >
                          {rerenderingId === paper.id
                            ? <RefreshCw className="w-4 h-4 animate-spin" />
                            : <Zap className="w-4 h-4" strokeWidth={1.75} />
                          }
                        </button>
                      )}
                      {paper.status === 'done' && (
                        <button
                          onClick={() => handleRegenerate(paper.id)}
                          disabled={regeneratingId === paper.id}
                          className="p-2 text-slate-500 hover:text-amber-600 bg-slate-50 hover:bg-amber-50 rounded-xl transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed hover:scale-105 active:scale-95"
                          title="Regenerate fresh questions (same pattern, class, subject & chapters)"
                        >
                          <RotateCw className={`w-4 h-4 ${regeneratingId === paper.id ? 'animate-spin' : ''}`} strokeWidth={1.75} />
                        </button>
                      )}
                      {(paper.status === 'failed' || isStuck(paper)) && (
                        <button
                          onClick={() => handleRetry(paper.id)}
                          className="p-2 text-slate-500 hover:text-emerald-600 bg-slate-50 hover:bg-emerald-50 rounded-xl transition-all duration-200 hover:scale-105 active:scale-95"
                          title={paper.status_detail || 'Retry'}
                        >
                          <RefreshCw className="w-4 h-4" strokeWidth={1.75} />
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(paper.id)}
                        className="p-2 text-slate-500 hover:text-red-500 bg-slate-50 hover:bg-red-50 rounded-xl transition-all duration-200 hover:scale-105 active:scale-95"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" strokeWidth={1.75} />
                      </button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan="5" className="py-20 text-center">
                    <div className="flex flex-col items-center">
                      <div className="w-16 h-16 bg-gradient-to-br from-slate-100 to-slate-50 rounded-3xl flex items-center justify-center mb-5 shadow-sm border border-slate-100">
                        <FileText className="w-7 h-7 text-slate-300" strokeWidth={1.5} />
                      </div>
                      <p className="text-[15px] font-semibold text-slate-700">No papers yet</p>
                      <p className="text-[13px] text-slate-400 mt-1.5 max-w-[280px] leading-relaxed">
                        Generate your first question paper to get started with qForge AI
                      </p>
                      <Link
                        href="/generator"
                        className="inline-flex items-center gap-2 mt-5 px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-indigo-700 text-white text-sm font-semibold rounded-2xl hover:from-indigo-700 hover:to-indigo-800 transition-all duration-300 shadow-lg shadow-indigo-200/50 hover:scale-[1.02] active:scale-[0.98]"
                      >
                        <Sparkles className="w-4 h-4" />
                        Create Your First Paper
                      </Link>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Warnings / failure-reason popup for a paper's status badge */}
      <Modal
        isOpen={!!warningPaper}
        onClose={() => setWarningPaper(null)}
        title={warningPaper?.status === 'failed' ? 'Why this paper failed' : 'Things to check'}
        size="lg"
      >
        {warningPaper && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 pb-3 border-b border-slate-100">
              <div className="w-10 h-10 bg-gradient-to-br from-slate-100 to-slate-50 border border-slate-200/80 rounded-xl flex items-center justify-center text-slate-700 text-xs font-bold shrink-0 shadow-sm">
                {warningPaper.class_name}
              </div>
              <div>
                <p className="font-semibold text-slate-900">{warningPaper.subject}</p>
                <p className="text-xs text-slate-400">{warningPaper.pattern_name || 'Standard'}</p>
              </div>
            </div>

            {warningPaper.status === 'failed' ? (
              <div className="flex gap-2.5 p-4 rounded-2xl bg-red-50 border border-red-100 text-sm text-red-800">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                <span className="break-words">{warningPaper.status_detail}</span>
              </div>
            ) : (
              <>
                <p className="text-sm text-slate-600">
                  The paper generated successfully, but a few things are worth a quick look before you hand it out:
                </p>
                <ul className="space-y-2">
                  {parseWarnings(warningPaper.status_detail).map((w, i) => (
                    <li
                      key={i}
                      className="flex gap-2.5 p-4 rounded-2xl bg-amber-50 border border-amber-100 text-sm text-amber-900"
                    >
                      <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-amber-500" />
                      <span className="break-words">{w}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-slate-400">
                  Tip: use <span className="font-medium text-amber-600">Regenerate</span> to rebuild fresh
                  questions from the pattern, or open the paper to edit it directly.
                </p>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
