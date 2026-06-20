'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import {
  ClipboardList, Search, ChevronDown, ChevronRight,
  RefreshCw, CheckCircle, XCircle, Loader2, BookOpen,
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
    <tr className={`border-b border-slate-100 last:border-0 text-xs ${isCompound ? 'bg-blue-50/30' : ''}`}>
      <td className="px-3 py-2 font-semibold text-slate-800 whitespace-nowrap">§ {sec.name}</td>
      <td className="px-3 py-2">
        {isCompound
          ? <span className="font-bold text-blue-800">{sec.subject}</span>
          : <span className="text-slate-600">{sec.title || '—'}</span>}
      </td>
      <td className="px-3 py-2 text-center font-mono text-slate-700">{sec.questions ?? sec.questions_count ?? 0}</td>
      <td className="px-3 py-2 text-center font-mono text-slate-700">{sec.marks_each ?? (isCompound ? 'Varies' : '—')}</td>
      <td className="px-3 py-2 text-center font-mono font-semibold text-blue-700">{sec.marks}</td>
      <td className="px-3 py-2 text-center">
        {sec.internal_choice
          ? <span className="text-[10px] bg-amber-50 text-amber-700 border border-amber-200 rounded px-1.5 py-0.5">Yes {choiceCount ? `(${choiceCount})` : ''}</span>
          : <span className="text-slate-300 text-[10px]">—</span>}
      </td>
      <td className="px-3 py-2 text-slate-500 text-[11px]">
        {[
          hotsCount ? `${hotsCount} HOTS` : null,
          cbqCount ? `${cbqCount} CBQ` : null,
        ].filter(Boolean).join(' · ') || '—'}
      </td>
      <td className="px-3 py-2 text-slate-400 text-[11px] max-w-[180px] truncate">{notesText}</td>
    </tr>
  );
}

function PatternCard({ pattern, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen || false);
  const sections = pattern.sections || [];

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-50 border border-blue-100 rounded-lg flex items-center justify-center text-blue-700 text-xs font-bold shrink-0">
            {pattern.class_name}
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900 flex items-center gap-2">
              {pattern.subject}
              {pattern.sqp_year && (
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                  {pattern.sqp_year}
                </span>
              )}
            </p>
            <p className="text-xs text-slate-400">{pattern.name}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-sm font-semibold text-slate-800">{pattern.total_marks}M</p>
            <p className="text-xs text-slate-400">{pattern.total_questions}Q</p>
          </div>
          <span className="text-xs text-slate-400">{sections.length} sections</span>
          {open
            ? <ChevronDown className="w-4 h-4 text-slate-400" />
            : <ChevronRight className="w-4 h-4 text-slate-400" />}
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-100 bg-slate-50 overflow-x-auto">
          {sections.length === 0 ? (
            <p className="px-5 py-4 text-xs text-slate-400">No section data available</p>
          ) : (
            <table className="w-full text-sm min-w-[700px]">
              <thead>
                <tr className="bg-slate-100 text-slate-500 text-[10px] uppercase tracking-wider">
                  <th className="px-3 py-2 text-left">Section</th>
                  <th className="px-3 py-2 text-left">Title</th>
                  <th className="px-3 py-2 text-center">Questions</th>
                  <th className="px-3 py-2 text-center">Marks Each</th>
                  <th className="px-3 py-2 text-center">Total Marks</th>
                  <th className="px-3 py-2 text-center">Choice</th>
                  <th className="px-3 py-2 text-center">Blueprint Info</th>
                  <th className="px-3 py-2 text-left">Notes / Types</th>
                </tr>
              </thead>
              <tbody>
                {sections.map((sec, i) => <SectionRow key={i} sec={sec} />)}
              </tbody>
              <tfoot>
                <tr className="bg-white border-t border-slate-200">
                  <td colSpan={4} className="px-3 py-2 text-xs text-slate-400 font-semibold">Total</td>
                  <td className="px-3 py-2 text-center text-xs font-bold text-blue-700">{pattern.total_marks}M</td>
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
  }, []);

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
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
            <ClipboardList className="w-5 h-5 text-blue-600" />
            CBSE Patterns
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {patterns.length} official patterns · Academic year 2025-26
          </p>
        </div>
        <button
          onClick={handleUpdate}
          disabled={updating}
          className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-900 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-60 shrink-0"
        >
          {updating
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <RefreshCw className="w-4 h-4" />}
          {updating ? `Updating ${updateProgress.current}/${updateProgress.total}…` : 'Update to Latest (2025-26)'}
        </button>
      </div>

      {/* Progress bar while updating */}
      {updating && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-3">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-blue-700 font-medium">{updateProgress.current_subject || 'Initialising…'}</span>
            <span className="text-blue-400">{updateProgress.current}/{updateProgress.total}</span>
          </div>
          <div className="w-full bg-blue-100 rounded-full h-1.5">
            <div
              className="bg-blue-600 h-1.5 rounded-full transition-all duration-500"
              style={{ width: updateProgress.total ? `${(updateProgress.current / updateProgress.total) * 100}%` : '2%' }}
            />
          </div>
          <p className="text-[11px] text-blue-400 mt-1.5">Using DeepSeek V3.2 via Bedrock Mantle</p>
        </div>
      )}

      {updateDone && (
        <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-xl px-5 py-3 text-sm text-emerald-700">
          <CheckCircle className="w-4 h-4 shrink-0" />
          Updated {updateProgress.results.filter(r => r.status === 'updated').length} ·{' '}
          Skipped {updateProgress.results.filter(r => r.status === 'skipped').length} (already 2025-26) ·{' '}
          Errors {updateProgress.results.filter(r => r.status === 'error').length}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search subject…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
          {['all', '6', '7', '8', '9', '10', '11', '12'].map(cls => (
            <button
              key={cls}
              onClick={() => setClassFilter(cls)}
              className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                classFilter === cls ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {cls === 'all' ? 'All' : `Class ${cls}`}
            </button>
          ))}
        </div>
      </div>

      {/* Pattern list */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-slate-400 text-sm">No patterns match your filter</div>
      ) : (
        Object.entries(grouped).map(([cls, items]) => (
          <div key={cls} className="space-y-2">
            <div className="flex items-center gap-2 px-1">
              <BookOpen className="w-4 h-4 text-slate-400" />
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Class {cls}</h2>
              <span className="text-xs text-slate-400">— {items.length} subjects</span>
            </div>
            <div className="space-y-2">
              {items.map(p => (
                <div key={p.id} className="relative">
                  {updatedIds.has(p.id) && (
                    <span className="absolute right-14 top-3.5 z-10 inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-600">
                      <CheckCircle className="w-3 h-3" /> Updated
                    </span>
                  )}
                  {skippedIds.has(p.id) && (
                    <span className="absolute right-14 top-3.5 z-10 inline-flex items-center gap-1 text-[10px] font-semibold text-slate-400">
                      Already 2025-26
                    </span>
                  )}
                  {errorIds.has(p.id) && (
                    <span className="absolute right-14 top-3.5 z-10 inline-flex items-center gap-1 text-[10px] font-semibold text-red-500">
                      <XCircle className="w-3 h-3" /> Error
                    </span>
                  )}
                  <PatternCard pattern={p} />
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
