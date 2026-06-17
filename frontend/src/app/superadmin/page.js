'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { School, Users, FileText, TrendingUp, ChevronRight, Plus } from 'lucide-react';

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
        <Link
          href="/superadmin/schools/new"
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add School
        </Link>
      </div>

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
                      {school.member_count} member{school.member_count !== 1 ? 's' : ''} · {school.paper_count} paper{school.paper_count !== 1 ? 's' : ''}
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
