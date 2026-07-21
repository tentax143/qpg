'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { School, Users, FileText, TrendingUp, ChevronRight, Plus, RefreshCw, CheckCircle, XCircle, Loader2, X, Sparkles, LayoutDashboard } from 'lucide-react';

function StatCard({ label, value, sub, icon: Icon, colorClass, bgClass, borderClass }) {
  return (
    <div className={`bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:shadow-lg transition-all group`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[12px] font-bold text-slate-500 uppercase tracking-wider mb-2">{label}</p>
          <p className="text-[32px] font-extrabold text-slate-900 tracking-tight">{value}</p>
          {sub && <p className="text-[12px] text-slate-400 font-medium mt-1">{sub}</p>}
        </div>
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${bgClass} border ${borderClass} transition-transform group-hover:scale-110`}>
          <Icon className={`w-6 h-6 ${colorClass}`} />
        </div>
      </div>
    </div>
  );
}

export default function SuperAdminDashboard() {
  const router = useRouter();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // CBSE pattern updater state
  const [cbseModal, setCbseModal] = useState(false);
  const [cbseState, setCbseState] = useState('idle'); // idle | running | done | error
  const [cbseProgress, setCbseProgress] = useState({ current: 0, total: 0, current_subject: '', results: [] });
  const pollRef = useRef(null);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') {
      router.replace('/dashboard');
      return;
    }
    apiClient.get('/admin/dashboard/')
      .then(r => setData(r.data))
      .catch(e => setError(e.response?.data?.error || 'Failed to load dashboard'))
      .finally(() => setLoading(false));
  }, [router]);

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function handleStartCbseUpdate() {
    setCbseModal(true);
    setCbseState('running');
    setCbseProgress({ current: 0, total: 0, current_subject: 'Starting…', results: [] });
    try {
      const r = await apiClient.post('/admin/cbse-patterns/update/');
      const taskId = r.data.task_id;
      pollRef.current = setInterval(async () => {
        try {
          const s = await apiClient.get(`/admin/cbse-patterns/status/${taskId}/`);
          const d = s.data;
          setCbseProgress({ current: d.current, total: d.total, current_subject: d.current_subject || '', results: d.results || [] });
          if (d.state === 'done') { stopPolling(); setCbseState('done'); }
          if (d.state === 'error') { stopPolling(); setCbseState('error'); }
        } catch { stopPolling(); setCbseState('error'); }
      }, 2000);
    } catch (e) {
      setCbseState('error');
      setCbseProgress(p => ({ ...p, current_subject: e.response?.data?.error || 'Failed to start' }));
    }
  }

  function handleCloseModal() {
    stopPolling();
    setCbseModal(false);
    setCbseState('idle');
    setCbseProgress({ current: 0, total: 0, current_subject: '', results: [] });
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
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">System Overview</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">Platform-wide activity, analytics, and tenant management.</p>
        </div>
        
        <div className="flex items-center gap-3">
          <button
            onClick={handleStartCbseUpdate}
            disabled={cbseState === 'running'}
            className="px-5 py-3.5 bg-slate-900 hover:bg-slate-800 text-white rounded-2xl font-bold text-[13px] shadow-sm transition-all flex items-center gap-2 disabled:opacity-60 active:scale-[0.98]"
          >
            <RefreshCw className={`w-4 h-4 ${cbseState === 'running' ? 'animate-spin' : ''}`} />
            Update CBSE Patterns
          </button>
          <Link
            href="/superadmin/schools/new"
            className="px-5 py-3.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-indigo-200/50 transition-all flex items-center gap-2 active:scale-[0.98]"
          >
            <Plus size={16} strokeWidth={2.5} />
            Add School
          </Link>
        </div>
      </div>

      <div className="max-w-7xl mx-auto space-y-8">
        {/* Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
          <StatCard label="Schools" value={data.total_schools} icon={School} colorClass="text-blue-500" bgClass="bg-blue-50" borderClass="border-blue-100" />
          <StatCard label="Total Users" value={data.total_users} icon={Users} colorClass="text-violet-500" bgClass="bg-violet-50" borderClass="border-violet-100" />
          <StatCard label="Papers Generated" value={data.total_papers} icon={FileText} colorClass="text-emerald-500" bgClass="bg-emerald-50" borderClass="border-emerald-100" />
          <StatCard
            label="Total Tokens"
            value={data.total_tokens > 0 ? data.total_tokens.toLocaleString() : '—'}
            sub={data.total_cost > 0 ? `₹${Number(data.total_cost).toFixed(4)}` : null}
            icon={TrendingUp}
            colorClass="text-amber-500" bgClass="bg-amber-50" borderClass="border-amber-100"
          />
        </div>

        {/* Schools table */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center gap-4 bg-slate-50/50">
            <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center border border-indigo-100">
              <LayoutDashboard size={20} strokeWidth={2} />
            </div>
            <div>
              <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Active Schools</h2>
              <p className="text-[12px] text-slate-500 font-medium mt-0.5">Manage tenant organizations</p>
            </div>
          </div>

          {data.schools.length === 0 ? (
            <div className="py-16 text-center">
              <div className="w-16 h-16 bg-slate-50 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-slate-100">
                <School size={24} className="text-slate-300" strokeWidth={1.5} />
              </div>
              <h3 className="text-[16px] font-bold text-slate-900 mb-1">No schools registered yet</h3>
              <p className="text-[13px] text-slate-500 mb-6">Create the first tenant to start onboarding users.</p>
              <Link href="/superadmin/schools/new" className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 text-white rounded-xl font-bold text-[13px] hover:bg-indigo-700 transition-all shadow-sm active:scale-[0.98]">
                <Plus size={16} />
                Create School
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-slate-50">
              {data.schools.map(school => (
                <Link
                  key={school.id}
                  href={`/superadmin/schools/${school.id}`}
                  className="flex items-center justify-between px-8 py-5 hover:bg-slate-50/80 transition-colors group"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-slate-100 rounded-xl flex items-center justify-center text-slate-600 text-[13px] font-extrabold shadow-sm group-hover:bg-indigo-50 group-hover:text-indigo-600 transition-colors">
                      {school.name.charAt(0)}
                    </div>
                    <div>
                      <p className="text-[15px] font-bold text-slate-900">{school.name}</p>
                      <p className="text-[12px] text-slate-400 font-medium mt-0.5">
                        {school.member_count} member{school.member_count !== 1 ? 's' : ''} · {school.paper_count} paper{school.paper_count !== 1 ? 's' : ''}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-5">
                    {school.monthly_token_budget > 0 && (
                      <span className="text-[12px] font-semibold text-slate-500">
                        <span className="text-slate-700">{school.total_tokens.toLocaleString()}</span> / {school.monthly_token_budget.toLocaleString()} tokens
                      </span>
                    )}
                    <span className={`inline-flex px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${school.is_active ? 'bg-emerald-50 text-emerald-700 border border-emerald-100/50' : 'bg-slate-100 text-slate-500 border border-slate-200/50'}`}>
                      {school.is_active ? 'Active' : 'Inactive'}
                    </span>
                    <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-indigo-400 transition-colors" />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* CBSE Update Modal */}
      {cbseModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-[28px] shadow-2xl w-full max-w-lg mx-4 overflow-hidden border border-slate-100 scale-100 animate-in zoom-in-95 duration-200">
            {/* Modal header */}
            <div className="flex items-center justify-between px-8 py-6 border-b border-slate-100 bg-slate-50/50">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center border border-indigo-100">
                  <RefreshCw className={`w-5 h-5 ${cbseState === 'running' ? 'animate-spin' : ''}`} />
                </div>
                <h3 className="text-[18px] font-bold text-slate-900 tracking-tight">Update CBSE Patterns</h3>
              </div>
              {cbseState !== 'running' && (
                <button onClick={handleCloseModal} className="w-8 h-8 flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-colors">
                  <X className="w-5 h-5" />
                </button>
              )}
            </div>

            {/* Progress */}
            <div className="px-8 py-6">
              {cbseState === 'running' && (
                <>
                  <div className="flex items-center justify-between text-[13px] font-bold mb-3">
                    <span className="text-slate-600 truncate">{cbseProgress.current_subject || 'Initialising…'}</span>
                    <span className="text-indigo-600 shrink-0 ml-2">{cbseProgress.current} / {cbseProgress.total}</span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2.5 mb-6 overflow-hidden">
                    <div
                      className="bg-indigo-600 h-full rounded-full transition-all duration-500"
                      style={{ width: cbseProgress.total ? `${(cbseProgress.current / cbseProgress.total) * 100}%` : '4%' }}
                    />
                  </div>
                </>
              )}

              {cbseState === 'done' && (
                <div className="flex items-center gap-2.5 text-emerald-600 text-[14px] font-bold mb-6 bg-emerald-50 px-4 py-3 rounded-xl border border-emerald-100/50">
                  <CheckCircle className="w-5 h-5" />
                  All {cbseProgress.total} patterns processed successfully.
                </div>
              )}

              {cbseState === 'error' && (
                <div className="flex items-center gap-2.5 text-red-600 text-[14px] font-bold mb-6 bg-red-50 px-4 py-3 rounded-xl border border-red-100/50">
                  <XCircle className="w-5 h-5" />
                  {cbseProgress.current_subject || 'An error occurred during update.'}
                </div>
              )}

              {/* Results list */}
              {cbseProgress.results.length > 0 && (
                <div className="max-h-64 overflow-y-auto space-y-2 pr-2">
                  {cbseProgress.results.map((r, i) => (
                    <div key={i} className="flex items-center gap-3 text-[13px] p-3 rounded-xl border border-slate-100 bg-white shadow-sm">
                      {r.status === 'updated' ? (
                        <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
                      ) : r.status === 'error' ? (
                        <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                      ) : (
                        <div className="w-4 h-4 rounded-full bg-slate-100 shrink-0" />
                      )}
                      <span className="flex-1 font-bold text-slate-700 truncate">
                        {r.subject} <span className="text-slate-400 font-medium">Cl.{r.class_name}</span>
                      </span>
                      {r.status === 'updated' && (
                        <span className="text-[11px] font-bold text-slate-400 bg-slate-50 px-2 py-1 rounded-md">{r.marks}M · {r.questions}Q</span>
                      )}
                      {r.status === 'error' && (
                        <span className="text-[11px] font-bold text-red-400 truncate max-w-[120px] bg-red-50 px-2 py-1 rounded-md">{r.error}</span>
                      )}
                    </div>
                  ))}
                  {cbseState === 'running' && cbseProgress.current < cbseProgress.total && (
                    <div className="flex items-center justify-center gap-2 text-[12px] font-bold py-4 text-slate-400">
                      <Loader2 className="w-4 h-4 animate-spin shrink-0 text-indigo-400" />
                      Processing {cbseProgress.current_subject}…
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-8 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between">
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Powered by DeepSeek V3.2</p>
              {cbseState !== 'running' && (
                <button onClick={handleCloseModal} className="px-5 py-2.5 bg-white border border-slate-200 text-slate-600 rounded-xl text-[12px] font-bold hover:bg-slate-50 transition-colors shadow-sm">
                  Close Window
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
