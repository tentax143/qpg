'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import {
  ClipboardList, Search, ChevronDown, ChevronRight,
  RefreshCw, CheckCircle, XCircle, Loader2, BookOpen, Sparkles
} from 'lucide-react';

const CLASS_ORDER = ['6', '7', '8', '9', '10', '11', '12'];

function SectionRow({ sec }) {
  const isCompound = Boolean(sec.subject);
  // Support both old field names and new compound-subject field names
  const hotsCount = sec.hots ?? sec.hots_count ?? 0;
  const cbqCount = sec.cbq ?? sec.competency_based_count ?? 0;
  const choiceCount = sec.choices ?? sec.internal_choice_count ?? null;
  const notesText = sec.notes || (
    Array.isArray(sec.question_types)
      ? sec.question_types.map(qt => typeof qt === 'string' ? qt : qt.type).join(', ')
      : ''
  ) || '—';

  return (
    <tr className={`border-b border-slate-100 last:border-0 text-[12px] hover:bg-slate-50/80 transition-colors group ${isCompound ? 'bg-indigo-50/30' : ''}`}>
      <td className="px-5 py-3 font-bold text-slate-800 whitespace-nowrap">§ {sec.name}</td>
      <td className="px-5 py-3">
        {isCompound
          ? <span className="font-extrabold text-indigo-700">{sec.subject}</span>
          : <span className="text-slate-600 font-semibold">{sec.title || '—'}</span>}
      </td>
      <td className="px-5 py-3 text-center font-mono font-medium text-slate-700">{sec.questions ?? sec.questions_count ?? 0}</td>
      <td className="px-5 py-3 text-center font-mono font-medium text-slate-700">{sec.marks_each ?? (isCompound ? 'Varies' : '—')}</td>
      <td className="px-5 py-3 text-center font-mono font-extrabold text-indigo-600">{sec.marks}</td>
      <td className="px-5 py-3 text-center">
        {sec.internal_choice
          ? <span className="text-[10px] bg-amber-50 text-amber-700 border border-amber-200/50 rounded-lg px-2 py-1 font-bold uppercase tracking-wider">Yes {choiceCount ? `(${choiceCount})` : ''}</span>
          : <span className="text-slate-300 font-bold">—</span>}
      </td>
      <td className="px-5 py-3 text-slate-500 font-semibold">
        {[
          hotsCount ? `${hotsCount} HOTS` : null,
          cbqCount ? `${cbqCount} CBQ` : null,
        ].filter(Boolean).join(' · ') || '—'}
      </td>
      <td className="px-5 py-3 text-slate-400 font-medium max-w-[200px] truncate" title={notesText}>{notesText}</td>
    </tr>
  );
}

