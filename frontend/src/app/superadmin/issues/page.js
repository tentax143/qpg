'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { Bug, Trash2, Check, X } from 'lucide-react';

// Status workflow: open → investigating → fixing → fixed.
const STATUSES = [
  { value: 'open', label: 'Open', cls: 'bg-slate-100 text-slate-600' },
  { value: 'investigating', label: 'Investigating', cls: 'bg-amber-50 text-amber-700' },
  { value: 'fixing', label: 'Fixing', cls: 'bg-blue-50 text-blue-700' },
  { value: 'fixed', label: 'Fixed', cls: 'bg-emerald-50 text-emerald-700' },
];
const STATUS_MAP = Object.fromEntries(STATUSES.map((s) => [s.value, s]));

const FILTERS = [{ value: 'all', label: 'All' }, ...STATUSES];

export default function SuperadminIssuesPage() {
  const router = useRouter();
  const [issues, setIssues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [savingId, setSavingId] = useState(null);
  // Per-issue draft of the admin note (keyed by issue id).
  const [noteDrafts, setNoteDrafts] = useState({});

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') {
      router.replace('/dashboard');
      return;
    }
    fetchIssues();
  }, [router]);

  async function fetchIssues() {
    try {
      const r = await apiClient.get('/issues/');
      const list = r.data.results || r.data || [];
      setIssues(list);
      setNoteDrafts(Object.fromEntries(list.map((i) => [i.id, i.admin_note || ''])));
      setError(null);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load issues');
    } finally {
      setLoading(false);
    }
  }

  async function updateIssue(id, payload) {
    try {
      setSavingId(id);
      await apiClient.patch(`/issues/${id}/`, payload);
      await fetchIssues();
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to update issue');
    } finally {
      setSavingId(null);
    }
  }

  async function deleteIssue(id) {
    if (!confirm('Delete this issue permanently?')) return;
    try {
      setSavingId(id);
      await apiClient.delete(`/issues/${id}/`);
      await fetchIssues();
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to delete issue');
    } finally {
      setSavingId(null);
    }
  }

  const shown = filter === 'all' ? issues : issues.filter((i) => i.status === filter);
  const counts = STATUSES.reduce((acc, s) => {
    acc[s.value] = issues.filter((i) => i.status === s.value).length;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Issues</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Problems reported by users. Update the status and leave a reply the reporter can see.
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const active = filter === f.value;
          const count = f.value === 'all' ? issues.length : (counts[f.value] || 0);
          return (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                active ? 'bg-blue-600 text-white' : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {f.label}
              <span className={`text-[11px] ${active ? 'text-blue-100' : 'text-slate-400'}`}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* Issue list */}
      {loading ? (
        <div className="flex justify-center py-10">
          <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
        </div>
      ) : shown.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center text-sm text-slate-500 shadow-sm">
          <Bug className="w-6 h-6 text-slate-300 mx-auto mb-2" />
          No issues {filter === 'all' ? 'reported yet' : `with status "${STATUS_MAP[filter]?.label}"`}.
        </div>
      ) : (
        <div className="space-y-3">
          {shown.map((issue) => {
            const s = STATUS_MAP[issue.status] || STATUS_MAP.open;
            const reporter = issue.created_by;
            const noteChanged = (noteDrafts[issue.id] ?? '') !== (issue.admin_note || '');
            return (
              <div key={issue.id} className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-semibold text-slate-900">{issue.title}</p>
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${s.cls}`}>{s.label}</span>
                    </div>
                    <p className="text-sm text-slate-600 mt-1.5 whitespace-pre-wrap break-words">{issue.description}</p>
                    <p className="text-[11px] text-slate-400 mt-2">
                      {reporter ? (reporter.first_name || reporter.last_name
                        ? `${reporter.first_name} ${reporter.last_name}`.trim()
                        : reporter.username) : 'Unknown'}
                      {issue.school_name ? ` · ${issue.school_name}` : ''}
                      {' · '}{new Date(issue.created_at).toLocaleString()}
                    </p>
                  </div>
                  <button
                    onClick={() => deleteIssue(issue.id)}
                    disabled={savingId === issue.id}
                    className="flex-shrink-0 text-slate-400 hover:text-red-600 transition-colors disabled:opacity-50"
                    title="Delete issue"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                {/* Status controls */}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mr-1">Set status</span>
                  {STATUSES.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => opt.value !== issue.status && updateIssue(issue.id, { status: opt.value })}
                      disabled={savingId === issue.id || opt.value === issue.status}
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
                        opt.value === issue.status
                          ? `${opt.cls} border-transparent cursor-default`
                          : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
                      }`}
                    >
                      {opt.value === issue.status && <Check className="w-3 h-3" />}
                      {opt.label}
                    </button>
                  ))}
                </div>

                {/* Admin note / reply */}
                <div className="mt-3">
                  <label className="block text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1">
                    Reply to reporter
                  </label>
                  <textarea
                    rows={2}
                    placeholder="Optional note the reporter will see (e.g. Fixed in today's release)"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm resize-y"
                    value={noteDrafts[issue.id] ?? ''}
                    onChange={(e) => setNoteDrafts((p) => ({ ...p, [issue.id]: e.target.value }))}
                  />
                  {noteChanged && (
                    <div className="mt-2 flex gap-2">
                      <button
                        onClick={() => updateIssue(issue.id, { admin_note: noteDrafts[issue.id] })}
                        disabled={savingId === issue.id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-xs font-medium rounded-lg transition-colors"
                      >
                        <Check className="w-3.5 h-3.5" /> Save reply
                      </button>
                      <button
                        onClick={() => setNoteDrafts((p) => ({ ...p, [issue.id]: issue.admin_note || '' }))}
                        disabled={savingId === issue.id}
                        className="px-3 py-1.5 bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 text-xs font-medium rounded-lg transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
