'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { FileText, Clock, CircleDashed, ListOrdered, Sparkles } from 'lucide-react';

function StatCard({ label, value, sub, icon: Icon, colorClass, bgClass, iconColorClass }) {
  return (
    <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[24px] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:shadow-lg transition-shadow relative overflow-hidden group">
      {/* Decorative gradient overlay */}
      <div className={`absolute top-0 right-0 w-32 h-32 opacity-10 rounded-bl-full transition-transform group-hover:scale-110 ${bgClass}`} />
      
      <div className="flex items-start justify-between relative z-10">
        <div>
          <p className="text-[12px] font-bold text-slate-500 uppercase tracking-wider mb-2">{label}</p>
          <p className={`text-[32px] font-extrabold tracking-tight ${colorClass}`}>{value}</p>
          {sub && <p className="text-[12px] font-semibold text-slate-400 mt-1">{sub}</p>}
        </div>
        <div className={`w-14 h-14 rounded-2xl flex items-center justify-center ${bgClass} ${iconColorClass} shadow-sm`}>
          <Icon size={24} />
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
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
          <Sparkles size={14} className="text-amber-500" strokeWidth={2} />
          <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">System Monitor</span>
        </div>
        <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Generation Queue</h1>
        <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">
          Monitor the status of global paper generation tasks.
        </p>
      </div>

      <div className="max-w-7xl mx-auto space-y-8">
        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <StatCard
            label="Papers Remaining"
            value="57"
            sub="Currently in queue"
            icon={FileText}
            colorClass="text-indigo-900"
            bgClass="bg-indigo-50"
            iconColorClass="text-indigo-600"
          />
          <StatCard
            label="Estimated Time"
            value="17 hrs"
            sub="To complete all tasks"
            icon={Clock}
            colorClass="text-amber-900"
            bgClass="bg-amber-50"
            iconColorClass="text-amber-600"
          />
          <StatCard
            label="Worker Status"
            value="Idle"
            sub="Waiting to start"
            icon={CircleDashed}
            colorClass="text-slate-900"
            bgClass="bg-slate-100"
            iconColorClass="text-slate-500"
          />
        </div>

        {/* Queue summary card */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[32px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)] max-w-3xl">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center gap-4 bg-slate-50/50">
            <div className="w-12 h-12 bg-white border border-slate-200 rounded-2xl flex items-center justify-center text-slate-500 shadow-sm">
              <ListOrdered size={20} strokeWidth={2} />
            </div>
            <div>
              <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Queue Overview</h2>
              <p className="text-[12px] text-slate-500 font-medium mt-0.5">Real-time progress of batch generations</p>
            </div>
          </div>
          <div className="p-8 space-y-8">
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[14px] font-bold text-slate-700">Batch Progress</span>
                <span className="text-[13px] font-extrabold text-indigo-600">0 / 57 papers</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-3 overflow-hidden">
                <div className="bg-indigo-600 h-full rounded-full w-[2%]" />
              </div>
            </div>
            
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-slate-50 rounded-2xl border border-slate-100">
                <span className="text-[13px] font-bold text-slate-600">Current status</span>
                <span className="inline-flex px-3 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider bg-slate-200/50 text-slate-600 border border-slate-300/50">
                  Not Started
                </span>
              </div>
              <div className="flex items-center justify-between p-4 bg-slate-50 rounded-2xl border border-slate-100">
                <span className="text-[13px] font-bold text-slate-600">Papers remaining</span>
                <span className="text-[16px] font-extrabold text-slate-900">57</span>
              </div>
              <div className="flex items-center justify-between p-4 bg-slate-50 rounded-2xl border border-slate-100">
                <span className="text-[13px] font-bold text-slate-600">Estimated time to complete</span>
                <span className="text-[16px] font-extrabold text-slate-900">17 hrs</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
