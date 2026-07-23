'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { Activity, LogOut, MessageSquare, RefreshCw, Send, X, Check } from 'lucide-react';

const STATUS = {
  online: { label: 'Online', dot: 'bg-emerald-500', text: 'text-emerald-600', ring: 'ring-emerald-500/30' },
  idle: { label: 'Idle', dot: 'bg-amber-500', text: 'text-amber-600', ring: 'ring-amber-500/30' },
  away: { label: 'Away', dot: 'bg-slate-400', text: 'text-slate-500', ring: 'ring-slate-400/30' },
  unknown: { label: 'No activity yet', dot: 'bg-slate-300', text: 'text-slate-400', ring: 'ring-slate-300/30' },
};

const ROLE_LABELS = { superadmin: 'Super Admin', school_admin: 'School Admin', teacher: 'Teacher' };

const LEVELS = [
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'success', label: 'Success' },
];

function relativeSeen(seconds) {
  if (seconds === null || seconds === undefined) return 'never';
  if (seconds < 15) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function ActiveUsersPage() {
  const router = useRouter();
  const [users, setUsers] = useState([]);
  const [counts, setCounts] = useState({ online: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  // Per-user message composer state: { [userId]: { open, body, level } }.
  const [composer, setComposer] = useState({});
  const [flash, setFlash] = useState(null);

  const fetchUsers = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const r = await apiClient.get('/admin/active-users/');
      setUsers(r.data.users || []);
      setCounts({ online: r.data.online_count || 0, total: r.data.total_logged_in || 0 });
      setError(null);
    } catch (e) {
      setError(e.response?.data?.detail || e.response?.data?.error || 'Failed to load active users');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') {
      router.replace('/dashboard');
      return;
    }
    fetchUsers();
    const interval = setInterval(() => fetchUsers(), 15000);
    return () => clearInterval(interval);
  }, [router, fetchUsers]);

  function showFlash(msg) {
    setFlash(msg);
    setTimeout(() => setFlash((c) => (c === msg ? null : c)), 4000);
  }

  async function forceLogout(u) {
    if (!confirm(`Force-log-out ${u.username}? They'll be returned to the login screen within a few seconds.`)) return;
    try {
      setBusyId(u.id);
      await apiClient.post('/admin/force-logout/', { user_id: u.id });
      showFlash(`${u.username} has been logged out.`);
      await fetchUsers(true);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to log the user out');
    } finally {
      setBusyId(null);
    }
  }

  function toggleComposer(id) {
    setComposer((prev) => ({
      ...prev,
      [id]: prev[id]?.open ? { ...prev[id], open: false } : { open: true, body: '', level: 'info' },
    }));
  }

  function updateComposer(id, patch) {
    setComposer((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function sendMessage(u) {
    const c = composer[u.id];
    if (!c || !c.body.trim()) return;
    try {
      setBusyId(u.id);
      await apiClient.post('/admin/send-message/', {
        user_id: u.id,
        body: c.body.trim(),
        level: c.level || 'info',
      });
      setComposer((prev) => ({ ...prev, [u.id]: { open: false, body: '', level: 'info' } }));
      showFlash(`Message sent to ${u.username}.`);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to send the message');
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
            <Activity className="w-5 h-5 text-blue-600" />
            Active Users
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Everyone currently signed in. Log a user out or send them a message — updates every 15s.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-3 text-sm">
            <span className="inline-flex items-center gap-1.5 text-slate-600">
              <span className="w-2 h-2 rounded-full bg-emerald-500" /> {counts.online} online
            </span>
            <span className="text-slate-300">·</span>
            <span className="text-slate-600">{counts.total} signed in</span>
          </div>
          <button
            onClick={() => fetchUsers(true)}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 text-sm font-medium rounded-lg transition-colors disabled:opacity-60"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {flash && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm rounded-lg px-4 py-3">
          {flash}
        </div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* List */}
      {loading ? (
        <div className="flex justify-center py-10">
          <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
        </div>
      ) : users.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center text-sm text-slate-500 shadow-sm">
          <Activity className="w-6 h-6 text-slate-300 mx-auto mb-2" />
          No users are currently signed in.
        </div>
      ) : (
        <div className="space-y-3">
          {users.map((u) => {
            const s = STATUS[u.status] || STATUS.unknown;
            const c = composer[u.id];
            return (
              <div key={u.id} className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div className="flex items-start gap-3 min-w-0">
                    {/* Avatar with status ring */}
                    <div className={`relative w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-600 font-semibold ring-2 ${s.ring} flex-shrink-0`}>
                      {(u.username || '?').charAt(0).toUpperCase()}
                      <span className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ${s.dot}`} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-semibold text-slate-900">
                          {u.full_name || u.username}
                        </p>
                        {u.is_you && (
                          <span className="inline-flex px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-50 text-blue-700">You</span>
                        )}
                        <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${s.text}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} /> {s.label}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5">
                        @{u.username} · {ROLE_LABELS[u.role] || u.role}
                        {u.school_name ? ` · ${u.school_name}` : ''}
                      </p>
                      <p className="text-[11px] text-slate-400 mt-1">
                        Last active {relativeSeen(u.seconds_since_seen)}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleComposer(u.id)}
                      disabled={busyId === u.id}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 text-xs font-medium rounded-lg transition-colors disabled:opacity-60"
                    >
                      <MessageSquare className="w-3.5 h-3.5" /> Message
                    </button>
                    {!u.is_you && (
                      <button
                        onClick={() => forceLogout(u)}
                        disabled={busyId === u.id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-red-50 border border-red-200 text-red-600 hover:bg-red-100 text-xs font-medium rounded-lg transition-colors disabled:opacity-60"
                      >
                        <LogOut className="w-3.5 h-3.5" /> Force logout
                      </button>
                    )}
                  </div>
                </div>

                {/* Message composer */}
                {c?.open && (
                  <div className="mt-4 border-t border-slate-100 pt-4">
                    <textarea
                      rows={2}
                      autoFocus
                      placeholder={`Message to ${u.username}… (they'll see it in the top-right corner)`}
                      className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm resize-y"
                      value={c.body}
                      onChange={(e) => updateComposer(u.id, { body: e.target.value })}
                    />
                    <div className="mt-2 flex items-center gap-2 flex-wrap">
                      <div className="flex items-center gap-1">
                        {LEVELS.map((lv) => (
                          <button
                            key={lv.value}
                            onClick={() => updateComposer(u.id, { level: lv.value })}
                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
                              (c.level || 'info') === lv.value
                                ? 'bg-blue-600 text-white border-transparent'
                                : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
                            }`}
                          >
                            {(c.level || 'info') === lv.value && <Check className="w-3 h-3" />}
                            {lv.label}
                          </button>
                        ))}
                      </div>
                      <div className="flex-1" />
                      <button
                        onClick={() => sendMessage(u)}
                        disabled={busyId === u.id || !c.body?.trim()}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium rounded-lg transition-colors"
                      >
                        <Send className="w-3.5 h-3.5" /> Send
                      </button>
                      <button
                        onClick={() => toggleComposer(u.id)}
                        disabled={busyId === u.id}
                        className="px-3 py-1.5 bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 text-xs font-medium rounded-lg transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
