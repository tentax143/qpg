'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import {
  Sparkles, Play, Loader2, CheckCircle, XCircle, AlertTriangle,
  FileText, BookOpen, Languages, Bug, Layers, X,
  ChevronDown, ChevronRight, Search, RefreshCw,
} from 'lucide-react';

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
  const [force, setForce] = useState(false);
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
      const nowRunning = r.data?.latest_run?.status === 'running';
      if (wasRunningRef.current && !nowRunning) loadCoverage();  // refresh browser when a run finishes
      wasRunningRef.current = nowRunning;
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

  // Poll live DB counters (not Celery state) every 3s while a run is in progress —
  // progress survives page refreshes because it is recomputed from the run row.
  function syncPolling(data) {
    if (!aliveRef.current) { stopPolling(); return; }
    const running = data?.latest_run?.status === 'running';
    if (running && !pollRef.current) {
      pollRef.current = setInterval(() => load(false), 3000);
    } else if (!running) {
      stopPolling();
    }
  }

  async function handleRun() {
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
        setNotice('An enrichment run is already in progress — showing its live status.');
      } else {
        setError(e.response?.data?.error || 'Failed to start the enrichment run');
      }
    } finally {
      setStarting(false);
    }
  }

  const run = stats?.latest_run;
  const running = run?.status === 'running';
  const processed = run ? run.done_groups + run.failed_groups : 0;
  const pct = run?.total_groups
    ? Math.min(100, Math.round((processed / run.total_groups) * 100)) : 0;
  const enrichedPct = stats?.total_chunks
    ? Math.round((stats.enriched_chunks / stats.total_chunks) * 100) : 0;
  const fmt = n => (n ?? 0).toLocaleString();

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
            LLM-labels every stored chunk (content kind, language, true chapter, garbled flag)
            and writes chapter summaries. New uploads are enriched automatically.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <label className="flex items-center gap-2 text-sm text-slate-500 select-none cursor-pointer">
            <input
              type="checkbox"
              checked={force}
              onChange={e => setForce(e.target.checked)}
              disabled={running}
              className="w-4 h-4 rounded border-slate-300 accent-blue-600"
            />
            Re-process already labeled
          </label>
          <button
            onClick={handleRun}
            disabled={running || starting || loading}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
          >
            {running || starting
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <Play className="w-4 h-4" />}
            {running ? `Processing ${processed}/${run.total_groups}…` : 'Process Stored Chunks'}
          </button>
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

      {/* Live run progress */}
      {running && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-3">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-blue-700 font-medium">
              Enriching materials — {run.chunks_labeled.toLocaleString()} chunks labeled,{' '}
              {run.summaries_created} summaries written
            </span>
            <span className="text-blue-400">{processed}/{run.total_groups} materials</span>
          </div>
          <div className="w-full bg-blue-100 rounded-full h-1.5">
            <div
              className="bg-blue-600 h-1.5 rounded-full transition-all duration-500"
              style={{ width: run.total_groups ? `${pct}%` : '2%' }}
            />
          </div>
          <p className="text-[11px] text-blue-400 mt-1.5">
            One material per Celery task · DeepSeek V3.2 via Bedrock Mantle · safe to leave this page
          </p>
        </div>
      )}

      {/* Last run result */}
      {run && !running && (
        <div className={`flex items-start gap-2 rounded-xl px-5 py-3 text-sm border ${
          run.status === 'done'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-red-50 border-red-200 text-red-700'
        }`}>
          {run.status === 'done'
            ? <CheckCircle className="w-4 h-4 shrink-0 mt-0.5" />
            : <XCircle className="w-4 h-4 shrink-0 mt-0.5" />}
          <div className="flex-1">
            <p>
              Last run {run.status === 'done' ? 'completed' : 'failed'}:{' '}
              {run.done_groups}/{run.total_groups} materials ·{' '}
              {run.chunks_labeled.toLocaleString()} chunks labeled ·{' '}
              {run.summaries_created} summaries · {run.garbled_found} garbled ·{' '}
              {(run.input_tokens + run.output_tokens).toLocaleString()} tokens · ₹{run.cost}
              {run.failed_groups > 0 && ` · ${run.failed_groups} materials failed`}
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

          <div className="bg-white border border-slate-200 rounded-xl p-5 text-sm text-slate-500 space-y-2">
            <p className="font-medium text-slate-700 flex items-center gap-2">
              <Languages className="w-4 h-4 text-slate-400" /> What enrichment stores
            </p>
            <p>
              Each chunk gets <span className="font-mono text-xs bg-slate-100 rounded px-1">content_kinds</span>{' '}
              (prose / poem / grammar for languages · concept / example / activity for science, maths &
              social · exercise / supplementary / intro / other for any subject),{' '}
              <span className="font-mono text-xs bg-slate-100 rounded px-1">language</span>, a{' '}
              <span className="font-mono text-xs bg-slate-100 rounded px-1">garbled</span> flag, and its true
              per-chunk chapter link. Mixed or noisy chunks (lesson text with book-back questions or page
              noise glued in) also get a cleaned copy in{' '}
              <span className="font-mono text-xs bg-slate-100 rounded px-1">content_clean</span> — the original
              text is never changed. Every chapter also gets a 300-500 character summary chunk used for
              whole-chapter grounding. Labels power chapter-balanced retrieval during paper generation.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
