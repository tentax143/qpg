'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Bug, Send } from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

// Status pill styling shared with the superadmin view: open → slate, investigating →
// amber, fixing → blue, fixed → emerald.
const STATUS_STYLES = {
  open: { label: 'Open', cls: 'bg-slate-100 text-slate-600' },
  investigating: { label: 'Investigating', cls: 'bg-amber-50 text-amber-700' },
  fixing: { label: 'Fixing', cls: 'bg-blue-50 text-blue-700' },
  fixed: { label: 'Fixed', cls: 'bg-emerald-50 text-emerald-700' },
};

function StatusPill({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.open;
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${s.cls}`}>
      {s.label}
    </span>
  );
}

export default function ReportIssuePage() {
  const router = useRouter();
  const [form, setForm] = useState({ title: '', description: '' });
  const [issues, setIssues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const fetchIssues = async () => {
    try {
      const res = await apiClient.get('/issues/');
      setIssues(res.data.results || res.data || []);
    } catch (err) {
      setError('Could not load your reported issues.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const token = localStorage.getItem('authToken');
    if (!token) { router.push('/'); return; }
    fetchIssues();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!form.title.trim() || !form.description.trim()) {
      setError('Please enter both a title and a description.');
      return;
    }
    try {
      setSubmitting(true);
      await apiClient.post('/issues/', {
        title: form.title.trim(),
        description: form.description.trim(),
      });
      setForm({ title: '', description: '' });
      setSuccess('Thanks! Your issue has been reported. You can track its status below.');
      fetchIssues();
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not submit your issue. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Report an Issue</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Something not working? Tell us what happened and we&apos;ll look into it.
        </p>
      </div>

      {/* Report form */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm max-w-2xl">
        {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-4" />}
        {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-4" />}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Title</label>
            <input
              type="text"
              maxLength={200}
              placeholder="e.g. Paper header is cut off on the second page"
              className="w-full px-3.5 py-2.5 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              value={form.title}
              onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Description</label>
            <textarea
              rows={5}
              placeholder="What were you doing, what did you expect, and what happened instead?"
              className="w-full px-3.5 py-2.5 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm resize-y"
              value={form.description}
              onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
              required
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="inline-flex items-center gap-2 py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {submitting ? (
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            {submitting ? 'Submitting...' : 'Submit issue'}
          </button>
        </form>
      </div>

      {/* My reported issues */}
      <div>
        <h2 className="text-sm font-semibold text-slate-900 mb-3">Your reported issues</h2>
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
          </div>
        ) : issues.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-2xl p-8 text-center text-sm text-slate-500 shadow-sm">
            <Bug className="w-6 h-6 text-slate-300 mx-auto mb-2" />
            You haven&apos;t reported any issues yet.
          </div>
        ) : (
          <div className="space-y-3">
            {issues.map((issue) => (
              <div key={issue.id} className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900">{issue.title}</p>
                    <p className="text-sm text-slate-600 mt-1 whitespace-pre-wrap break-words">{issue.description}</p>
                  </div>
                  <StatusPill status={issue.status} />
                </div>
                {issue.admin_note && (
                  <div className="mt-3 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2">
                    <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-0.5">Admin reply</p>
                    <p className="text-sm text-slate-700 whitespace-pre-wrap break-words">{issue.admin_note}</p>
                  </div>
                )}
                <p className="text-[11px] text-slate-400 mt-2">
                  Reported {new Date(issue.created_at).toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
