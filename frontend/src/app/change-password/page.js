'use client';

import { useState, useEffect } from 'react';
import { Lock, Loader2, ShieldCheck, ArrowRight } from 'lucide-react';
import apiClient from '@/lib/api';

export default function ChangePasswordPage() {
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState('');   // '' | 'change' | 'skip'
  const [error, setError] = useState(null);

  // Must be logged in to be here; bounce to login otherwise. (No setState in the effect.)
  useEffect(() => {
    if (typeof window !== 'undefined' && !localStorage.getItem('authToken')) {
      window.location.href = '/login';
    }
  }, []);

  // Clear the local first-login flag and move on into the app.
  const finish = () => {
    let role;
    try {
      const s = localStorage.getItem('user');
      if (s) {
        const u = JSON.parse(s);
        u.require_password_change = false;
        localStorage.setItem('user', JSON.stringify(u));
        role = u.role;
      }
    } catch { /* ignore */ }
    window.location.href = role === 'superadmin' ? '/superadmin' : '/dashboard';
  };

  const handleChange = async (e) => {
    e?.preventDefault();
    setError(null);
    if (pw.length < 8) { setError('Password must be at least 8 characters.'); return; }
    if (pw !== confirm) { setError('Passwords do not match.'); return; }
    try {
      setLoading('change');
      await apiClient.post('/auth/first-login-password/', { new_password: pw });
      finish();
    } catch (err) {
      setError(err?.response?.data?.error || 'Could not update password.');
      setLoading('');
    }
  };

  const handleSkip = async () => {
    setError(null);
    try {
      setLoading('skip');
      await apiClient.post('/auth/first-login-password/', { skip: true });
      finish();
    } catch (err) {
      setError(err?.response?.data?.error || 'Could not skip.');
      setLoading('');
    }
  };

  const busy = loading !== '';

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="w-12 h-12 bg-blue-600 rounded-2xl flex items-center justify-center mx-auto mb-3">
            <ShieldCheck className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-xl font-bold text-slate-900">Set a new password</h1>
          <p className="text-sm text-slate-500 mt-1">
            Your account was created by your school admin. Choose your own password.
          </p>
        </div>

        <form onSubmit={handleChange} className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6 space-y-4">
          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{error}</div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">New password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                placeholder="At least 8 characters"
                disabled={busy}
                className="w-full pl-9 pr-3 py-2.5 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Confirm password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Re-enter new password"
                disabled={busy}
                className="w-full pl-9 pr-3 py-2.5 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
          >
            {loading === 'change' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
            Change password
          </button>

          <button
            type="button"
            onClick={handleSkip}
            disabled={busy}
            className="w-full flex items-center justify-center gap-1.5 px-4 py-2 text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors disabled:opacity-50"
          >
            {loading === 'skip' ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Skip for now <ArrowRight className="w-3.5 h-3.5" /></>}
          </button>
        </form>

        <p className="text-center text-xs text-slate-400 mt-4">
          You can change your password anytime later in settings.
        </p>
      </div>
    </div>
  );
}