function PatternCard({ pattern, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen || false);
  const sections = pattern.sections || [];

  return (
    <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[24px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)] transition-all">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex flex-col md:flex-row md:items-center justify-between px-6 py-5 hover:bg-slate-50/80 transition-colors text-left gap-4"
      >
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 bg-indigo-50 border border-indigo-100 rounded-2xl flex items-center justify-center text-indigo-700 text-[16px] font-extrabold shadow-sm shrink-0">
            {pattern.class_name}
          </div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h3 className="text-[16px] font-extrabold text-slate-900 tracking-tight">{pattern.subject}</h3>
              {pattern.sqp_year && (
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200/50 uppercase tracking-wider">
                  {pattern.sqp_year}
                </span>
              )}
            </div>
            <p className="text-[13px] font-medium text-slate-500">{pattern.name}</p>
          </div>
        </div>
        <div className="flex items-center gap-6 justify-between md:justify-end">
          <div className="text-right">
            <p className="text-[18px] font-extrabold text-slate-900 tracking-tight">{pattern.total_marks}M</p>
            <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">{pattern.total_questions} Qs</p>
          </div>
          <div className="flex items-center gap-3 border-l border-slate-200 pl-6">
            <span className="text-[12px] font-bold text-slate-500">{sections.length} sections</span>
            <div className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${open ? 'bg-indigo-50 text-indigo-600' : 'bg-slate-50 text-slate-400'}`}>
              {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </div>
          </div>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-100 bg-white overflow-x-auto">
          {sections.length === 0 ? (
            <p className="px-6 py-8 text-center text-[13px] font-bold text-slate-400">No section data available</p>
          ) : (
            <table className="w-full text-left min-w-[800px]">
              <thead className="bg-slate-50/80 text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                <tr>
                  <th className="px-5 py-4">Section</th>
                  <th className="px-5 py-4">Title</th>
                  <th className="px-5 py-4 text-center">Questions</th>
                  <th className="px-5 py-4 text-center">Marks/Q</th>
                  <th className="px-5 py-4 text-center">Total Marks</th>
                  <th className="px-5 py-4 text-center">Choice</th>
                  <th className="px-5 py-4">Blueprint</th>
                  <th className="px-5 py-4">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {sections.map((sec, i) => <SectionRow key={i} sec={sec} />)}
              </tbody>
              <tfoot className="bg-slate-50/50 border-t-2 border-slate-100">
                <tr>
                  <td colSpan={4} className="px-5 py-4 text-[13px] text-slate-500 font-extrabold text-right">Total</td>
                  <td className="px-5 py-4 text-center text-[15px] font-extrabold text-indigo-700">{pattern.total_marks}M</td>
                  <td colSpan={3} />
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

export default function CbsePatternsPage() {
  const router = useRouter();
  const [patterns, setPatterns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [classFilter, setClassFilter] = useState('all');

  // Update state
  const [updating, setUpdating] = useState(false);
  const [updateProgress, setUpdateProgress] = useState({ current: 0, total: 0, current_subject: '', results: [] });
  const [updateDone, setUpdateDone] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') { router.replace('/dashboard'); return; }
    fetchPatterns();
  }, [router]);

  async function fetchPatterns() {
    setLoading(true);
    try {
      const r = await apiClient.get('/admin/cbse-patterns/');
      setPatterns(r.data.patterns || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function handleUpdate() {
    setUpdating(true);
    setUpdateDone(false);
    setUpdateProgress({ current: 0, total: 0, current_subject: 'Starting…', results: [] });
    try {
      const r = await apiClient.post('/admin/cbse-patterns/update/', {
        classes: classFilter !== 'all' ? [classFilter] : null,
      });
      const taskId = r.data.task_id;
      pollRef.current = setInterval(async () => {
        try {
          const s = await apiClient.get(`/admin/cbse-patterns/status/${taskId}/`);
          const d = s.data;
          setUpdateProgress({ current: d.current, total: d.total, current_subject: d.current_subject || '', results: d.results || [] });
          if (d.state === 'done') {
            stopPolling();
            setUpdating(false);
            setUpdateDone(true);
            fetchPatterns(); // reload with fresh data
          }
          if (d.state === 'error') { stopPolling(); setUpdating(false); }
        } catch { stopPolling(); setUpdating(false); }
      }, 2000);
    } catch (e) {
      setUpdating(false);
      alert(e.response?.data?.error || 'Failed to start update');
    }
  }

  const filtered = patterns.filter(p => {
    const matchClass = classFilter === 'all' || p.class_name === classFilter;
    const q = search.toLowerCase();
    const matchSearch = !q || p.subject.toLowerCase().includes(q) || p.name.toLowerCase().includes(q);
    return matchClass && matchSearch;
  });

  // Group by class
  const grouped = CLASS_ORDER.reduce((acc, cls) => {
    const items = filtered.filter(p => p.class_name === cls);
    if (items.length) acc[cls] = items;
    return acc;
  }, {});

  const updatedIds = new Set(updateProgress.results.filter(r => r.status === 'updated').map(r => r.id));
  const errorIds = new Set(updateProgress.results.filter(r => r.status === 'error').map(r => r.id));
  const skippedIds = new Set(updateProgress.results.filter(r => r.status === 'skipped').map(r => r.id));

  return (
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col lg:flex-row lg:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-amber-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Global Master Data</span>
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">CBSE Patterns</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">
            {patterns.length} official patterns synced · Academic year 2025-26
          </p>
        </div>
        
        <button
          onClick={handleUpdate}
          disabled={updating}
          className="px-6 py-3.5 bg-slate-900 hover:bg-slate-800 disabled:opacity-60 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-slate-200/50 transition-all flex items-center justify-center gap-2 active:scale-[0.98] shrink-0"
        >
          {updating ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          {updating ? `Updating ${updateProgress.current}/${updateProgress.total}…` : 'Fetch Latest Patterns'}
        </button>
      </div>

      <div className="max-w-7xl mx-auto space-y-8">
        {/* Progress bar while updating */}
        {updating && (
          <div className="bg-indigo-50 border border-indigo-200/60 rounded-2xl p-6 shadow-sm animate-in fade-in zoom-in duration-300">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[14px] font-bold text-indigo-700">{updateProgress.current_subject || 'Initialising API…'}</span>
              <span className="text-[13px] font-extrabold text-indigo-500">{updateProgress.current}/{updateProgress.total}</span>
            </div>
            <div className="w-full bg-indigo-100 rounded-full h-2 mb-2 overflow-hidden">
              <div
                className="bg-indigo-600 h-full rounded-full transition-all duration-500"
                style={{ width: updateProgress.total ? `${(updateProgress.current / updateProgress.total) * 100}%` : '2%' }}
              />
            </div>
            <p className="text-[11px] font-bold text-indigo-400 uppercase tracking-wider">Powered by DeepSeek V3.2</p>
          </div>
        )}

        {updateDone && (
          <div className="flex items-center gap-3 bg-emerald-50 border border-emerald-200/60 rounded-2xl p-6 shadow-sm text-emerald-700 animate-in fade-in zoom-in duration-300">
            <div className="w-10 h-10 bg-emerald-100 text-emerald-600 flex items-center justify-center rounded-xl shrink-0">
              <CheckCircle size={20} />
            </div>
            <div>
              <p className="text-[14px] font-bold">Sync Completed Successfully</p>
              <p className="text-[12px] font-medium text-emerald-600/80 mt-0.5">
                Updated: {updateProgress.results.filter(r => r.status === 'updated').length} · 
                Skipped: {updateProgress.results.filter(r => r.status === 'skipped').length} (already 2025-26) · 
                Errors: {updateProgress.results.filter(r => r.status === 'error').length}
              </p>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-4 shadow-[0_8px_30px_rgb(0,0,0,0.04)] flex flex-col md:flex-row items-center gap-4 relative z-50">
          <div className="relative flex-1 w-full">
            <Search className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="text"
              placeholder="Search by subject or name..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-12 pr-6 py-4 bg-slate-50/50 border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 transition-shadow"
            />
          </div>
          <div className="flex items-center gap-2 bg-slate-50 p-2 rounded-2xl border border-slate-100 overflow-x-auto w-full md:w-auto">
            {['all', '6', '7', '8', '9', '10', '11', '12'].map(cls => (
              <button
                key={cls}
                onClick={() => setClassFilter(cls)}
                className={`px-4 py-2.5 rounded-xl text-[12px] font-bold transition-all whitespace-nowrap ${
                  classFilter === cls ? 'bg-white text-indigo-700 shadow-sm border border-slate-200/50' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
                }`}
              >
                {cls === 'all' ? 'All Classes' : `Class ${cls}`}
              </button>
            ))}
          </div>
        </div>

        {/* Pattern list */}
        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-20">
            <ClipboardList className="w-16 h-16 text-slate-300 mx-auto mb-4" />
            <h3 className="text-[16px] font-bold text-slate-900 mb-1">No patterns found</h3>
            <p className="text-[13px] text-slate-500">Try adjusting your filters or search terms.</p>
          </div>
        ) : (
          <div className="space-y-12">
            {Object.entries(grouped).map(([cls, items]) => (
              <div key={cls} className="space-y-4">
                <div className="flex items-center gap-3 px-2">
                  <div className="w-8 h-8 bg-indigo-50 rounded-lg flex items-center justify-center text-indigo-600">
                    <BookOpen size={16} />
                  </div>
                  <div>
                    <h2 className="text-[14px] font-extrabold text-slate-900 tracking-tight">Class {cls}</h2>
                    <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">{items.length} Subjects</p>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-4">
                  {items.map(p => (
                    <div key={p.id} className="relative">
                      {updatedIds.has(p.id) && (
                        <span className="absolute right-6 top-6 z-10 inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200/50 rounded-lg uppercase tracking-wider">
                          <CheckCircle size={12} /> Updated
                        </span>
                      )}
                      {skippedIds.has(p.id) && (
                        <span className="absolute right-6 top-6 z-10 inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold text-slate-500 bg-slate-50 border border-slate-200/50 rounded-lg uppercase tracking-wider">
                          Already 2025-26
                        </span>
                      )}
                      {errorIds.has(p.id) && (
                        <span className="absolute right-6 top-6 z-10 inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold text-red-700 bg-red-50 border border-red-200/50 rounded-lg uppercase tracking-wider">
                          <XCircle size={12} /> Sync Error
                        </span>
                      )}
                      <PatternCard pattern={p} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
