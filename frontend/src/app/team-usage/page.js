'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  BarChart3, Users, FileText, TrendingUp,
  Zap, ArrowUpRight, Crown, ChevronUp, ChevronDown,
} from 'lucide-react';
import apiClient from '@/lib/api';

/* ─── helpers ────────────────────────────────────────────────────────────── */

const ROLE_LABEL = { superadmin: 'Super Admin', school_admin: 'Admin', teacher: 'Teacher' };
const ROLE_COLOR = {
  superadmin: 'bg-amber-50 text-amber-700 border-amber-200',
  school_admin: 'bg-violet-50 text-violet-700 border-violet-200',
  teacher: 'bg-slate-50 text-slate-600 border-slate-200',
};

function fmt(n) { return Number(n || 0).toLocaleString('en-IN'); }

/* ─── Plan quota card ────────────────────────────────────────────────────── */

function PlanCard({ school }) {
  if (!school) return null;
  const {
    plan_name, plan_key, papers_this_month, paper_limit, paper_limit_unlimited,
    teacher_count, teacher_limit, teacher_limit_unlimited, is_on_trial, trial_ends_at,
  } = school;

  const paperPct = paper_limit_unlimited ? 0
    : Math.min(100, Math.round((papers_this_month / paper_limit) * 100));
  const teacherPct = teacher_limit_unlimited ? 0
    : Math.min(100, Math.round((teacher_count / teacher_limit) * 100));

  const daysLeft = trial_ends_at
    ? Math.ceil((new Date(trial_ends_at) - Date.now()) / 86400000) : null;

  const barColor = (pct) =>
    pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-400' : 'bg-blue-500';

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-5">
      {/* plan header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-blue-50 border border-blue-100 rounded-lg flex items-center justify-center">
            <Zap className="w-4 h-4 text-blue-600" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900">{plan_name} Plan</p>
            {is_on_trial && daysLeft !== null && (
              <p className={`text-[11px] font-medium ${daysLeft <= 3 ? 'text-red-600' : 'text-amber-600'}`}>
                Trial · {daysLeft > 0 ? `${daysLeft}d left` : 'expired'}
              </p>
            )}
          </div>
        </div>
        <a
          href="/billing"
          className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1.5 rounded-lg transition-colors"
        >
          <ArrowUpRight className="w-3.5 h-3.5" />
          Upgrade
        </a>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Papers */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">Papers this month</span>
            <span className={`font-semibold ${paperPct >= 80 ? 'text-amber-600' : 'text-slate-700'}`}>
              {papers_this_month}{!paper_limit_unlimited && ` / ${paper_limit}`}
            </span>
          </div>
          {!paper_limit_unlimited && (
            <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${barColor(paperPct)}`}
                style={{ width: `${paperPct}%` }}
              />
            </div>
          )}
          {paper_limit_unlimited && (
            <p className="text-[11px] text-slate-400">Unlimited</p>
          )}
        </div>

        {/* Teachers */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">Teachers</span>
            <span className={`font-semibold ${teacherPct >= 80 ? 'text-amber-600' : 'text-slate-700'}`}>
              {teacher_count}{!teacher_limit_unlimited && ` / ${teacher_limit}`}
            </span>
          </div>
          {!teacher_limit_unlimited && (
            <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${barColor(teacherPct)}`}
                style={{ width: `${teacherPct}%` }}
              />
            </div>
          )}
          {teacher_limit_unlimited && (
            <p className="text-[11px] text-slate-400">Unlimited</p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── stat card ─────────────────────────────────────────────────────────── */

function StatCard({ label, value, sub, icon: Icon, accent = 'blue' }) {
  const colors = {
    blue:   'bg-blue-50 text-blue-600',
    green:  'bg-emerald-50 text-emerald-600',
    violet: 'bg-violet-50 text-violet-600',
    amber:  'bg-amber-50 text-amber-600',
  };
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 flex items-start gap-3">
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${colors[accent]}`}>
        <Icon className="w-4 h-4" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-500 truncate">{label}</p>
        <p className="text-xl font-bold text-slate-900 tracking-tight mt-0.5">{value}</p>
        {sub && <p className="text-[11px] text-slate-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

/* ─── inline mini-bar ───────────────────────────────────────────────────── */

function MiniBar({ value, max }) {
  if (!max) return <span className="text-slate-300 text-xs">—</span>;
  const pct = Math.min(100, Math.round((value / max) * 100));
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm font-medium text-slate-800 w-6 text-right">{value}</span>
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden min-w-[40px]">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/* ─── sort hook ─────────────────────────────────────────────────────────── */

function useSorted(rows, defaultKey = 'monthly_papers') {
  const [key, setKey] = useState(defaultKey);
  const [asc, setAsc] = useState(false);

  function toggle(k) {
    if (k === key) setAsc(a => !a);
    else { setKey(k); setAsc(false); }
  }

  const sorted = [...rows].sort((a, b) => {
    const av = a[key] ?? 0, bv = b[key] ?? 0;
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return asc ? cmp : -cmp;
  });

  return { sorted, key, asc, toggle };
}

function SortIcon({ col, activeCol, asc }) {
  if (col !== activeCol) return <ChevronUp className="w-3 h-3 text-slate-300" />;
  return asc
    ? <ChevronUp className="w-3 h-3 text-blue-500" />
    : <ChevronDown className="w-3 h-3 text-blue-500" />;
}

/* ─── main page ─────────────────────────────────────────────────────────── */

export default function TeamUsagePage() {
  const router = useRouter();
  const [rows, setRows] = useState([]);
  const [schoolName, setSchoolName] = useState('');
  const [schoolInfo, setSchoolInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const { sorted, key: sortKey, asc: sortAsc, toggle: sortToggle } = useSorted(rows);

  useEffect(() => {
    const stored = localStorage.getItem('user');
    if (!stored) { router.replace('/login'); return; }
    const user = JSON.parse(stored);
    const role = user?.role;
    if (role !== 'school_admin' && role !== 'superadmin') {
      router.replace('/dashboard'); return;
    }
    fetchAll(role);
  }, []);

  async function fetchAll(role) {
    try {
      setLoading(true);
      let schoolId;
      if (role === 'school_admin') {
        const s = await apiClient.get('/admin/my-school/');
        schoolId = s.data.id;
        setSchoolInfo(s.data);
        setSchoolName(s.data.name || '');
      } else {
        const params = new URLSearchParams(window.location.search);
        schoolId = params.get('school');
        if (!schoolId) { setError('Pass ?school=<id> in the URL'); setLoading(false); return; }
      }
      const r = await apiClient.get(`/admin/schools/${schoolId}/user-usage/`);
      setRows(r.data.users || []);
      if (!schoolName) setSchoolName(r.data.school || '');
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  }

  if (loading) return (
    <div className="flex justify-center items-center py-24">
      <div className="w-5 h-5 border-2 border-slate-200 border-t-blue-600 rounded-full animate-spin" />
    </div>
  );

  if (error) return (
    <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">{error}</div>
  );

  /* ── derived stats ── */
  const totalPapersMonth  = rows.reduce((s, r) => s + (r.monthly_papers || 0), 0);
  const totalPapersAll    = rows.reduce((s, r) => s + r.total_papers, 0);
  const activeTeachers    = rows.filter(r => (r.monthly_papers || 0) > 0).length;
  const maxMonthly        = Math.max(...rows.map(r => r.monthly_papers || 0), 1);
  const topTeacher        = rows.find(r => (r.monthly_papers || 0) === maxMonthly && maxMonthly > 0);

  const now     = new Date();
  const monthLabel = now.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });

  const COLS = [
    { key: 'username',       label: 'Teacher',        align: 'left'  },
    { key: 'monthly_papers', label: 'This Month',     align: 'right' },
    { key: 'total_papers',   label: 'All Time',       align: 'right' },
    { key: 'monthly_cost',   label: 'Monthly Cost',   align: 'right' },
  ];

  return (
    <div className="space-y-6">
      {/* ── header ── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-blue-600" />
            Usage Dashboard
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">{monthLabel} · {schoolName}</p>
        </div>
      </div>

      {/* ── plan card ── */}
      <PlanCard school={schoolInfo} />

      {/* ── stat cards ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Papers This Month"  value={totalPapersMonth} sub="Across all teachers" icon={FileText}   accent="blue"   />
        <StatCard label="Active Teachers"    value={activeTeachers}   sub="Generated ≥1 paper"  icon={Users}      accent="green"  />
        <StatCard label="All-time Papers"    value={fmt(totalPapersAll)} sub="Since account created" icon={TrendingUp} accent="violet" />
        <StatCard label="Team Members"       value={rows.length}      sub="Teachers + admins"   icon={BarChart3}  accent="amber"  />
      </div>

      {/* ── teacher table ── */}
      <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-900">Per-Teacher Breakdown</h2>
          {topTeacher && (
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full">
              <Crown className="w-3 h-3" />
              Most active: {topTeacher.username}
            </span>
          )}
        </div>

        {rows.length === 0 ? (
          <div className="py-16 text-center text-sm text-slate-400">No team members yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/70">
                  {COLS.map(c => (
                    <th
                      key={c.key}
                      onClick={() => sortToggle(c.key)}
                      className={`px-4 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider cursor-pointer select-none hover:text-slate-700 transition-colors
                        ${c.align === 'right' ? 'text-right' : 'text-left'}`}
                    >
                      <span className="inline-flex items-center gap-1">
                        {c.label}
                        <SortIcon col={c.key} activeCol={sortKey} asc={sortAsc} />
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {sorted.map((r, i) => (
                  <tr key={r.id} className="hover:bg-slate-50/60 transition-colors">
                    {/* teacher */}
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className="w-7 h-7 rounded-md bg-blue-600 flex items-center justify-center text-white text-xs font-semibold flex-shrink-0">
                          {r.username.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-slate-900 truncate flex items-center gap-1.5">
                            {r.username}
                            {i === 0 && r.monthly_papers > 0 && (
                              <Crown className="w-3 h-3 text-amber-500 flex-shrink-0" />
                            )}
                          </p>
                          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                            <span className={`inline-flex px-1.5 py-0 rounded text-[10px] font-medium border ${ROLE_COLOR[r.role] || ROLE_COLOR.teacher}`}>
                              {ROLE_LABEL[r.role] || 'Teacher'}
                            </span>
                            {r.allowed_subject && (
                              <span className="text-[10px] text-slate-400">{r.allowed_subject}</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* this month — with mini-bar */}
                    <td className="px-4 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-2 min-w-[90px]">
                        <MiniBar value={r.monthly_papers || 0} max={maxMonthly} />
                      </div>
                    </td>

                    {/* all-time */}
                    <td className="px-4 py-3.5 text-right text-slate-700 tabular-nums">
                      {fmt(r.total_papers)}
                    </td>

                    {/* monthly cost */}
                    <td className="px-4 py-3.5 text-right text-slate-500 text-xs tabular-nums">
                      ₹{Number(r.monthly_cost || 0).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* footer note */}
        <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/50">
          <p className="text-[11px] text-slate-400">
            "All Time" counts generation events and persists even after papers are deleted.
            Costs shown are LLM usage costs, not your subscription price.
          </p>
        </div>
      </div>
    </div>
  );
}
