'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { BarChart3, Users, TrendingUp, DollarSign, Sparkles, Building2, Coins, Receipt, ArrowRight } from 'lucide-react';
import apiClient from '@/lib/api';

const ROLE_BADGE = {
  superadmin: 'bg-amber-100/80 text-amber-700 border border-amber-200/60',
  school_admin: 'bg-violet-100/80 text-violet-700 border border-violet-200/60',
  teacher: 'bg-slate-100/80 text-slate-600 border border-slate-200/60',
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-2xl p-6 text-red-700 text-sm font-semibold text-center max-w-2xl mx-auto mt-10">
        {error}
      </div>
    );
  }

  const totalPapers = rows.reduce((s, r) => s + r.total_papers, 0);
  const totalTokens = rows.reduce((s, r) => s + r.total_tokens, 0);
  const monthlyTokens = rows.reduce((s, r) => s + r.monthly_tokens, 0);

  return (
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col xl:flex-row xl:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-indigo-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Administration</span>
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Team Usage</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">Monitor AI token consumption and paper generation across your organization.</p>
        </div>
        
        {schoolName && (
          <div className="flex items-center gap-3">
            <div className="px-5 py-3 bg-white border border-slate-200 rounded-2xl font-bold text-[13px] flex items-center gap-2 shadow-sm text-slate-700">
              <Building2 size={16} className="text-indigo-500" />
              {schoolName}
            </div>
          </div>
        )}
      </div>

      <div className="max-w-7xl mx-auto space-y-8">
        {/* Summary cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
          {[
            { label: 'Team Members', value: rows.length, icon: Users, color: 'text-indigo-500', bg: 'bg-indigo-50', border: 'border-indigo-100' },
            { label: 'Total Papers', value: totalPapers, icon: TrendingUp, color: 'text-emerald-500', bg: 'bg-emerald-50', border: 'border-emerald-100' },
            { label: 'All-time Tokens', value: totalTokens.toLocaleString(), icon: Coins, color: 'text-amber-500', bg: 'bg-amber-50', border: 'border-amber-100' },
            { label: 'Monthly Tokens', value: monthlyTokens.toLocaleString(), icon: Receipt, color: 'text-blue-500', bg: 'bg-blue-50', border: 'border-blue-100' },
          ].map(({ label, value, icon: Icon, color, bg, border }) => (
            <div key={label} className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:shadow-lg transition-all group">
              <div className="flex items-center gap-3 mb-4">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${bg} border ${border} transition-transform group-hover:scale-110`}>
                  <Icon className={`w-5 h-5 ${color}`} />
                </div>
                <p className="text-[12px] font-bold text-slate-500 uppercase tracking-wider">{label}</p>
              </div>
              <p className="text-[32px] font-extrabold text-slate-900 tracking-tight">{value}</p>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center gap-4 bg-slate-50/50">
            <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center border border-indigo-100">
              <BarChart3 size={20} strokeWidth={2} />
            </div>
            <div>
              <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Usage Breakdown</h2>
              <p className="text-[12px] text-slate-500 font-medium mt-0.5">Detailed metrics per team member</p>
            </div>
          </div>
          
          {rows.length === 0 ? (
            <div className="py-16 text-center">
              <div className="w-16 h-16 bg-slate-50 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-slate-100">
                <Users size={24} className="text-slate-300" strokeWidth={1.5} />
              </div>
              <h3 className="text-[16px] font-bold text-slate-900 mb-1">No usage data found</h3>
              <p className="text-[13px] text-slate-500">Your team members haven't generated any papers yet.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-slate-50/80 text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                  <tr>
                    <th className="px-8 py-5">User Details</th>
                    <th className="px-6 py-5">Role & Access</th>
                    <th title="Papers generated all-time (includes deleted papers)" className="px-6 py-5 text-right">Papers</th>
                    <th className="px-6 py-5 text-right">Total Tokens</th>
                    <th className="px-6 py-5 text-right">Total Cost</th>
                    <th className="px-6 py-5 text-right">Monthly Tokens</th>
                    <th className="px-8 py-5 text-right">Monthly Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50 bg-white/50">
                  {rows.map(r => (
                    <tr key={r.id} className="hover:bg-slate-50/80 transition-colors group">
                      <td className="px-8 py-5">
                        <div className="flex items-center gap-4">
                          <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-[12px] font-extrabold shadow-sm ${r.role === 'superadmin' ? 'bg-amber-100 text-amber-700' : 'bg-indigo-100 text-indigo-700'}`}>
                            {r.username.substring(0, 2).toUpperCase()}
                          </div>
                          <span className="text-[14px] font-bold text-slate-900">{r.username}</span>
                        </div>
                      </td>
                      <td className="px-6 py-5">
                        <div className="flex flex-col items-start gap-2">
                          <span className={`inline-flex px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${ROLE_BADGE[r.role] || ROLE_BADGE.teacher}`}>
                            {r.role === 'school_admin' ? 'School Admin' : r.role === 'superadmin' ? 'Super Admin' : 'Teacher'}
                          </span>
                          {r.allowed_subject ? (
                            <span className="inline-flex px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-indigo-50 text-indigo-600 border border-indigo-100">
                              {r.allowed_subject}
                            </span>
                          ) : (
                            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 italic">Global Access</span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-5 text-right">
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-[15px] font-extrabold text-slate-900">{r.total_papers}</span>
                          {typeof r.current_papers === 'number' && r.current_papers !== r.total_papers && (
                            <span className="text-[11px] font-semibold text-slate-400">{r.current_papers} active</span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-5 text-right font-bold text-slate-700 text-[13px]">{r.total_tokens.toLocaleString()}</td>
                      <td className="px-6 py-5 text-right font-semibold text-slate-500 text-[12px]">₹{Number(r.total_cost).toFixed(4)}</td>
                      <td className="px-6 py-5 text-right font-bold text-slate-700 text-[13px]">{r.monthly_tokens.toLocaleString()}</td>
                      <td className="px-8 py-5 text-right font-semibold text-slate-500 text-[12px]">₹{Number(r.monthly_cost).toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
