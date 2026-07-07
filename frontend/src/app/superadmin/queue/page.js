'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { FileText, Clock, CircleDashed, ListOrdered } from 'lucide-react';

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

export default function QueuePage() {
  const router = useRouter();

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') {
      router.replace('/dashboard');
    }
  }, [router]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Queue</h1>
        <p className="text-sm text-slate-500 mt-0.5">Paper generation queue status</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Papers Remaining"
          value="57"
          sub="in queue"
          icon={FileText}
          color="bg-blue-600"
        />
        <StatCard
          label="Estimated Time"
          value="17 hrs"
          sub="to complete"
          icon={Clock}
          color="bg-amber-600"
        />
        <StatCard
          label="Status"
          value="Not Started"
          icon={CircleDashed}
          color="bg-slate-500"
        />
      </div>

      {/* Queue summary card */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center gap-2">
          <ListOrdered className="w-4 h-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-900">Queue Overview</h2>
        </div>
        <div className="px-5 py-4 space-y-4">
          <div>
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="text-slate-600">Progress</span>
              <span className="text-slate-400">0 / 57 papers</span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-2">
              <div className="bg-blue-600 h-2 rounded-full" style={{ width: '0%' }} />
            </div>
          </div>
          <div className="flex items-center justify-between text-sm py-2 border-t border-slate-100">
            <span className="text-slate-600">Current status</span>
            <span className="inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-500">
              Not Started
            </span>
          </div>
          <div className="flex items-center justify-between text-sm py-2 border-t border-slate-100">
            <span className="text-slate-600">Papers remaining</span>
            <span className="font-medium text-slate-900">57</span>
          </div>
          <div className="flex items-center justify-between text-sm py-2 border-t border-slate-100">
            <span className="text-slate-600">Estimated time to complete</span>
            <span className="font-medium text-slate-900">17 hrs</span>
          </div>
        </div>
      </div>
    </div>
  );
}
