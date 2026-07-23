'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { School, Users, FileText, TrendingUp, ChevronRight, Plus, RefreshCw, CheckCircle, XCircle, Loader2, X } from 'lucide-react';

function StatCard({ label, value, sub, icon: Icon, color }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-500 mb-1">{label}</p>
          <p className="text-2xl font-semibold text-slate-900">{value}</p>
          {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
          <Icon className="w-5 h-5 text-white" />
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
    <div className="flex items-center justify-center min-h-[300px]">
      <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
    </div>
  );

  if (error) return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">{error}</div>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Overview</h1>
          <p className="text-sm text-slate-500 mt-0.5">Platform-wide activity and school management</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleStartCbseUpdate}
            disabled={cbseState === 'running'}
            className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-900 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-60"
          >
            <RefreshCw className={`w-4 h-4 ${cbseState === 'running' ? 'animate-spin' : ''}`} />
            Update CBSE Patterns
          </button>
          <Link
            href="/superadmin/schools/new"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add School
          </Link>
        </div>
      </div>

      {/* CBSE Update Modal */}
      {cbseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
              <div className="flex items-center gap-2">
                <RefreshCw className={`w-4 h-4 text-blue-600 ${cbseState === 'running' ? 'animate-spin' : ''}`} />
                <h3 className="font-semibold text-slate-900">Update CBSE Patterns</h3>
              </div>
              {cbseState !== 'running' && (
                <button onClick={handleCloseModal} className="text-slate-400 hover:text-slate-600">
                  <X className="w-5 h-5" />
                </button>
              )}
            </div>

            {/* Progress */}
            <div className="px-6 py-4">
              {cbseState === 'running' && (
                <>
                  <div className="flex items-center justify-between text-sm mb-2">
                    <span className="text-slate-600 truncate">{cbseProgress.current_subject || 'Initialising…'}</span>
                    <span className="text-slate-400 shrink-0 ml-2">{cbseProgress.current}/{cbseProgress.total}</span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2 mb-4">
                    <div
                      className="bg-blue-600 h-2 rounded-full transition-all duration-500"
                      style={{ width: cbseProgress.total ? `${(cbseProgress.current / cbseProgress.total) * 100}%` : '4%' }}
                    />
                  </div>
                </>
              )}

              {cbseState === 'done' && (
                <div className="flex items-center gap-2 text-emerald-600 text-sm font-medium mb-4">
                  <CheckCircle className="w-4 h-4" />
                  All {cbseProgress.total} patterns processed
                </div>
              )}

              {cbseState === 'error' && (
                <div className="flex items-center gap-2 text-red-600 text-sm font-medium mb-4">
                  <XCircle className="w-4 h-4" />
                  {cbseProgress.current_subject || 'An error occurred'}
                </div>
              )}

              {/* Results list */}
              {cbseProgress.results.length > 0 && (
                <div className="max-h-64 overflow-y-auto space-y-1">
                  {cbseProgress.results.map((r, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs py-1 border-b border-slate-50">
                      {r.status === 'updated' ? (
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                      ) : r.status === 'error' ? (
                        <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                      ) : (
                        <div className="w-3.5 h-3.5 rounded-full bg-slate-200 shrink-0" />
                      )}
                      <span className="flex-1 text-slate-700 truncate">
                        {r.subject} Cl.{r.class_name}
                      </span>
                      {r.status === 'updated' && (
                        <span className="text-slate-400">{r.marks}M · {r.questions}Q</span>
                      )}
                      {r.status === 'error' && (
                        <span className="text-red-400 truncate max-w-[120px]">{r.error}</span>
                      )}
                    </div>
                  ))}
                  {cbseState === 'running' && cbseProgress.current < cbseProgress.total && (
                    <div className="flex items-center gap-2 text-xs py-1 text-slate-400">
                      <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
                      Processing {cbseProgress.current_subject}…
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between">
              <p className="text-xs text-slate-400">Powered by DeepSeek V3.2 via Bedrock Mantle</p>
              {cbseState !== 'running' && (
                <button onClick={handleCloseModal} className="text-sm font-medium text-slate-600 hover:text-slate-900">
                  Close
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Schools" value={data.total_schools} icon={School} color="bg-blue-600" />
        <StatCard label="Total Users" value={data.total_users} icon={Users} color="bg-violet-600" />
        <StatCard label="Papers Generated" value={data.total_papers} icon={FileText} color="bg-emerald-600" />
        <StatCard
          label="Total Tokens"
          value={data.total_tokens > 0 ? data.total_tokens.toLocaleString() : '—'}
          sub={data.total_cost > 0 ? `₹${Number(data.total_cost).toFixed(4)}` : null}
          icon={TrendingUp}
          color="bg-amber-600"
        />
      </div>

      {/* Schools table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200">
          <h2 className="text-sm font-semibold text-slate-900">Schools</h2>
        </div>
        {data.schools.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-slate-400">
            No schools yet.{' '}
            <Link href="/superadmin/schools/new" className="text-blue-600 hover:underline">
              Create one
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {data.schools.map(school => (
              <Link
                key={school.id}
                href={`/superadmin/schools/${school.id}`}
                className="flex items-center justify-between px-5 py-3.5 hover:bg-slate-50 transition-colors group"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center text-slate-600 text-sm font-semibold">
                    {school.name.charAt(0)}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-slate-900">{school.name}</p>
                    <p className="text-xs text-slate-400">
                      {school.member_count} member{school.member_count !== 1 ? 's' : ''} · {school.paper_count} paper{school.paper_count !== 1 ? 's' : ''} · {(school.images_generated ?? 0).toLocaleString()} image{school.images_generated !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  {school.monthly_token_budget > 0 && (
                    <span className="text-xs text-slate-400">
                      {school.total_tokens.toLocaleString()} / {school.monthly_token_budget.toLocaleString()} tokens
                    </span>
                  )}
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${school.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                    {school.is_active ? 'Active' : 'Inactive'}
                  </span>
                  <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-slate-500 transition-colors" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
