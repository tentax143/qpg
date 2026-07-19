'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import {
  Sparkles, Play, Loader2, CheckCircle, XCircle, AlertTriangle,
  FileText, BookOpen, Languages, Bug, Layers, X,
  ChevronDown, ChevronRight, Search, RefreshCw, Square, Tag,
} from 'lucide-react';

// Chapter-kind badge colors (ChapterInfo.kind — one kind per chapter).
const KIND_STYLES = {
  poem: 'text-purple-600 bg-purple-50 border-purple-200',
  prose: 'text-sky-600 bg-sky-50 border-sky-200',
  drama: 'text-pink-600 bg-pink-50 border-pink-200',
  grammar: 'text-amber-700 bg-amber-50 border-amber-200',
  supplementary: 'text-teal-600 bg-teal-50 border-teal-200',
};

function StatCard({ icon: Icon, label, value, sub, tone = 'slate' }) {
  const tones = {
    slate: 'text-slate-700 bg-slate-50 border-slate-200',
    blue: 'text-blue-700 bg-blue-50 border-blue-100',
    emerald: 'text-emerald-700 bg-emerald-50 border-emerald-100',
    amber: 'text-amber-700 bg-amber-50 border-amber-200',
    red: 'text-red-600 bg-red-50 border-red-200',
  };
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-7 h-7 rounded-lg border flex items-center justify-center ${tones[tone]}`}>
          <Icon className="w-3.5 h-3.5" />
        </span>
        <span className="text-xs text-slate-400 uppercase tracking-wider font-semibold">{label}</span>
      </div>
      <p className="text-2xl font-semibold text-slate-900">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function EnrichmentPage() {
  const router = useRouter();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const pollRef = useRef(null);
  const aliveRef = useRef(true);   // a resolved request must never re-arm polling after unmount
  const failsRef = useRef(0);      // consecutive poll failures
  const wasRunningRef = useRef(false);

  // Corpus browser (class → subject → chapter drill-down)
  const [coverage, setCoverage] = useState([]);
  const [covLoading, setCovLoading] = useState(true);
  const [classFilter, setClassFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [openUnits, setOpenUnits] = useState({});
  const [unitDetail, setUnitDetail] = useState({});

  useEffect(() => {
    aliveRef.current = true;
    const u = JSON.parse(localStorage.getItem('user') || 'null');
    if (!u || u.role !== 'superadmin') { router.replace('/dashboard'); return; }
    load(true);
    loadCoverage();
    return () => { aliveRef.current = false; stopPolling(); };
  }, [router]);

  async function loadCoverage() {
    setCovLoading(true);
    try {
      const r = await apiClient.get('/admin/enrichment/coverage/');
      if (!aliveRef.current) return;
      setCoverage(r.data.rows || []);
      setUnitDetail({});   // drill-down data may be stale after a run
    } catch { /* browser is best-effort; stats banner reports real errors */ }
    finally { if (aliveRef.current) setCovLoading(false); }
  }

  const unitKey = r => `${r.class_name}||${r.subject}||${r.unit ?? ''}`;

  async function toggleUnit(r) {
    const key = unitKey(r);
    const opening = !openUnits[key];
    setOpenUnits(s => ({ ...s, [key]: opening }));
    if (opening && !unitDetail[key]) {
      setUnitDetail(s => ({ ...s, [key]: 'loading' }));
      try {
        const res = await apiClient.get('/admin/enrichment/unit/', {
          params: { class: r.class_name, subject: r.subject, unit: r.unit || '' },
        });
        if (aliveRef.current) setUnitDetail(s => ({ ...s, [key]: res.data }));
      } catch {
        if (aliveRef.current) setUnitDetail(s => ({ ...s, [key]: null }));
      }
    }
  }

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function load(initial = false) {
    if (initial) setLoading(true);
    try {
      const r = await apiClient.get('/admin/enrichment/stats/');
      if (!aliveRef.current) return;
      failsRef.current = 0;
      setStats(r.data);
      syncPolling(r.data);
      const nowActive = ['running', 'stopping'].includes(r.data?.latest_run?.status);
      if (wasRunningRef.current && !nowActive) loadCoverage();  // refresh browser when a run finishes/stops
      wasRunningRef.current = nowActive;
    } catch (e) {
      if (!aliveRef.current) return;
      failsRef.current += 1;
      // A transient miss (dev-server restart, 502) mid-run must not freeze the live
      // progress view — keep polling and only give up after several straight failures.
      if (!pollRef.current || failsRef.current >= 5) {
        setError(e.response?.data?.error || 'Failed to load enrichment stats');
        stopPolling();
      }
    } finally {
      if (initial && aliveRef.current) setLoading(false);
    }
  }

  // Poll live DB counters (not Celery state) every 3s while a run is in progress OR
  // draining after a stop — progress survives page refreshes because it is recomputed
  // from the run row. Polling only ends on a terminal status (done/failed/stopped).
  function syncPolling(data) {
    if (!aliveRef.current) { stopPolling(); return; }
    const active = ['running', 'stopping'].includes(data?.latest_run?.status);
    if (active && !pollRef.current) {
      pollRef.current = setInterval(() => load(false), 3000);
    } else if (!active) {
      stopPolling();
    }
  }

  async function handleStop() {
    setStopping(true);
    setError(null);
    try {
      const r = await apiClient.post('/admin/enrichment/stop/');
      if (aliveRef.current && r.data.run) {
        setStats(s => ({ ...(s || {}), latest_run: r.data.run }));
        // Keep polling: the run drains asynchronously ('stopping' → 'stopped') — the
        // in-flight material pauses at its next LLM batch, queued tasks report in as
        // drained, and the banner flips when the run actually reaches 'stopped'.
        syncPolling({ latest_run: r.data.run });
        if (r.data.run.status === 'stopping') {
          setNotice('Stop requested — in-flight work pauses at the next batch; queued materials are draining. Nothing partial is kept, so resuming is safe.');
        }
        load(false);
      }
    } catch (e) {
      if (aliveRef.current) setError(e.response?.data?.error || 'Failed to stop the run');
    } finally {
      if (aliveRef.current) setStopping(false);
    }
  }

  async function handleClassify() {
    setClassifying(true);
    setError(null);
    setNotice(null);
    try {
      const r = await apiClient.post('/admin/enrichment/classify/', {});
      setNotice(r.data.detail || 'Chapter classification queued.');
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to queue chapter classification');
    } finally {
      setClassifying(false);
    }
  }

  async function handleRun(force = false) {
    if (force && !window.confirm(
      'Re-process ALL chunks, including already-labeled ones? This re-bills the LLM for the whole corpus.')) {
      return;
    }
    setStarting(true);
    setError(null);
    setNotice(null);
    try {
      const r = await apiClient.post('/admin/enrichment/run/', { force });
      if (!r.data.run) {
        setNotice(r.data.detail || 'Nothing to enrich.');
      } else {
        setStats(s => ({ ...(s || {}), latest_run: r.data.run }));
        syncPolling({ latest_run: r.data.run });
      }
      load(false);
    } catch (e) {
      if (e.response?.status === 409 && e.response.data?.run) {
        setStats(s => ({ ...(s || {}), latest_run: e.response.data.run }));
        syncPolling({ latest_run: e.response.data.run });
        setNotice(`${e.response.data?.error || 'An enrichment run is already in progress'} — showing its live status.`);
      } else {
        setError(e.response?.data?.error || 'Failed to start the enrichment run');
      }
    } finally {
      setStarting(false);
    }
  }

  const run = stats?.latest_run;
  const running = run?.status === 'running';
  const draining = run?.status === 'stopping';
  const active = running || draining;
  const processed = run ? run.done_groups + run.failed_groups + (run.drained_groups || 0) : 0;
  const pct = run?.total_groups
    ? Math.min(100, Math.round((processed / run.total_groups) * 100)) : 0;
  const enrichedPct = stats?.total_chunks
    ? Math.round((stats.enriched_chunks / stats.total_chunks) * 100) : 0;
  const fmt = n => (n ?? 0).toLocaleString();

  // Corpus browser: filter → group class → subject → chapter rows
  const classes = [...new Set(coverage.map(r => r.class_name))]
    .sort((a, b) => (Number(a) - Number(b)) || String(a).localeCompare(String(b)));
  const q = search.trim().toLowerCase();
  const grouped = coverage
    .filter(r => (classFilter === 'all' || r.class_name === classFilter) &&
                 (!q || r.subject.toLowerCase().includes(q) || (r.unit || '').toLowerCase().includes(q)))
    .reduce((acc, r) => {
      ((acc[r.class_name] ||= {})[r.subject] ||= []).push(r);
      return acc;
    }, {});

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-blue-600" />
            Chunk Enrichment
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            LLM-labels every stored chunk (true chapter link, cleaned content, garbled flag)
            and writes chapter summaries. New uploads are enriched automatically.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
          {draining ? (
            <span className="inline-flex items-center gap-2 px-4 py-2 bg-amber-50 border border-amber-200 text-amber-700 text-sm font-medium rounded-lg">
              <Loader2 className="w-4 h-4 animate-spin" />
              Stopping — draining queue…
            </span>
          ) : running ? (
            <button
              onClick={handleStop}
              disabled={stopping}
              className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
            >
              {stopping
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Square className="w-4 h-4" />}
              {stopping ? 'Stopping…' : 'Stop'}
            </button>
          ) : (
            <>
              <button
                onClick={handleClassify}
                disabled={classifying || loading}
                className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                title="Tag every chapter as prose / poem / drama / grammar / supplementary (cheap — uses stored summaries)"
              >
                {classifying
                  ? <Loader2 className="w-4 h-4 animate-spin" />
                  : <Tag className="w-4 h-4" />}
                Classify Chapters
              </button>
              <button
                onClick={() => handleRun(true)}
                disabled={starting || loading}
                className="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                title="Re-run everything, including already-labeled chunks"
              >
                <RefreshCw className="w-4 h-4" />
                Re-process All
              </button>
              <button
                onClick={() => handleRun(false)}
                disabled={starting || loading}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
              >
                {starting
                  ? <Loader2 className="w-4 h-4 animate-spin" />
                  : <Play className="w-4 h-4" />}
                Process Stored Chunks
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}
      {notice && (
        <div className="flex items-start gap-2 bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-700">
          <span className="flex-1">{notice}</span>
          <button onClick={() => setNotice(null)}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {/* Live run progress (running, or draining after a stop request) */}
      {active && (
        <div className={`border rounded-xl px-5 py-3 ${
          draining ? 'bg-amber-50 border-amber-200' : 'bg-blue-50 border-blue-200'}`}>
          <div className="flex items-center justify-between text-sm mb-2">
            <span className={`font-medium ${draining ? 'text-amber-700' : 'text-blue-700'}`}>
              {draining
                ? <>Stopping — waiting for in-flight work to pause and the queue to drain…</>
                : <>Enriching materials — {run.chunks_labeled.toLocaleString()} chunks labeled,{' '}
                   {run.summaries_created} summaries written</>}
            </span>
            <span className={draining ? 'text-amber-500' : 'text-blue-400'}>
              {processed}/{run.total_groups} materials
            </span>
          </div>
          <div className={`w-full rounded-full h-1.5 ${draining ? 'bg-amber-100' : 'bg-blue-100'}`}>
            <div
              className={`h-1.5 rounded-full transition-all duration-500 ${
                draining ? 'bg-amber-500' : 'bg-blue-600'}`}
              style={{ width: run.total_groups ? `${pct}%` : '2%' }}
            />
          </div>
          <p className={`text-[11px] mt-1.5 ${draining ? 'text-amber-500' : 'text-blue-400'}`}>
            {draining
              ? 'Nothing partial is kept — a stopped material stays pending and is redone on resume'
              : 'Materials processed in parallel groups · DeepSeek V3.2 via Bedrock Mantle · safe to leave this page'}
          </p>
        </div>
      )}

      {/* Last run result */}
      {run && !active && (
        <div className={`flex items-start gap-2 rounded-xl px-5 py-3 text-sm border ${
          run.status === 'done'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : run.status === 'stopped'
              ? 'bg-amber-50 border-amber-200 text-amber-700'
              : 'bg-red-50 border-red-200 text-red-700'
        }`}>
          {run.status === 'done'
            ? <CheckCircle className="w-4 h-4 shrink-0 mt-0.5" />
            : run.status === 'stopped'
              ? <Square className="w-4 h-4 shrink-0 mt-0.5" />
              : <XCircle className="w-4 h-4 shrink-0 mt-0.5" />}
          <div className="flex-1">
            <p>
              Last run {run.status === 'done' ? 'completed'
                : run.status === 'stopped' ? 'was stopped' : 'failed'}:{' '}
              {run.done_groups}/{run.total_groups} materials ·{' '}
              {run.chunks_labeled.toLocaleString()} chunks labeled ·{' '}
              {run.summaries_created} summaries · {run.garbled_found} garbled ·{' '}
              {(run.input_tokens + run.output_tokens).toLocaleString()} tokens · ₹{run.cost}
              {run.failed_groups > 0 && ` · ${run.failed_groups} materials failed`}
              {(run.drained_groups || 0) > 0 && ` · ${run.drained_groups} paused`}
              {run.status === 'stopped' && ' — press "Process Stored Chunks" to resume the rest.'}
            </p>
            {(run.error_samples || []).length > 0 && (
              <ul className="mt-1.5 space-y-0.5 text-xs opacity-80 list-disc list-inside">
                {run.error_samples.slice(0, 5).map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* Coverage stats */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
        </div>
      ) : stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            <StatCard icon={Layers} label="Total chunks" value={fmt(stats.total_chunks)} />
            <StatCard icon={CheckCircle} label="Enriched" tone="emerald"
                      value={fmt(stats.enriched_chunks)} sub={`${enrichedPct}% of corpus`} />
            <StatCard icon={FileText} label="Pending" tone="blue"
                      value={fmt(stats.pending_chunks)}
                      sub={`${fmt(stats.pending_materials)} materials`} />
            <StatCard icon={BookOpen} label="Summaries" tone="blue" value={fmt(stats.summary_chunks)} />
            <StatCard icon={Bug} label="Garbled" tone={stats.garbled_chunks ? 'amber' : 'slate'}
                      value={fmt(stats.garbled_chunks)} sub="extraction noise flagged" />
          </div>

          {stats.unlinked_chunks > 0 && (
            <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-700">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {fmt(stats.unlinked_chunks)} chunks have no Material record and cannot be enriched
              (legacy rows) — they are excluded from the pending count.
            </div>
          )}

          {/* Corpus browser: class → subject → chapter */}
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-slate-400" /> What&apos;s in the store
              </h2>
              <div className="flex items-center gap-2 flex-wrap">
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Filter subject / chapter…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
                  {['all', ...classes].map(cls => (
                    <button
                      key={cls}
                      onClick={() => setClassFilter(cls)}
                      className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                        classFilter === cls ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                      }`}
                    >
                      {cls === 'all' ? 'All' : `Class ${cls}`}
                    </button>
                  ))}
                </div>
                <button
                  onClick={loadCoverage}
                  title="Refresh"
                  className="p-1.5 text-slate-400 hover:text-slate-600 border border-slate-200 rounded-lg"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${covLoading ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>

            {covLoading ? (
              <div className="flex justify-center py-10">
                <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
              </div>
            ) : Object.keys(grouped).length === 0 ? (
              <div className="text-center py-10 text-slate-400 text-sm">
                {coverage.length === 0 ? 'No chunks stored yet' : 'Nothing matches your filter'}
              </div>
            ) : (
              Object.entries(grouped).map(([cls, subjects]) => (
                <div key={cls} className="space-y-2">
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-1">Class {cls}</h3>
                  {Object.entries(subjects).map(([subj, rows]) => (
                    <div key={subj} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                      <div className="px-4 py-2.5 bg-slate-50 border-b border-slate-100 flex items-center justify-between gap-3">
                        <span className="text-sm font-semibold text-slate-800 capitalize truncate">{subj}</span>
                        <span className="text-xs text-slate-400 shrink-0">
                          {rows.length} chapter{rows.length === 1 ? '' : 's'} ·{' '}
                          {fmt(rows.reduce((n, r) => n + r.chunks, 0))} chunks
                        </span>
                      </div>
                      <div className="divide-y divide-slate-100">
                        {rows.map(r => {
                          const key = unitKey(r);
                          const open = openUnits[key];
                          const det = unitDetail[key];
                          const unitPct = r.chunks ? Math.round((r.enriched / r.chunks) * 100) : 0;
                          return (
                            <div key={key}>
                              <button
                                onClick={() => toggleUnit(r)}
                                className="w-full px-4 py-2 flex items-center gap-3 hover:bg-slate-50 transition-colors text-left"
                              >
                                {open
                                  ? <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                                  : <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
                                <span className="flex-1 text-sm text-slate-700 truncate">
                                  {r.unit || '(no chapter link)'}
                                </span>
                                {r.kind && (
                                  <span className={`text-[10px] font-semibold rounded px-1.5 py-0.5 shrink-0 border ${
                                    KIND_STYLES[r.kind] || 'text-slate-600 bg-slate-50 border-slate-200'}`}>
                                    {r.kind}
                                  </span>
                                )}
                                {r.garbled > 0 && (
                                  <span className="text-[10px] font-semibold text-amber-600 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5 shrink-0">
                                    {r.garbled} garbled
                                  </span>
                                )}
                                {r.cleaned > 0 && (
                                  <span className="text-[10px] font-semibold text-blue-600 bg-blue-50 border border-blue-100 rounded px-1.5 py-0.5 shrink-0">
                                    {r.cleaned} cleaned
                                  </span>
                                )}
                                {r.summaries > 0 && (
                                  <span className="text-[10px] font-semibold text-emerald-600 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5 shrink-0">
                                    summary ✓
                                  </span>
                                )}
                                <span className="text-xs text-slate-400 w-28 text-right shrink-0">
                                  {r.enriched}/{r.chunks} enriched
                                </span>
                                <span className="w-16 bg-slate-100 h-1.5 rounded-full shrink-0">
                                  <span
                                    className="block bg-emerald-500 h-1.5 rounded-full"
                                    style={{ width: `${unitPct}%` }}
                                  />
                                </span>
                              </button>
                              {open && (
                                <div className="px-11 pb-3 text-xs text-slate-500 space-y-2">
                                  {det === 'loading' ? (
                                    <span className="inline-flex items-center gap-1.5 text-slate-400">
                                      <Loader2 className="w-3 h-3 animate-spin" /> Loading…
                                    </span>
                                  ) : det ? (
                                    <>
                                      {det.summary && (
                                        <p className="bg-slate-50 border border-slate-100 rounded-lg p-2.5 text-slate-600 leading-relaxed">
                                          <span className="font-medium">Chapter summary:</span> {det.summary}
                                        </p>
                                      )}
                                      {(det.chunks || []).length > 0 ? (
                                        <div className="border border-slate-100 rounded-lg max-h-80 overflow-y-auto divide-y divide-slate-100">
                                          {det.chunks.map(c => (
                                            <div key={c.id ?? c.index} className={`p-2.5 ${c.garbled ? 'bg-amber-50/60' : ''}`}>
                                              <div className="flex items-center gap-1.5 mb-1">
                                                <span className="font-mono text-[10px] text-slate-400">#{c.index + 1}</span>
                                                {c.cleaned && (
                                                  <span className="text-[9px] font-semibold text-blue-600 bg-blue-50 border border-blue-100 rounded px-1 py-px">
                                                    cleaned
                                                  </span>
                                                )}
                                                {c.garbled && (
                                                  <span className="text-[9px] font-semibold text-amber-600 bg-amber-50 border border-amber-200 rounded px-1 py-px">
                                                    garbled
                                                  </span>
                                                )}
                                                {!c.enriched && (
                                                  <span className="text-[9px] font-semibold text-slate-400 bg-slate-50 border border-slate-200 rounded px-1 py-px">
                                                    not processed
                                                  </span>
                                                )}
                                              </div>
                                              <p className="text-[11px] text-slate-600 leading-relaxed whitespace-pre-wrap break-words">
                                                {c.text}
                                              </p>
                                            </div>
                                          ))}
                                        </div>
                                      ) : (
                                        <p className="text-slate-400">No chunks under this chapter.</p>
                                      )}
                                    </>
                                  ) : (
                                    <p className="text-slate-400">Could not load chapter detail.</p>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-5 text-sm text-slate-500 space-y-2">
            <p className="font-medium text-slate-700 flex items-center gap-2">
              <Languages className="w-4 h-4 text-slate-400" /> What enrichment stores
            </p>
            <p>
              Every chunk ends up carrying its <span className="font-mono text-xs bg-slate-100 rounded px-1">class</span>,{' '}
              <span className="font-mono text-xs bg-slate-100 rounded px-1">subject</span>, true{' '}
              <span className="font-mono text-xs bg-slate-100 rounded px-1">chapter</span> link, and its actual
              content — noisy chunks (page numbers, headers, unrelated matter glued in) get a cleaned copy in{' '}
              <span className="font-mono text-xs bg-slate-100 rounded px-1">content_clean</span> while the
              original text is never changed, and unreadable extractions are flagged{' '}
              <span className="font-mono text-xs bg-slate-100 rounded px-1">garbled</span>. Every chapter also
              gets a 300-500 character summary used for whole-chapter grounding during paper generation.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
