'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { BarChart3, Users, TrendingUp, DollarSign } from 'lucide-react';
import apiClient from '@/lib/api';

const ROLE_BADGE = {
  superadmin: 'bg-amber-100 text-amber-700',
  school_admin: 'bg-violet-100 text-violet-700',
  teacher: 'bg-slate-100 text-slate-600',
};

export default function TeamUsagePage() {
  const router = useRouter();
  const [rows, setRows] = useState([]);
  const [schoolName, setSchoolName] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const stored = localStorage.getItem('user');
    if (!stored) { router.replace('/'); return; }
    const user = JSON.parse(stored);
    const role = user?.role;
    if (role !== 'school_admin' && role !== 'superadmin') {
      router.replace('/dashboard');
      return;
    }
    fetchUsage(role, user);
  }, []);

  async function fetchUsage(role, user) {
    try {
      setLoading(true);
      let schoolId;
      if (role === 'school_admin') {
        const mySchoolRes = await apiClient.get('/admin/my-school/');
        schoolId = mySchoolRes.data.id;
      } else {
        // superadmin: read from query param
        const params = new URLSearchParams(window.location.search);
        schoolId = params.get('school');
        if (!schoolId) {
          setError('Superadmin: pass ?school=<id> in the URL');
          setLoading(false);
          return;
        }
      }
      const res = await apiClient.get(`/admin/schools/${schoolId}/user-usage/`);
      setRows(res.data.users || []);
      setSchoolName(res.data.school || '');
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to load team usage');
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
        {error}
      </div>
    );
  }

  const totalPapers = rows.reduce((s, r) => s + r.total_papers, 0);
  const totalTokens = rows.reduce((s, r) => s + r.total_tokens, 0);
  const monthlyTokens = rows.reduce((s, r) => s + r.monthly_tokens, 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-blue-600" />
            Team Usage
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">AI usage breakdown across your team</p>
        </div>
        {schoolName && (
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 border border-blue-200 text-blue-700 text-sm font-medium rounded-lg">
            <Users className="w-3.5 h-3.5" />
            {schoolName}
          </span>
        )}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Team Members', value: rows.length, icon: Users },
          { label: 'Total Papers', value: totalPapers, icon: TrendingUp },
          { label: 'All-time Tokens', value: totalTokens.toLocaleString(), icon: BarChart3 },
          { label: 'Monthly Tokens', value: monthlyTokens.toLocaleString(), icon: DollarSign },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="bg-white border border-slate-200 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1">
              <Icon className="w-4 h-4 text-blue-500" />
              <p className="text-xs text-slate-500">{label}</p>
            </div>
            <p className="text-xl font-semibold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        {rows.length === 0 ? (
          <div className="py-12 text-center text-sm text-slate-400">No usage data available</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Username</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Role</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Subject</th>
                  <th title="Papers generated all-time (includes deleted papers)" className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Papers Generated</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Total Tokens</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Total Cost</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Monthly Tokens</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Monthly Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map(r => (
                  <tr key={r.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-medium text-slate-900">{r.username}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${ROLE_BADGE[r.role] || ROLE_BADGE.teacher}`}>
                        {r.role === 'school_admin' ? 'School Admin' : r.role === 'superadmin' ? 'Super Admin' : 'Teacher'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {r.allowed_subject ? (
                        <span className="inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
                          {r.allowed_subject}
                        </span>
                      ) : (
                        <span className="text-slate-300 text-xs">All</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-700">
                      {r.total_papers}
                      {typeof r.current_papers === 'number' && r.current_papers !== r.total_papers && (
                        <span className="block text-[10px] text-slate-400 font-normal">{r.current_papers} current</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-700">{r.total_tokens.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-slate-500 text-xs">₹{Number(r.total_cost).toFixed(4)}</td>
                    <td className="px-4 py-3 text-right text-slate-700">{r.monthly_tokens.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-slate-500 text-xs">₹{Number(r.monthly_cost).toFixed(4)}</td>
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
